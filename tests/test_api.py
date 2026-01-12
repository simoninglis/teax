"""Tests for Gitea API client."""

import os

import httpx
import pytest
import respx

from teax.api import GiteaClient, _get_ssl_verify
from teax.models import TeaLogin


@pytest.fixture
def mock_login() -> TeaLogin:
    """Create a mock tea login for testing."""
    return TeaLogin(
        name="test.example.com",
        url="https://test.example.com",
        token="test-token-123",
        default=True,
        user="testuser",
    )


@pytest.fixture
def client(mock_login: TeaLogin) -> GiteaClient:
    """Create a GiteaClient with mock login."""
    return GiteaClient(login=mock_login)


# --- SSL Verification Tests ---


def test_ssl_verify_default():
    """Test SSL verification enabled by default."""
    env_backup = os.environ.get("TEAX_INSECURE")
    try:
        os.environ.pop("TEAX_INSECURE", None)
        assert _get_ssl_verify() is True
    finally:
        if env_backup is not None:
            os.environ["TEAX_INSECURE"] = env_backup


def test_ssl_verify_disabled():
    """Test SSL verification disabled with TEAX_INSECURE=1."""
    env_backup = os.environ.get("TEAX_INSECURE")
    try:
        os.environ["TEAX_INSECURE"] = "1"
        assert _get_ssl_verify() is False
    finally:
        if env_backup is not None:
            os.environ["TEAX_INSECURE"] = env_backup
        else:
            os.environ.pop("TEAX_INSECURE", None)


# --- Client Initialization Tests ---


def test_client_context_manager(mock_login: TeaLogin):
    """Test client works as context manager."""
    with GiteaClient(login=mock_login) as client:
        assert client.base_url == "https://test.example.com"


def test_client_base_url(client: GiteaClient):
    """Test base URL property."""
    assert client.base_url == "https://test.example.com"


# --- Issue Operations Tests ---


@respx.mock
def test_create_issue(client: GiteaClient):
    """Test creating an issue."""
    route = respx.post("https://test.example.com/api/v1/repos/owner/repo/issues")
    route.mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 200,
                "number": 50,
                "title": "New Issue",
                "state": "open",
                "labels": [],
                "assignees": [],
                "milestone": None,
            },
        )
    )

    issue = client.create_issue("owner", "repo", "New Issue", "Issue body")

    assert issue.number == 50
    assert issue.title == "New Issue"

    # Verify request body
    import json

    request_body = json.loads(route.calls.last.request.content)
    assert request_body["title"] == "New Issue"
    assert request_body["body"] == "Issue body"


@respx.mock
def test_create_issue_with_labels(client: GiteaClient):
    """Test creating an issue with labels."""
    route = respx.post("https://test.example.com/api/v1/repos/owner/repo/issues")
    route.mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 200,
                "number": 50,
                "title": "New Issue",
                "state": "open",
                "labels": [
                    {"id": 1, "name": "bug", "color": "ff0000", "description": ""}
                ],
                "assignees": [],
                "milestone": None,
            },
        )
    )

    issue = client.create_issue("owner", "repo", "New Issue", labels=[1, 2])

    assert issue.number == 50

    # Verify request body includes labels
    import json

    request_body = json.loads(route.calls.last.request.content)
    assert request_body["labels"] == [1, 2]


@respx.mock
def test_get_issue(client: GiteaClient):
    """Test getting an issue."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/25").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 100,
                "number": 25,
                "title": "Test Issue",
                "state": "open",
                "labels": [],
                "assignees": [],
                "milestone": None,
            },
        )
    )

    issue = client.get_issue("owner", "repo", 25)

    assert issue.number == 25
    assert issue.title == "Test Issue"
    assert issue.state == "open"


@respx.mock
def test_edit_issue(client: GiteaClient):
    """Test editing an issue."""
    respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/25").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 100,
                "number": 25,
                "title": "Updated Title",
                "state": "open",
                "labels": [],
                "assignees": [],
                "milestone": None,
            },
        )
    )

    issue = client.edit_issue("owner", "repo", 25, title="Updated Title")

    assert issue.title == "Updated Title"


@respx.mock
def test_edit_issue_with_assignees(client: GiteaClient):
    """Test editing an issue with assignees."""
    respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/25").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 100,
                "number": 25,
                "title": "Test",
                "state": "open",
                "labels": [],
                "assignees": [{"id": 1, "login": "user1", "full_name": "User One"}],
                "milestone": None,
            },
        )
    )

    issue = client.edit_issue("owner", "repo", 25, assignees=["user1"])

    assert len(issue.assignees) == 1
    assert issue.assignees[0].login == "user1"


@respx.mock
def test_edit_issue_clear_milestone(client: GiteaClient):
    """Test clearing milestone with milestone=0."""
    route = respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/25")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 100,
                "number": 25,
                "title": "Test",
                "state": "open",
                "labels": [],
                "assignees": [],
                "milestone": None,
            },
        )
    )

    client.edit_issue("owner", "repo", 25, milestone=0)

    # Verify the request body had milestone: None (JSON without spaces)
    import json

    request_body = json.loads(route.calls.last.request.content)
    assert request_body == {"milestone": None}


# --- Label Operations Tests ---


@respx.mock
def test_get_issue_labels(client: GiteaClient):
    """Test getting labels for an issue."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/25/labels").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "bug",
                    "color": "ff0000",
                    "description": "Bug report",
                },
                {
                    "id": 2,
                    "name": "feature",
                    "color": "00ff00",
                    "description": "Feature request",
                },
            ],
        )
    )

    labels = client.get_issue_labels("owner", "repo", 25)

    assert len(labels) == 2
    assert labels[0].name == "bug"
    assert labels[1].name == "feature"


@respx.mock
def test_add_issue_labels(client: GiteaClient):
    """Test adding labels to an issue."""
    # Mock the label lookup
    respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                {"id": 2, "name": "feature", "color": "00ff00", "description": ""},
            ],
        )
    )
    # Mock the add labels request
    respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
            ],
        )
    )

    labels = client.add_issue_labels("owner", "repo", 25, ["bug"])

    assert len(labels) == 1
    assert labels[0].name == "bug"


@respx.mock
def test_remove_issue_label(client: GiteaClient):
    """Test removing a label from an issue."""
    # Mock the label lookup
    respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
            ],
        )
    )
    # Mock the delete request
    respx.delete(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels/1"
    ).mock(return_value=httpx.Response(204))

    # Should not raise
    client.remove_issue_label("owner", "repo", 25, "bug")


@respx.mock
def test_set_issue_labels(client: GiteaClient):
    """Test replacing all labels on an issue."""
    # Mock the label lookup
    respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                {"id": 2, "name": "feature", "color": "00ff00", "description": ""},
            ],
        )
    )
    # Mock the set labels request
    respx.put("https://test.example.com/api/v1/repos/owner/repo/issues/25/labels").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                {"id": 2, "name": "feature", "color": "00ff00", "description": ""},
            ],
        )
    )

    labels = client.set_issue_labels("owner", "repo", 25, ["bug", "feature"])

    assert len(labels) == 2


@respx.mock
def test_resolve_label_not_found(client: GiteaClient):
    """Test error when label not found."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
        return_value=httpx.Response(200, json=[])
    )

    with pytest.raises(ValueError, match="Label 'nonexistent' not found"):
        client.add_issue_labels("owner", "repo", 25, ["nonexistent"])


# --- Dependency Operations Tests ---


@respx.mock
def test_list_dependencies(client: GiteaClient):
    """Test listing dependencies."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 17,
                    "number": 17,
                    "title": "Dependency Issue",
                    "state": "open",
                    "repository": {
                        "id": 1,
                        "name": "repo",
                        "full_name": "owner/repo",
                        "owner": "owner",
                    },
                },
            ],
        )
    )

    deps = client.list_dependencies("owner", "repo", 25)

    assert len(deps) == 1
    assert deps[0].number == 17
    assert deps[0].title == "Dependency Issue"


@respx.mock
def test_list_blocks(client: GiteaClient):
    """Test listing blocked issues."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/25/blocks").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 30,
                    "number": 30,
                    "title": "Blocked Issue",
                    "state": "open",
                    "repository": {
                        "id": 1,
                        "name": "repo",
                        "full_name": "owner/repo",
                        "owner": "owner",
                    },
                },
            ],
        )
    )

    blocks = client.list_blocks("owner", "repo", 25)

    assert len(blocks) == 1
    assert blocks[0].number == 30


@respx.mock
def test_add_dependency(client: GiteaClient):
    """Test adding a dependency."""
    route = respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies"
    )
    route.mock(return_value=httpx.Response(201))

    client.add_dependency("owner", "repo", 25, "owner", "repo", 17)

    # Verify the request was made
    assert route.called


@respx.mock
def test_remove_dependency(client: GiteaClient):
    """Test removing a dependency."""
    route = respx.delete(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies"
    )
    route.mock(return_value=httpx.Response(200))

    client.remove_dependency("owner", "repo", 25, "owner", "repo", 17)

    # Verify the request was made
    assert route.called


# --- Repository Label Operations Tests ---


@respx.mock
def test_create_label(client: GiteaClient):
    """Test creating a label."""
    route = respx.post("https://test.example.com/api/v1/repos/owner/repo/labels")
    route.mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 10,
                "name": "epic/new-feature",
                "color": "9b59b6",
                "description": "Epic: new-feature",
            },
        )
    )

    label = client.create_label(
        "owner", "repo", "epic/new-feature", "9b59b6", "Epic: new-feature"
    )

    assert label.id == 10
    assert label.name == "epic/new-feature"
    assert label.color == "9b59b6"

    # Verify request body
    import json

    request_body = json.loads(route.calls.last.request.content)
    assert request_body["name"] == "epic/new-feature"
    assert request_body["color"] == "9b59b6"
    assert request_body["description"] == "Epic: new-feature"


@respx.mock
def test_list_repo_labels(client: GiteaClient):
    """Test listing all repository labels."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "bug",
                    "color": "ff0000",
                    "description": "Bug report",
                },
                {
                    "id": 2,
                    "name": "feature",
                    "color": "00ff00",
                    "description": "Feature",
                },
                {
                    "id": 3,
                    "name": "docs",
                    "color": "0000ff",
                    "description": "Documentation",
                },
            ],
        )
    )

    labels = client.list_repo_labels("owner", "repo")

    assert len(labels) == 3
    assert labels[0].name == "bug"
    assert labels[2].name == "docs"


# --- Error Handling Tests ---


@respx.mock
def test_http_error_404(client: GiteaClient):
    """Test 404 error handling."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/999").mock(
        return_value=httpx.Response(404, json={"message": "Issue not found"})
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.get_issue("owner", "repo", 999)

    assert exc_info.value.response.status_code == 404


@respx.mock
def test_http_error_401(client: GiteaClient):
    """Test 401 unauthorized error handling."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/25").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.get_issue("owner", "repo", 25)

    assert exc_info.value.response.status_code == 401


# --- Label Caching Tests ---


@respx.mock
def test_label_cache_avoids_redundant_calls(client: GiteaClient):
    """Test that label resolution uses cache to avoid redundant API calls."""
    label_route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    label_route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                {"id": 2, "name": "feature", "color": "00ff00", "description": ""},
            ],
        )
    )
    # Mock for adding labels
    respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels"
    ).mock(return_value=httpx.Response(200, json=[]))
    respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/issues/26/labels"
    ).mock(return_value=httpx.Response(200, json=[]))

    # Make two label operations on different issues in same repo
    client.add_issue_labels("owner", "repo", 25, ["bug"])
    client.add_issue_labels("owner", "repo", 26, ["feature"])

    # Label lookup should only be called once due to caching
    assert label_route.call_count == 1


@respx.mock
def test_label_cache_per_repo(client: GiteaClient):
    """Test that label cache is per-repo."""
    label_route_1 = respx.get("https://test.example.com/api/v1/repos/owner/repo1/labels")
    label_route_1.mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "name": "bug", "color": "ff0000", "description": ""}],
        )
    )
    label_route_2 = respx.get("https://test.example.com/api/v1/repos/owner/repo2/labels")
    label_route_2.mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 5, "name": "bug", "color": "ff0000", "description": ""}],
        )
    )
    respx.post(
        "https://test.example.com/api/v1/repos/owner/repo1/issues/1/labels"
    ).mock(return_value=httpx.Response(200, json=[]))
    respx.post(
        "https://test.example.com/api/v1/repos/owner/repo2/issues/1/labels"
    ).mock(return_value=httpx.Response(200, json=[]))

    # Operations on different repos should fetch labels separately
    client.add_issue_labels("owner", "repo1", 1, ["bug"])
    client.add_issue_labels("owner", "repo2", 1, ["bug"])

    assert label_route_1.call_count == 1
    assert label_route_2.call_count == 1


@respx.mock
def test_label_cache_cleared_on_close(client: GiteaClient):
    """Test that label cache is cleared when client is closed."""
    label_route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    label_route.mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "name": "bug", "color": "ff0000", "description": ""}],
        )
    )
    respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels"
    ).mock(return_value=httpx.Response(200, json=[]))

    # Populate the cache
    client.add_issue_labels("owner", "repo", 25, ["bug"])
    assert label_route.call_count == 1

    # Close and verify cache is cleared
    client.close()
    assert client._label_cache == {}


@respx.mock
def test_label_cache_invalidated_on_create_label(client: GiteaClient):
    """Test that create_label invalidates the cache for that repo."""
    label_route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    label_route.mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "name": "bug", "color": "ff0000", "description": ""}],
        )
    )
    respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels"
    ).mock(return_value=httpx.Response(200, json=[]))
    respx.post("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
        return_value=httpx.Response(
            201,
            json={"id": 2, "name": "new-label", "color": "0000ff", "description": ""},
        )
    )

    # First operation populates cache
    client.add_issue_labels("owner", "repo", 25, ["bug"])
    assert label_route.call_count == 1
    assert "owner/repo" in client._label_cache

    # Creating a label should invalidate the cache
    client.create_label("owner", "repo", "new-label", "0000ff")
    assert "owner/repo" not in client._label_cache

    # Next operation should fetch labels again
    client.add_issue_labels("owner", "repo", 25, ["bug"])
    assert label_route.call_count == 2
