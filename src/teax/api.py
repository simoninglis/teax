"""Gitea API client for teax operations."""

from typing import Any

import httpx

from teax.config import get_default_login, get_login_by_name
from teax.models import Dependency, Issue, Label, TeaLogin


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

        self._client = httpx.Client(
            base_url=self._login.url.rstrip("/"),
            headers={
                "Authorization": f"token {self._login.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "GiteaClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def base_url(self) -> str:
        """Get the base URL for the Gitea instance."""
        return self._login.url

    # --- Issue Operations ---

    def get_issue(self, owner: str, repo: str, index: int) -> Issue:
        """Get an issue by number.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number

        Returns:
            Issue details
        """
        response = self._client.get(
            f"/api/v1/repos/{owner}/{repo}/issues/{index}"
        )
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
            f"/api/v1/repos/{owner}/{repo}/issues/{index}",
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
            f"/api/v1/repos/{owner}/{repo}/issues/{index}/labels"
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
            f"/api/v1/repos/{owner}/{repo}/issues/{index}/labels",
            json={"labels": label_ids},
        )
        response.raise_for_status()
        return [Label.model_validate(item) for item in response.json()]

    def remove_issue_label(
        self, owner: str, repo: str, index: int, label: str
    ) -> None:
        """Remove a label from an issue.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number
            label: Label name to remove
        """
        # Get label ID
        label_ids = self._resolve_label_ids(owner, repo, [label])
        if not label_ids:
            return

        response = self._client.delete(
            f"/api/v1/repos/{owner}/{repo}/issues/{index}/labels/{label_ids[0]}"
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
            f"/api/v1/repos/{owner}/{repo}/issues/{index}/labels",
            json={"labels": label_ids},
        )
        response.raise_for_status()
        return [Label.model_validate(item) for item in response.json()]

    def _resolve_label_ids(
        self, owner: str, repo: str, label_names: list[str]
    ) -> list[int]:
        """Resolve label names to IDs.

        Args:
            owner: Repository owner
            repo: Repository name
            label_names: Label names to resolve

        Returns:
            List of label IDs
        """
        response = self._client.get(f"/api/v1/repos/{owner}/{repo}/labels")
        response.raise_for_status()
        all_labels = {item["name"]: item["id"] for item in response.json()}

        ids = []
        for name in label_names:
            if name in all_labels:
                ids.append(all_labels[name])
            else:
                raise ValueError(f"Label '{name}' not found in repository")
        return ids

    # --- Dependency Operations ---

    def list_dependencies(
        self, owner: str, repo: str, index: int
    ) -> list[Dependency]:
        """List issues that this issue depends on.

        Args:
            owner: Repository owner
            repo: Repository name
            index: Issue number

        Returns:
            List of dependency issues
        """
        response = self._client.get(
            f"/api/v1/repos/{owner}/{repo}/issues/{index}/dependencies"
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
            f"/api/v1/repos/{owner}/{repo}/issues/{index}/blocks"
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
            f"/api/v1/repos/{owner}/{repo}/issues/{index}/dependencies",
            json={
                "dependentOwner": depends_on_owner,
                "dependentRepo": depends_on_repo,
                "dependentIndex": depends_on_index,
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
            f"/api/v1/repos/{owner}/{repo}/issues/{index}/dependencies",
            json={
                "dependentOwner": depends_on_owner,
                "dependentRepo": depends_on_repo,
                "dependentIndex": depends_on_index,
            },
        )
        response.raise_for_status()

    # --- Repository Label Operations ---

    def list_repo_labels(self, owner: str, repo: str) -> list[Label]:
        """List all labels in a repository.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            List of labels
        """
        response = self._client.get(f"/api/v1/repos/{owner}/{repo}/labels")
        response.raise_for_status()
        return [Label.model_validate(item) for item in response.json()]
