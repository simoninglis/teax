"""Gitea API client for teax operations."""

import os
import warnings
from typing import Any
from urllib.parse import quote

import httpx

from teax.config import get_default_login, get_login_by_name
from teax.models import (
    Comment,
    Dependency,
    Issue,
    Label,
    Milestone,
    Package,
    PackageVersion,
    RegistrationToken,
    Runner,
    Secret,
    TeaLogin,
    User,
    Variable,
    Workflow,
    WorkflowJob,
    WorkflowRun,
)


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
        return False
    return True


def _seg(s: str) -> str:
    """URL-encode a path segment to prevent path traversal.

    Encodes special characters including '/' which prevents path traversal
    attacks (e.g., '../admin' becomes '..%2Fadmin'). The encoded slash
    is treated as part of the segment, not a path separator.

    Also rejects '.' and '..' which are special path segments that could
    cause path normalization to collapse into unintended endpoints.

    Raises:
        ValueError: If segment is '.' or '..' (dot-segment traversal)
    """
    if s in (".", ".."):
        raise ValueError(f"Invalid path segment: '{s}' (dot-segment traversal)")
    return quote(s, safe="")


def _normalize_base_url(url: str) -> str:
    """Normalize a base URL for API requests.

    Handles various URL formats:
    - Strips leading/trailing whitespace
    - Strips trailing slashes and /api/v1 if already present
    - Returns a clean base URL ending with /api/v1/
    """
    url = url.strip().rstrip("/")
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
                    "API tokens would be sent unencrypted, risking credential "
                    "exposure. Use HTTPS, or set TEAX_ALLOW_INSECURE_HTTP=1."
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

    def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        labels: list[str] | None = None,
        milestone: str | None = None,
        assignee: str | None = None,
        max_pages: int = 100,
    ) -> list[Issue]:
        """List issues in a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            state: Filter by state: 'open', 'closed', or 'all' (default: 'open')
            labels: Filter by labels (comma-separated in API, list here)
            milestone: Filter by milestone name
            assignee: Filter by assignee username
            max_pages: Maximum pages to fetch (default 100, prevents DoS)

        Returns:
            List of issues
        """
        issues: list[Issue] = []
        page = 1
        limit = 50
        truncated = False

        while page <= max_pages:
            params: dict[str, Any] = {"page": page, "limit": limit, "state": state}
            if labels:
                params["labels"] = ",".join(labels)
            if milestone:
                params["milestone"] = milestone
            if assignee:
                params["assignee"] = assignee

            response = self._client.get(
                f"repos/{_seg(owner)}/{_seg(repo)}/issues",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            issues.extend(Issue.model_validate(item) for item in data)

            if len(data) < limit:
                break
            page += 1
        else:
            truncated = True

        if truncated:
            warnings.warn(
                f"Issues list truncated at {max_pages} pages "
                f"({len(issues)} items). Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )

        return issues

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

    def ensure_label(
        self,
        owner: str,
        repo: str,
        name: str,
        color: str = "1d76db",
        description: str = "",
    ) -> tuple[Label, bool]:
        """Ensure a label exists (idempotent create).

        Creates the label if it doesn't exist, returns existing label if it does.
        Handles race conditions (409 Conflict) gracefully.

        Args:
            owner: Repository owner
            repo: Repository name
            name: Label name
            color: Hex color code without # (default: blue)
            description: Label description (optional)

        Returns:
            Tuple of (Label, was_created) where was_created is True if label
            was created, False if it already existed
        """
        cache_key = f"{owner}/{repo}"

        # Check cache first
        if cache_key in self._label_cache:
            if name in self._label_cache[cache_key]:
                # Label exists in cache - fetch full details
                labels = self.list_repo_labels(owner, repo)
                for label in labels:
                    if label.name == name:
                        return (label, False)

        # Try to create - may fail with 409 if already exists
        try:
            label = self.create_label(owner, repo, name, color, description)
            return (label, True)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                # Label already exists (race condition or not in cache)
                # Refresh cache and return existing label
                labels = self.list_repo_labels(owner, repo)
                for label in labels:
                    if label.name == name:
                        return (label, False)
                # Should not happen - 409 means it exists
                raise ValueError(f"Label '{name}' conflict but not found") from None
            raise

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
        self._milestone_cache[cache_key] = {ms.title: ms.id for ms in all_milestones}
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

    # --- Actions/Runner Operations ---

    def _actions_base_path(
        self,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        global_scope: bool = False,
    ) -> str:
        """Build base path for Actions API endpoints.

        Args:
            owner: Repository owner (required with repo)
            repo: Repository name (required with owner)
            org: Organisation name (for org-level scope)
            global_scope: If True, use admin/global scope

        Returns:
            Base path like 'repos/{o}/{r}/actions', 'orgs/{o}/actions',
            or 'admin/actions'

        Raises:
            ValueError: If scope is ambiguous or missing
        """
        scope_count = sum(
            [
                bool(owner and repo),
                bool(org),
                global_scope,
            ]
        )

        if scope_count == 0:
            raise ValueError("Must specify --repo, --org, or --global scope")
        if scope_count > 1:
            raise ValueError("Specify only one of --repo, --org, or --global")

        if global_scope:
            return "admin/actions"
        elif org:
            return f"orgs/{_seg(org)}/actions"
        else:
            assert owner and repo  # Type guard
            return f"repos/{_seg(owner)}/{_seg(repo)}/actions"

    def list_runners(
        self,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        global_scope: bool = False,
        *,
        max_pages: int = 100,
    ) -> list[Runner]:
        """List runners for a repository, organisation, or globally.

        Args:
            owner: Repository owner (required with repo)
            repo: Repository name (required with owner)
            org: Organisation name (for org-level scope)
            global_scope: If True, list global runners (admin only)
            max_pages: Maximum pages to fetch (default 100, prevents DoS)

        Returns:
            List of runners
        """
        base = self._actions_base_path(owner, repo, org, global_scope)
        runners: list[Runner] = []
        page = 1
        limit = 50
        truncated = False

        while page <= max_pages:
            response = self._client.get(
                f"{base}/runners",
                params={"page": page, "limit": limit},
            )
            response.raise_for_status()
            data = response.json()

            # Handle Gitea's response format (may be {"runners": [...]} or [...])
            if isinstance(data, dict):
                items = data.get("runners", [])
            elif isinstance(data, list):
                items = data
            else:
                raise TypeError(f"Unexpected runners response type: {type(data)!r}")
            if not items:
                break

            for item in items:
                # Normalize labels field (may be list of strings or list of dicts)
                if "labels" in item and item["labels"]:
                    if isinstance(item["labels"][0], dict):
                        item["labels"] = [lb.get("name", "") for lb in item["labels"]]
                runners.append(Runner.model_validate(item))

            if len(items) < limit:
                break
            page += 1
        else:
            truncated = True

        if truncated:
            warnings.warn(
                f"Runners list truncated at {max_pages} pages "
                f"({len(runners)} items). Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )

        return runners

    def get_runner(
        self,
        runner_id: int,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        global_scope: bool = False,
    ) -> Runner:
        """Get a runner by ID.

        Args:
            runner_id: The runner ID
            owner: Repository owner (required with repo)
            repo: Repository name (required with owner)
            org: Organisation name (for org-level scope)
            global_scope: If True, use global scope (admin only)

        Returns:
            Runner details
        """
        base = self._actions_base_path(owner, repo, org, global_scope)
        response = self._client.get(f"{base}/runners/{runner_id}")
        response.raise_for_status()
        data = response.json()

        # Normalize labels field
        if "labels" in data and data["labels"]:
            if isinstance(data["labels"][0], dict):
                data["labels"] = [lb.get("name", "") for lb in data["labels"]]

        return Runner.model_validate(data)

    def delete_runner(
        self,
        runner_id: int,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        global_scope: bool = False,
    ) -> None:
        """Delete a runner by ID.

        Args:
            runner_id: The runner ID
            owner: Repository owner (required with repo)
            repo: Repository name (required with owner)
            org: Organisation name (for org-level scope)
            global_scope: If True, use global scope (admin only)
        """
        base = self._actions_base_path(owner, repo, org, global_scope)
        response = self._client.delete(f"{base}/runners/{runner_id}")
        response.raise_for_status()

    def get_runner_registration_token(
        self,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        global_scope: bool = False,
    ) -> RegistrationToken:
        """Get or create a runner registration token.

        Args:
            owner: Repository owner (required with repo)
            repo: Repository name (required with owner)
            org: Organisation name (for org-level scope)
            global_scope: If True, use global scope (admin only)

        Returns:
            Registration token
        """
        base = self._actions_base_path(owner, repo, org, global_scope)
        response = self._client.get(f"{base}/runners/registration-token")
        response.raise_for_status()
        return RegistrationToken.model_validate(response.json())

    # --- Package Operations ---

    def _packages_base_url(self, owner: str) -> str:
        """Build base URL for package API.

        Package API uses /api/packages/{owner}/, not /api/v1/packages/{owner}/.
        We need to use the server base URL directly (stripping /api/v1 if present).

        Args:
            owner: Package owner (user or organisation)

        Returns:
            Base URL like 'https://gitea.example.com/api/packages/{owner}'
        """
        # Use _normalize_base_url to handle various URL formats, then strip /api/v1/
        api_base = _normalize_base_url(self._login.url)  # ends with /api/v1/
        server_url = api_base.removesuffix("/api/v1/").rstrip("/")
        return f"{server_url}/api/packages/{_seg(owner)}"

    def list_packages(
        self,
        owner: str,
        pkg_type: str | None = None,
        *,
        max_pages: int = 100,
    ) -> list[Package]:
        """List packages for an owner.

        Args:
            owner: Package owner (user or organisation)
            pkg_type: Filter by package type (pypi, container, generic, etc.)
            max_pages: Maximum pages to fetch (default 100, prevents DoS)

        Returns:
            List of packages
        """
        base_url = self._packages_base_url(owner)
        packages: list[Package] = []
        page = 1
        limit = 50
        truncated = False

        while page <= max_pages:
            params: dict[str, Any] = {"page": page, "limit": limit}
            if pkg_type:
                params["type"] = pkg_type

            response = self._client.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            packages.extend(Package.model_validate(pkg) for pkg in data)

            if len(data) < limit:
                break
            page += 1
        else:
            truncated = True

        if truncated:
            warnings.warn(
                f"Packages list truncated at {max_pages} pages "
                f"({len(packages)} items). Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )

        return packages

    def get_package(
        self,
        owner: str,
        pkg_type: str,
        name: str,
    ) -> Package:
        """Get a package by type and name.

        Args:
            owner: Package owner (user or organisation)
            pkg_type: Package type (pypi, container, generic, etc.)
            name: Package name

        Returns:
            Package details (returns first version found)
        """
        versions = self.list_package_versions(owner, pkg_type, name)
        if not versions:
            raise ValueError(f"Package '{name}' not found")

        # Build a Package from the version info - we need to fetch owner details
        # The package list endpoint returns full Package objects, but get by name
        # returns versions. We'll construct a minimal Package.
        first_version = versions[0]
        return Package(
            id=first_version.id,
            owner=User(id=0, login=owner, full_name=""),
            name=name,
            type=pkg_type,
            version=first_version.version,
            created_at=first_version.created_at,
            html_url=first_version.html_url,
        )

    def list_package_versions(
        self,
        owner: str,
        pkg_type: str,
        name: str,
        *,
        max_pages: int = 100,
    ) -> list[PackageVersion]:
        """List versions of a package.

        Args:
            owner: Package owner (user or organisation)
            pkg_type: Package type (pypi, container, generic, etc.)
            name: Package name
            max_pages: Maximum pages to fetch (default 100, prevents DoS)

        Returns:
            List of package versions, sorted by created_at descending
        """
        base_url = self._packages_base_url(owner)
        url = f"{base_url}/{_seg(pkg_type)}/{_seg(name)}"
        versions: list[PackageVersion] = []
        page = 1
        limit = 50
        truncated = False

        while page <= max_pages:
            response = self._client.get(url, params={"page": page, "limit": limit})
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            versions.extend(PackageVersion.model_validate(v) for v in data)

            if len(data) < limit:
                break
            page += 1
        else:
            truncated = True

        if truncated:
            warnings.warn(
                f"Package versions list truncated at {max_pages} pages "
                f"({len(versions)} items). Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )

        # Sort by created_at descending (ISO-8601 strings sort lexicographically)
        versions.sort(key=lambda v: v.created_at or "", reverse=True)
        return versions

    def delete_package_version(
        self,
        owner: str,
        pkg_type: str,
        name: str,
        version: str,
    ) -> None:
        """Delete a specific package version.

        Args:
            owner: Package owner (user or organisation)
            pkg_type: Package type (pypi, container, generic, etc.)
            name: Package name
            version: Version to delete

        Raises:
            ValueError: If pkg_type is 'pypi' (PyPI deletion not supported via API)
        """
        if pkg_type.lower() == "pypi":
            raise ValueError(
                "PyPI packages cannot be deleted via API (Gitea limitation). "
                "Use the Gitea web UI: Settings → Packages → Delete. "
                "See: https://github.com/go-gitea/gitea/issues/22303"
            )

        base_url = self._packages_base_url(owner)
        url = f"{base_url}/{_seg(pkg_type)}/{_seg(name)}/{_seg(version)}"
        response = self._client.delete(url)
        response.raise_for_status()

    # --- Secrets Operations ---

    def _secrets_base_path(
        self,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        user_scope: bool = False,
    ) -> str:
        """Build base path for secrets API.

        Args:
            owner: Repository owner (required with repo)
            repo: Repository name
            org: Organisation name
            user_scope: If True, use user-level scope

        Returns:
            Base path for secrets endpoints
        """
        if user_scope:
            return "user/actions/secrets"
        elif org:
            return f"orgs/{_seg(org)}/actions/secrets"
        elif owner and repo:
            return f"repos/{_seg(owner)}/{_seg(repo)}/actions/secrets"
        else:
            raise ValueError("Must specify repo (owner+repo), org, or user_scope")

    def list_secrets(
        self,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        user_scope: bool = False,
    ) -> list[Secret]:
        """List secrets (names only - values are never returned).

        Args:
            owner: Repository owner (required with repo)
            repo: Repository name
            org: Organisation name
            user_scope: If True, list user-level secrets

        Returns:
            List of secrets (metadata only, no values)
        """
        base = self._secrets_base_path(owner, repo, org, user_scope)
        response = self._client.get(base)
        response.raise_for_status()
        data = response.json()
        return [Secret.model_validate(s) for s in data]

    def set_secret(
        self,
        name: str,
        value: str,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        user_scope: bool = False,
    ) -> bool:
        """Create or update a secret.

        Args:
            name: Secret name (uppercase alphanumeric and underscores only)
            value: Secret value (will be encrypted at rest)
            owner: Repository owner (required with repo)
            repo: Repository name
            org: Organisation name
            user_scope: If True, set user-level secret

        Returns:
            True if created, False if updated
        """
        base = self._secrets_base_path(owner, repo, org, user_scope)
        response = self._client.put(
            f"{base}/{_seg(name)}",
            json={"data": value},
        )
        response.raise_for_status()
        return response.status_code == 201

    def delete_secret(
        self,
        name: str,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        user_scope: bool = False,
    ) -> None:
        """Delete a secret.

        Args:
            name: Secret name
            owner: Repository owner (required with repo)
            repo: Repository name
            org: Organisation name
            user_scope: If True, delete user-level secret
        """
        base = self._secrets_base_path(owner, repo, org, user_scope)
        response = self._client.delete(f"{base}/{_seg(name)}")
        response.raise_for_status()

    # --- Variables Operations ---

    def _variables_base_path(
        self,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        user_scope: bool = False,
    ) -> str:
        """Build base path for variables API.

        Args:
            owner: Repository owner (required with repo)
            repo: Repository name
            org: Organisation name
            user_scope: If True, use user-level scope

        Returns:
            Base path for variables endpoints
        """
        if user_scope:
            return "user/actions/variables"
        elif org:
            return f"orgs/{_seg(org)}/actions/variables"
        elif owner and repo:
            return f"repos/{_seg(owner)}/{_seg(repo)}/actions/variables"
        else:
            raise ValueError("Must specify repo (owner+repo), org, or user_scope")

    def list_variables(
        self,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        user_scope: bool = False,
    ) -> list[Variable]:
        """List variables.

        Args:
            owner: Repository owner (required with repo)
            repo: Repository name
            org: Organisation name
            user_scope: If True, list user-level variables

        Returns:
            List of variables with values
        """
        base = self._variables_base_path(owner, repo, org, user_scope)
        response = self._client.get(base)
        response.raise_for_status()
        data = response.json()
        return [Variable.model_validate(v) for v in data]

    def get_variable(
        self,
        name: str,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        user_scope: bool = False,
    ) -> Variable:
        """Get a single variable.

        Args:
            name: Variable name
            owner: Repository owner (required with repo)
            repo: Repository name
            org: Organisation name
            user_scope: If True, get user-level variable

        Returns:
            Variable with value
        """
        base = self._variables_base_path(owner, repo, org, user_scope)
        response = self._client.get(f"{base}/{_seg(name)}")
        response.raise_for_status()
        return Variable.model_validate(response.json())

    def set_variable(
        self,
        name: str,
        value: str,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        user_scope: bool = False,
    ) -> bool:
        """Create or update a variable.

        Args:
            name: Variable name
            value: Variable value
            owner: Repository owner (required with repo)
            repo: Repository name
            org: Organisation name
            user_scope: If True, set user-level variable

        Returns:
            True if created, False if updated
        """
        base = self._variables_base_path(owner, repo, org, user_scope)
        url = f"{base}/{_seg(name)}"

        # Try to create first (POST), fall back to update (PUT)
        response = self._client.post(url, json={"value": value})
        if response.status_code == 201:
            return True
        elif response.status_code == 409:  # Already exists
            response = self._client.put(url, json={"value": value})
            response.raise_for_status()
            return False
        else:
            response.raise_for_status()
            return True  # Shouldn't reach here

    def delete_variable(
        self,
        name: str,
        owner: str | None = None,
        repo: str | None = None,
        org: str | None = None,
        user_scope: bool = False,
    ) -> None:
        """Delete a variable.

        Args:
            name: Variable name
            owner: Repository owner (required with repo)
            repo: Repository name
            org: Organisation name
            user_scope: If True, delete user-level variable
        """
        base = self._variables_base_path(owner, repo, org, user_scope)
        response = self._client.delete(f"{base}/{_seg(name)}")
        response.raise_for_status()

    # --- Workflow Operations ---

    def list_workflows(
        self,
        owner: str,
        repo: str,
        *,
        max_pages: int = 100,
    ) -> list[Workflow]:
        """List workflows for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            max_pages: Maximum pages to fetch (default 100, prevents DoS)

        Returns:
            List of workflows
        """
        workflows: list[Workflow] = []
        page = 1
        limit = 50
        truncated = False

        while page <= max_pages:
            response = self._client.get(
                f"repos/{_seg(owner)}/{_seg(repo)}/actions/workflows",
                params={"page": page, "limit": limit},
            )
            response.raise_for_status()
            data = response.json()

            # Handle Gitea's response format (may be {"workflows": [...]} or [...])
            if isinstance(data, dict):
                if "workflows" not in data:
                    raise TypeError(
                        "Unexpected workflows response: dict missing 'workflows' key"
                    )
                items = data["workflows"]
                if not isinstance(items, list):
                    raise TypeError(
                        f"Unexpected 'workflows' value type: {type(items)!r}"
                    )
            elif isinstance(data, list):
                items = data
            else:
                raise TypeError(f"Unexpected workflows response type: {type(data)!r}")
            if not items:
                break

            workflows.extend(Workflow.model_validate(w) for w in items)

            if len(items) < limit:
                break
            page += 1
        else:
            truncated = True

        if truncated:
            warnings.warn(
                f"Workflows list truncated at {max_pages} pages "
                f"({len(workflows)} items). Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )

        return workflows

    def get_workflow(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
    ) -> Workflow:
        """Get a workflow by ID or filename.

        Args:
            owner: Repository owner
            repo: Repository name
            workflow_id: Workflow ID or filename (e.g., "ci.yml")

        Returns:
            Workflow details
        """
        response = self._client.get(
            f"repos/{_seg(owner)}/{_seg(repo)}/actions/workflows/{_seg(workflow_id)}"
        )
        response.raise_for_status()
        return Workflow.model_validate(response.json())

    def dispatch_workflow(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
        ref: str,
        inputs: dict[str, str] | None = None,
    ) -> None:
        """Dispatch a workflow run.

        Args:
            owner: Repository owner
            repo: Repository name
            workflow_id: Workflow ID or filename (e.g., "ci.yml")
            ref: Git reference (branch, tag, or commit SHA)
            inputs: Workflow input parameters (optional)
        """
        payload: dict[str, Any] = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs

        response = self._client.post(
            f"repos/{_seg(owner)}/{_seg(repo)}/actions/workflows/"
            f"{_seg(workflow_id)}/dispatches",
            json=payload,
        )
        response.raise_for_status()

    def enable_workflow(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
    ) -> None:
        """Enable a workflow.

        Args:
            owner: Repository owner
            repo: Repository name
            workflow_id: Workflow ID or filename (e.g., "ci.yml")
        """
        response = self._client.put(
            f"repos/{_seg(owner)}/{_seg(repo)}/actions/workflows/"
            f"{_seg(workflow_id)}/enable"
        )
        response.raise_for_status()

    def disable_workflow(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
    ) -> None:
        """Disable a workflow.

        Args:
            owner: Repository owner
            repo: Repository name
            workflow_id: Workflow ID or filename (e.g., "ci.yml")
        """
        response = self._client.put(
            f"repos/{_seg(owner)}/{_seg(repo)}/actions/workflows/"
            f"{_seg(workflow_id)}/disable"
        )
        response.raise_for_status()

    # --- Workflow Run Operations ---

    def list_runs(
        self,
        owner: str,
        repo: str,
        *,
        workflow: str | None = None,
        branch: str | None = None,
        status: str | None = None,
        head_sha: str | None = None,
        limit: int = 20,
        max_pages: int = 10,
    ) -> list[WorkflowRun]:
        """List workflow runs for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            workflow: Filter by workflow filename (e.g., "ci.yml")
            branch: Filter by branch name
            status: Filter by status (queued, in_progress, completed, waiting)
            head_sha: Filter by commit SHA (prefix match, client-side)
            limit: Results per page (default 20)
            max_pages: Maximum pages to fetch (default 10, prevents DoS)

        Returns:
            List of workflow runs
        """
        runs: list[WorkflowRun] = []
        page = 1
        truncated = False

        while page <= max_pages:
            params: dict[str, Any] = {"page": page, "limit": limit}
            if branch:
                params["branch"] = branch
            if status:
                params["status"] = status

            # Gitea uses /actions/runs for all runs, filter by workflow client-side
            response = self._client.get(
                f"repos/{_seg(owner)}/{_seg(repo)}/actions/runs",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            # Handle Gitea's response format (may be {"workflow_runs": [...]} or [...])
            if isinstance(data, dict):
                items = data.get("workflow_runs", [])
                if not isinstance(items, list):
                    raise TypeError(
                        f"Unexpected 'workflow_runs' value type: {type(items)!r}"
                    )
            elif isinstance(data, list):
                items = data
            else:
                raise TypeError(f"Unexpected runs response type: {type(data)!r}")

            if not items:
                break

            for item in items:
                run = WorkflowRun.model_validate(item)
                # Client-side workflow filter (Gitea API doesn't support it)
                # Strip @refs/... suffix before matching (Gitea may include it)
                if workflow:
                    path_for_match = run.path.split("@")[0] if "@" in run.path else run.path  # noqa: E501
                    if not path_for_match.endswith(workflow):
                        continue
                # Client-side SHA filter (prefix match)
                if head_sha and not run.head_sha.startswith(head_sha):
                    continue
                runs.append(run)

            if len(items) < limit:
                break
            page += 1
        else:
            truncated = True

        if truncated:
            warnings.warn(
                f"Runs list truncated at {max_pages} pages "
                f"({len(runs)} items). Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )

        return runs

    def get_run(
        self,
        owner: str,
        repo: str,
        run_id: int,
    ) -> WorkflowRun:
        """Get a workflow run by ID.

        Note: Gitea may not have a direct endpoint for single run.
        This fetches from the runs list and filters.

        Args:
            owner: Repository owner
            repo: Repository name
            run_id: Workflow run ID

        Returns:
            Workflow run details

        Raises:
            httpx.HTTPStatusError: If run not found
        """
        # Try to get run from jobs endpoint which includes run info
        response = self._client.get(
            f"repos/{_seg(owner)}/{_seg(repo)}/actions/runs/{run_id}/jobs",
        )
        response.raise_for_status()
        data = response.json()

        # Get jobs to find the run info
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        if jobs and isinstance(jobs, list) and len(jobs) > 0:
            # Jobs exist, so run exists - fetch from runs list
            runs = self.list_runs(owner, repo, limit=100, max_pages=5)
            for run in runs:
                if run.id == run_id:
                    return run

        # Fallback: search in recent runs
        runs = self.list_runs(owner, repo, limit=100, max_pages=10)
        for run in runs:
            if run.id == run_id:
                return run

        # Not found - raise 404-like error
        raise httpx.HTTPStatusError(
            f"Run {run_id} not found",
            request=httpx.Request("GET", f"runs/{run_id}"),
            response=httpx.Response(404),
        )

    def delete_run(
        self,
        owner: str,
        repo: str,
        run_id: int,
    ) -> None:
        """Delete a workflow run.

        Args:
            owner: Repository owner
            repo: Repository name
            run_id: Workflow run ID
        """
        response = self._client.delete(
            f"repos/{_seg(owner)}/{_seg(repo)}/actions/runs/{run_id}"
        )
        response.raise_for_status()

    def list_run_jobs(
        self,
        owner: str,
        repo: str,
        run_id: int,
    ) -> list[WorkflowJob]:
        """List jobs for a workflow run.

        Args:
            owner: Repository owner
            repo: Repository name
            run_id: Workflow run ID

        Returns:
            List of jobs with their steps
        """
        response = self._client.get(
            f"repos/{_seg(owner)}/{_seg(repo)}/actions/runs/{run_id}/jobs"
        )
        response.raise_for_status()
        data = response.json()

        # Handle Gitea's response format
        if isinstance(data, dict):
            items = data.get("jobs", [])
        elif isinstance(data, list):
            items = data
        else:
            raise TypeError(f"Unexpected jobs response type: {type(data)!r}")

        return [WorkflowJob.model_validate(j) for j in items]

    def get_job(
        self,
        owner: str,
        repo: str,
        job_id: int,
    ) -> WorkflowJob:
        """Get a job by ID.

        Args:
            owner: Repository owner
            repo: Repository name
            job_id: Job ID

        Returns:
            Job details with steps
        """
        response = self._client.get(
            f"repos/{_seg(owner)}/{_seg(repo)}/actions/jobs/{job_id}"
        )
        response.raise_for_status()
        return WorkflowJob.model_validate(response.json())

    def get_job_logs(
        self,
        owner: str,
        repo: str,
        job_id: int,
    ) -> str:
        """Get logs for a job.

        Args:
            owner: Repository owner
            repo: Repository name
            job_id: Job ID

        Returns:
            Job logs as plain text
        """
        response = self._client.get(
            f"repos/{_seg(owner)}/{_seg(repo)}/actions/jobs/{job_id}/logs"
        )
        response.raise_for_status()
        return response.text

    def rerun_workflow(
        self,
        owner: str,
        repo: str,
        run_id: int,
    ) -> None:
        """Rerun a workflow via dispatch.

        Since Gitea doesn't have a native rerun API yet (PR #35382 pending),
        this uses workflow dispatch as a workaround.

        Limitations:
        - Only works for workflows with workflow_dispatch trigger
        - Original inputs not preserved
        - Original event context (PR number, etc.) lost

        Args:
            owner: Repository owner
            repo: Repository name
            run_id: Workflow run ID to rerun
        """
        # Get the run to extract workflow and ref
        run = self.get_run(owner, repo, run_id)

        # Extract workflow filename from path
        # e.g., ".github/workflows/ci.yml" -> "ci.yml"
        workflow_id = run.path.split("/")[-1]

        # Dispatch on the same branch
        self.dispatch_workflow(owner, repo, workflow_id, run.head_branch)

    # --- Package Linking Operations ---

    def link_package(
        self,
        owner: str,
        pkg_type: str,
        name: str,
        repo_name: str,
    ) -> None:
        """Link a package to a repository.

        Args:
            owner: Package owner
            pkg_type: Package type (container, pypi, etc.)
            name: Package name
            repo_name: Repository name to link to
        """
        response = self._client.post(
            f"{self._packages_base_url(owner)}/{_seg(pkg_type)}/"
            f"{_seg(name)}/-/link/{_seg(repo_name)}"
        )
        response.raise_for_status()

    def unlink_package(
        self,
        owner: str,
        pkg_type: str,
        name: str,
    ) -> None:
        """Unlink a package from its repository.

        Args:
            owner: Package owner
            pkg_type: Package type (container, pypi, etc.)
            name: Package name
        """
        response = self._client.post(
            f"{self._packages_base_url(owner)}/{_seg(pkg_type)}/{_seg(name)}/-/unlink"
        )
        response.raise_for_status()

    def get_latest_package_version(
        self,
        owner: str,
        pkg_type: str,
        name: str,
    ) -> Package:
        """Get the latest version of a package.

        Args:
            owner: Package owner
            pkg_type: Package type (container, pypi, etc.)
            name: Package name

        Returns:
            Latest package version
        """
        response = self._client.get(
            f"{self._packages_base_url(owner)}/{_seg(pkg_type)}/{_seg(name)}/-/latest"
        )
        response.raise_for_status()
        return Package.model_validate(response.json())
