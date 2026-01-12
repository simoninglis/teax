"""Gitea API client for teax operations."""

import os
from typing import Any

import httpx

from teax.config import get_default_login, get_login_by_name
from teax.models import Dependency, Issue, Label, TeaLogin


def _get_ssl_verify() -> bool:
    """Check if SSL verification should be enabled.

    Set TEAX_INSECURE=1 to disable SSL verification for self-hosted CA instances.
    """
    return os.environ.get("TEAX_INSECURE", "").lower() not in ("1", "true", "yes")


class GiteaClient:
    """HTTP client for Gitea API operations not covered by tea CLI."""

    def __init__(self, login: TeaLogin | None = None, login_name: str | None = None):
        """Initialize the Gitea client.

        Args:
            login: Optional pre-loaded login config
            login_name: Optional login name to use (looks up from tea config)
        """
        if login is not None:
            self._login = login
        elif login_name is not None:
            self._login = get_login_by_name(login_name)
        else:
            self._login = get_default_login()

        # Ensure base URL ends with / and includes /api/v1/ for correct path joining
        # This handles subpath installations like https://example.com/gitea/
        base = self._login.url.rstrip("/") + "/api/v1/"
        self._client = httpx.Client(
            base_url=base,
            headers={
                "Authorization": f"token {self._login.token.get_secret_value()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
            verify=_get_ssl_verify(),
        )
        # Cache for label name -> ID mapping per repo (cleared on close)
        self._label_cache: dict[str, dict[str, int]] = {}

    def close(self) -> None:
        """Close the HTTP client and clear caches."""
        self._client.close()
        self._label_cache.clear()

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
            f"repos/{owner}/{repo}/issues",
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
        response = self._client.get(f"repos/{owner}/{repo}/issues/{index}")
        response.raise_for_status()
        return Issue.model_validate(response.json())

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
            f"repos/{owner}/{repo}/issues/{index}",
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
            f"repos/{owner}/{repo}/issues/{index}/labels"
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
            f"repos/{owner}/{repo}/issues/{index}/labels",
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
            f"repos/{owner}/{repo}/issues/{index}/labels/{label_ids[0]}"
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
            f"repos/{owner}/{repo}/issues/{index}/labels",
            json={"labels": label_ids},
        )
        response.raise_for_status()
        return [Label.model_validate(item) for item in response.json()]

    def _resolve_label_ids(
        self, owner: str, repo: str, label_names: list[str]
    ) -> list[int]:
        """Resolve label names to IDs.

        Uses per-repo caching to avoid redundant API calls within a session.

        Args:
            owner: Repository owner
            repo: Repository name
            label_names: Label names to resolve

        Returns:
            List of label IDs
        """
        cache_key = f"{owner}/{repo}"
        if cache_key not in self._label_cache:
            # Fetch all labels with pagination
            all_labels: dict[str, int] = {}
            page = 1
            while True:
                response = self._client.get(
                    f"repos/{owner}/{repo}/labels",
                    params={"page": page, "limit": 50},
                )
                response.raise_for_status()
                items = response.json()
                if not items:
                    break
                for item in items:
                    all_labels[item["name"]] = item["id"]
                page += 1
            self._label_cache[cache_key] = all_labels

        all_labels = self._label_cache[cache_key]
        ids = []
        for name in label_names:
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
            f"repos/{owner}/{repo}/issues/{index}/dependencies"
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
            f"repos/{owner}/{repo}/issues/{index}/blocks"
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
            f"repos/{owner}/{repo}/issues/{index}/dependencies",
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
            f"repos/{owner}/{repo}/issues/{index}/dependencies",
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
            f"repos/{owner}/{repo}/labels",
            json={"name": name, "color": color, "description": description},
        )
        response.raise_for_status()
        # Invalidate label cache for this repo
        cache_key = f"{owner}/{repo}"
        self._label_cache.pop(cache_key, None)
        return Label.model_validate(response.json())

    def list_repo_labels(self, owner: str, repo: str) -> list[Label]:
        """List all labels in a repository.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            List of labels
        """
        all_labels: list[Label] = []
        page = 1
        while True:
            response = self._client.get(
                f"repos/{owner}/{repo}/labels",
                params={"page": page, "limit": 50},
            )
            response.raise_for_status()
            items = response.json()
            if not items:
                break
            all_labels.extend(Label.model_validate(item) for item in items)
            page += 1
        return all_labels
