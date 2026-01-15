"""Gitea API client for teax operations."""

import os
import warnings
from typing import Any
from urllib.parse import quote

import httpx

from teax.config import get_default_login, get_login_by_name
from teax.models import Comment, Dependency, Issue, Label, Milestone, TeaLogin


def _get_ssl_verify() -> bool | str:
    """Get SSL verification setting.

    Environment variables (checked in order):
    - TEAX_CA_BUNDLE: Path to custom CA certificate bundle (e.g., /path/to/ca.pem)
    - TEAX_INSECURE=1: Disable SSL verification entirely (not recommended)

    Returns:
        True for default verification, False to disable, or path string for custom CA.
    """
    ca_bundle = os.environ.get("TEAX_CA_BUNDLE", "").strip()
    if ca_bundle:
        return ca_bundle
    if os.environ.get("TEAX_INSECURE", "").lower() in ("1", "true", "yes"):
        warnings.warn(
            "TEAX_INSECURE is set: SSL certificate verification is disabled. "
            "This makes connections vulnerable to man-in-the-middle attacks. "
            "Consider using TEAX_CA_BUNDLE with a custom CA certificate instead.",
            UserWarning,
            stacklevel=3,
        )
        return False
    return True


def _seg(s: str) -> str:
    """URL-encode a path segment to prevent path traversal.

    Encodes special characters including '/' which prevents path traversal
    attacks (e.g., '../admin' becomes '..%2Fadmin'). The encoded slash
    is treated as part of the segment, not a path separator.
    """
    return quote(s, safe="")


def _normalize_base_url(url: str) -> str:
    """Normalize a base URL for API requests.

    Handles various URL formats:
    - Strips trailing slashes and /api/v1 if already present
    - Returns a clean base URL ending with /api/v1/
    """
    url = url.rstrip("/")
    # Remove any existing /api/v1 suffix to avoid duplication
    if url.endswith("/api/v1"):
        url = url[:-7]
    elif url.endswith("/api"):
        url = url[:-4]
    return url + "/api/v1/"


class GiteaClient:
    """HTTP client for Gitea API operations not covered by tea CLI."""

    def __init__(self, login: TeaLogin | None = None, login_name: str | None = None):
        """Initialize the Gitea client.

        Args:
            login: Optional pre-loaded login config
            login_name: Optional login name to use (looks up from tea config)

        Raises:
            ValueError: If the login URL uses HTTP (not HTTPS) and
                TEAX_ALLOW_INSECURE_HTTP is not set. Plain HTTP would send
                API tokens unencrypted, risking credential exposure.
        """
        if login is not None:
            self._login = login
        elif login_name is not None:
            self._login = get_login_by_name(login_name)
        else:
            self._login = get_default_login()

        # Normalize base URL to handle various formats (with/without /api/v1)
        base = _normalize_base_url(self._login.url)

        # Block HTTP by default - tokens would be sent unencrypted
        if base.startswith("http://"):
            if os.environ.get("TEAX_ALLOW_INSECURE_HTTP", "").lower() in (
                "1",
                "true",
                "yes",
            ):
                warnings.warn(
                    f"Using insecure HTTP connection to {self._login.name}. "
                    "API token will be sent unencrypted. Consider using HTTPS.",
                    UserWarning,
                    stacklevel=2,
                )
            else:
                raise ValueError(
                    f"Refusing to connect to {self._login.name} over plain HTTP. "
                    "API tokens would be sent unencrypted, risking credential exposure. "
                    "Use HTTPS, or set TEAX_ALLOW_INSECURE_HTTP=1 to proceed anyway."
                )

        self._client = httpx.Client(
            base_url=base,
            headers={
                "Authorization": f"token {self._login.token.get_secret_value()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
            verify=_get_ssl_verify(),
            # Disable trust_env to prevent token leakage via HTTP_PROXY/HTTPS_PROXY
            trust_env=False,
        )
        # Cache for label name -> ID mapping per repo (cleared on close)
        self._label_cache: dict[str, dict[str, int]] = {}
        # Cache for milestone title -> ID mapping per repo (cleared on close)
        self._milestone_cache: dict[str, dict[str, int]] = {}
        # Track the state filter used to populate milestone cache
        self._milestone_cache_state: dict[str, str] = {}

    def close(self) -> None:
        """Close the HTTP client and clear caches."""
        self._client.close()
        self._label_cache.clear()
        self._milestone_cache.clear()
        self._milestone_cache_state.clear()

    def __enter__(self) -> "GiteaClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def base_url(self) -> str:
        """Get the base URL for the Gitea instance."""
        return self._login.url

    # --- Issue Operations ---

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: list[int] | None = None,
    ) -> Issue:
        """Create a new issue.

        Args:
            owner: Repository owner
            repo: Repository name
            title: Issue title
            body: Issue body (optional)
            labels: Label IDs to apply (optional)

        Returns:
            Created issue
        """
        data: dict[str, Any] = {"title": title}
        if body:
            data["body"] = body
        if labels:
            data["labels"] = labels

        response = self._client.post(
            f"repos/{_seg(owner)}/{_seg(repo)}/issues",
            json=data,
        )
        response.raise_for_status()
        return Issue.model_validate(response.json())

    def get_issue(self, owner: str, repo: str, index: int) -> Issue:
        """Get an issue by number.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number

        Returns:
            Issue details
        """
        response = self._client.get(f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}")
        response.raise_for_status()
        return Issue.model_validate(response.json())

    def list_comments(
        self, owner: str, repo: str, index: int, *, max_pages: int = 100
    ) -> list[Comment]:
        """List all comments on an issue.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number
            max_pages: Maximum pages to fetch (default 100, prevents DoS from
                misbehaving servers)

        Returns:
            List of comments on the issue
        """
        comments: list[Comment] = []
        page = 1
        truncated = False
        while page <= max_pages:
            response = self._client.get(
                f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}/comments",
                params={"page": page, "limit": 50},
            )
            response.raise_for_status()
            data = response.json()
            if not data:
                break
            comments.extend(Comment.model_validate(c) for c in data)
            if len(data) < 50:
                break
            page += 1
        else:
            # Loop completed without break - hit max_pages ceiling
            truncated = True
        if truncated:
            warnings.warn(
                f"Comments list truncated at {max_pages} pages "
                f"({len(comments)} items). Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )
        return comments

    def edit_issue(
        self,
        owner: str,
        repo: str,
        index: int,
        *,
        title: str | None = None,
        body: str | None = None,
        assignees: list[str] | None = None,
        milestone: int | None = None,
    ) -> Issue:
        """Edit an existing issue.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number
            title: New title (optional)
            body: New body (optional)
            assignees: New assignee list (optional)
            milestone: New milestone ID (optional, 0 to clear)

        Returns:
            Updated issue
        """
        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if body is not None:
            data["body"] = body
        if assignees is not None:
            data["assignees"] = assignees
        if milestone is not None:
            data["milestone"] = milestone if milestone > 0 else None

        response = self._client.patch(
            f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}",
            json=data,
        )
        response.raise_for_status()
        return Issue.model_validate(response.json())

    # --- Label Operations ---

    def get_issue_labels(self, owner: str, repo: str, index: int) -> list[Label]:
        """Get labels for an issue.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number

        Returns:
            List of labels
        """
        response = self._client.get(
            f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}/labels"
        )
        response.raise_for_status()
        return [Label.model_validate(item) for item in response.json()]

    def add_issue_labels(
        self, owner: str, repo: str, index: int, labels: list[str]
    ) -> list[Label]:
        """Add labels to an issue.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number
            labels: Label names to add

        Returns:
            Updated label list
        """
        # First get label IDs from names
        label_ids = self._resolve_label_ids(owner, repo, labels)

        response = self._client.post(
            f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}/labels",
            json={"labels": label_ids},
        )
        response.raise_for_status()
        return [Label.model_validate(item) for item in response.json()]

    def remove_issue_label(self, owner: str, repo: str, index: int, label: str) -> None:
        """Remove a label from an issue.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number
            label: Label name to remove
        """
        # Get label ID (raises ValueError if not found)
        label_ids = self._resolve_label_ids(owner, repo, [label])

        response = self._client.delete(
            f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}/labels/{label_ids[0]}"
        )
        response.raise_for_status()

    def set_issue_labels(
        self, owner: str, repo: str, index: int, labels: list[str]
    ) -> list[Label]:
        """Replace all labels on an issue.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number
            labels: Label names to set

        Returns:
            Updated label list
        """
        label_ids = self._resolve_label_ids(owner, repo, labels)

        response = self._client.put(
            f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}/labels",
            json={"labels": label_ids},
        )
        response.raise_for_status()
        return [Label.model_validate(item) for item in response.json()]

    def _resolve_label_ids(
        self, owner: str, repo: str, label_names: list[str]
    ) -> list[int]:
        """Resolve label names to IDs.

        Uses per-repo caching to avoid redundant API calls within a session.
        Automatically refreshes cache once if a label is not found.

        Args:
            owner: Repository owner
            repo: Repository name
            label_names: Label names to resolve

        Returns:
            List of label IDs
        """
        cache_key = f"{owner}/{repo}"

        def fetch_labels() -> dict[str, int]:
            """Fetch all labels with pagination (max 100 pages)."""
            all_labels: dict[str, int] = {}
            page = 1
            limit = 50
            max_pages = 100  # Prevent DoS from misbehaving servers
            truncated = False
            while page <= max_pages:
                response = self._client.get(
                    f"repos/{_seg(owner)}/{_seg(repo)}/labels",
                    params={"page": page, "limit": limit},
                )
                response.raise_for_status()
                items = response.json()
                if not items:
                    break
                for item in items:
                    all_labels[item["name"]] = item["id"]
                # If we got fewer items than the limit, we're on the last page
                if len(items) < limit:
                    break
                page += 1
            else:
                truncated = True
            if truncated:
                warnings.warn(
                    f"Labels list truncated at {max_pages} pages "
                    f"({len(all_labels)} items). Results may be incomplete.",
                    UserWarning,
                    stacklevel=4,  # Account for nested function
                )
            return all_labels

        if cache_key not in self._label_cache:
            self._label_cache[cache_key] = fetch_labels()

        all_labels = self._label_cache[cache_key]
        ids = []
        missing: list[str] = []
        for name in label_names:
            if name in all_labels:
                ids.append(all_labels[name])
            else:
                missing.append(name)

        # Retry once by refreshing cache if labels are missing
        if missing:
            self._label_cache[cache_key] = fetch_labels()
            all_labels = self._label_cache[cache_key]
            for name in missing:
                if name in all_labels:
                    ids.append(all_labels[name])
                else:
                    raise ValueError(f"Label '{name}' not found in repository")

        return ids

    # --- Dependency Operations ---

    def list_dependencies(self, owner: str, repo: str, index: int) -> list[Dependency]:
        """List issues that this issue depends on.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number

        Returns:
            List of dependency issues
        """
        response = self._client.get(
            f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}/dependencies"
        )
        response.raise_for_status()
        return [Dependency.model_validate(d) for d in response.json()]

    def list_blocks(self, owner: str, repo: str, index: int) -> list[Dependency]:
        """List issues that this issue blocks.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number

        Returns:
            List of blocked issues
        """
        response = self._client.get(
            f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}/blocks"
        )
        response.raise_for_status()
        return [Dependency.model_validate(d) for d in response.json()]

    def add_dependency(
        self,
        owner: str,
        repo: str,
        index: int,
        depends_on_owner: str,
        depends_on_repo: str,
        depends_on_index: int,
    ) -> None:
        """Add a dependency (issue depends on another).

        Args:
            owner: Repository owner of the dependent issue
            repo: Repository name of the dependent issue
            index: Issue number of the dependent issue
            depends_on_owner: Owner of the issue being depended on
            depends_on_repo: Repo of the issue being depended on
            depends_on_index: Issue number being depended on
        """
        response = self._client.post(
            f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}/dependencies",
            json={
                "owner": depends_on_owner,
                "repo": depends_on_repo,
                "index": depends_on_index,
            },
        )
        response.raise_for_status()

    def remove_dependency(
        self,
        owner: str,
        repo: str,
        index: int,
        depends_on_owner: str,
        depends_on_repo: str,
        depends_on_index: int,
    ) -> None:
        """Remove a dependency.

        Args:
            owner: Repository owner of the dependent issue
            repo: Repository name of the dependent issue
            index: Issue number of the dependent issue
            depends_on_owner: Owner of the issue being depended on
            depends_on_repo: Repo of the issue being depended on
            depends_on_index: Issue number being depended on
        """
        response = self._client.request(
            "DELETE",
            f"repos/{_seg(owner)}/{_seg(repo)}/issues/{index}/dependencies",
            json={
                "owner": depends_on_owner,
                "repo": depends_on_repo,
                "index": depends_on_index,
            },
        )
        response.raise_for_status()

    # --- Repository Label Operations ---

    def create_label(
        self,
        owner: str,
        repo: str,
        name: str,
        color: str = "e0e0e0",
        description: str = "",
    ) -> Label:
        """Create a new label in a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            name: Label name
            color: Hex color code without # (default: grey)
            description: Label description (optional)

        Returns:
            Created label
        """
        response = self._client.post(
            f"repos/{_seg(owner)}/{_seg(repo)}/labels",
            json={"name": name, "color": color, "description": description},
        )
        response.raise_for_status()
        label = Label.model_validate(response.json())
        # Update label cache with the new label (if cache exists)
        cache_key = f"{owner}/{repo}"
        if cache_key in self._label_cache:
            self._label_cache[cache_key][label.name] = label.id
        return label

    def list_repo_labels(
        self, owner: str, repo: str, *, max_pages: int = 100
    ) -> list[Label]:
        """List all labels in a repository.

        Also populates the label cache for subsequent _resolve_label_ids calls.

        Args:
            owner: Repository owner
            repo: Repository name
            max_pages: Maximum pages to fetch (default 100, prevents DoS from
                misbehaving servers)

        Returns:
            List of labels
        """
        all_labels: list[Label] = []
        page = 1
        limit = 50
        truncated = False
        while page <= max_pages:
            response = self._client.get(
                f"repos/{_seg(owner)}/{_seg(repo)}/labels",
                params={"page": page, "limit": limit},
            )
            response.raise_for_status()
            items = response.json()
            if not items:
                break
            all_labels.extend(Label.model_validate(item) for item in items)
            # If we got fewer items than the limit, we're on the last page
            if len(items) < limit:
                break
            page += 1
        else:
            truncated = True
        if truncated:
            warnings.warn(
                f"Labels list truncated at {max_pages} pages "
                f"({len(all_labels)} items). Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )

        # Populate label cache for subsequent _resolve_label_ids calls
        cache_key = f"{owner}/{repo}"
        self._label_cache[cache_key] = {label.name: label.id for label in all_labels}

        return all_labels

    # --- Milestone Operations ---

    def get_milestone(self, owner: str, repo: str, milestone_id: int) -> Milestone:
        """Get a milestone by ID.

        Args:
            owner: Repository owner
            repo: Repository name
            milestone_id: Milestone ID

        Returns:
            Milestone details

        Raises:
            httpx.HTTPStatusError: If milestone not found (404) or other error
        """
        response = self._client.get(
            f"repos/{_seg(owner)}/{_seg(repo)}/milestones/{milestone_id}"
        )
        response.raise_for_status()
        return Milestone.model_validate(response.json())

    def list_milestones(
        self, owner: str, repo: str, state: str = "all", *, max_pages: int = 100
    ) -> list[Milestone]:
        """List all milestones in a repository.

        Also populates the milestone cache for subsequent resolve_milestone calls.

        Args:
            owner: Repository owner
            repo: Repository name
            state: Filter by state: 'open', 'closed', or 'all' (default)
            max_pages: Maximum pages to fetch (default 100, prevents DoS from
                misbehaving servers)

        Returns:
            List of milestones
        """
        all_milestones: list[Milestone] = []
        page = 1
        limit = 50
        truncated = False
        while page <= max_pages:
            response = self._client.get(
                f"repos/{_seg(owner)}/{_seg(repo)}/milestones",
                params={"page": page, "limit": limit, "state": state},
            )
            response.raise_for_status()
            items = response.json()
            if not items:
                break
            all_milestones.extend(Milestone.model_validate(item) for item in items)
            # If we got fewer items than the limit, we're on the last page
            if len(items) < limit:
                break
            page += 1
        else:
            truncated = True
        if truncated:
            warnings.warn(
                f"Milestones list truncated at {max_pages} pages "
                f"({len(all_milestones)} items). Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )

        # Populate milestone cache for subsequent resolve_milestone calls
        cache_key = f"{owner}/{repo}"
        self._milestone_cache[cache_key] = {
            ms.title: ms.id for ms in all_milestones
        }
        self._milestone_cache_state[cache_key] = state

        return all_milestones

    def resolve_milestone(self, owner: str, repo: str, milestone_ref: str) -> int:
        """Resolve a milestone reference to its ID.

        The reference can be:
        - A numeric ID (e.g., "5")
        - A milestone title (e.g., "Sprint 1")

        Uses per-repo caching to avoid redundant API calls within a session.

        Args:
            owner: Repository owner
            repo: Repository name
            milestone_ref: Milestone ID or title

        Returns:
            Milestone ID

        Raises:
            ValueError: If milestone not found by name
            httpx.HTTPStatusError: If milestone not found by ID (404)
        """
        milestone_ref = milestone_ref.strip()

        # Try parsing as an integer first
        try:
            milestone_id = int(milestone_ref)
            # Validate the milestone exists (raises 404 if not)
            self.get_milestone(owner, repo, milestone_id)
            return milestone_id
        except ValueError:
            pass  # Not a numeric ID, try name lookup

        # Look up by name using cache
        # Ensure cache includes all milestones (not just open/closed)
        cache_key = f"{owner}/{repo}"
        if (
            cache_key not in self._milestone_cache
            or self._milestone_cache_state.get(cache_key) != "all"
        ):
            # Fetch all milestones to populate cache
            self.list_milestones(owner, repo, state="all")

        all_milestones = self._milestone_cache.get(cache_key, {})
        if milestone_ref in all_milestones:
            return all_milestones[milestone_ref]

        # Retry once by refreshing cache if milestone not found
        self.list_milestones(owner, repo, state="all")
        all_milestones = self._milestone_cache.get(cache_key, {})
        if milestone_ref in all_milestones:
            return all_milestones[milestone_ref]

        raise ValueError(f"Milestone '{milestone_ref}' not found in repository")
