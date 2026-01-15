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


def test_ssl_verify_custom_ca_bundle():
    """Test custom CA bundle path with TEAX_CA_BUNDLE."""
    env_backup_insecure = os.environ.get("TEAX_INSECURE")
    env_backup_ca = os.environ.get("TEAX_CA_BUNDLE")
    try:
        os.environ.pop("TEAX_INSECURE", None)
        os.environ["TEAX_CA_BUNDLE"] = "/path/to/custom/ca.pem"
        assert _get_ssl_verify() == "/path/to/custom/ca.pem"
    finally:
        if env_backup_insecure is not None:
            os.environ["TEAX_INSECURE"] = env_backup_insecure
        else:
            os.environ.pop("TEAX_INSECURE", None)
        if env_backup_ca is not None:
            os.environ["TEAX_CA_BUNDLE"] = env_backup_ca
        else:
            os.environ.pop("TEAX_CA_BUNDLE", None)


def test_ssl_ca_bundle_takes_precedence_over_insecure():
    """Test TEAX_CA_BUNDLE takes precedence over TEAX_INSECURE."""
    env_backup_insecure = os.environ.get("TEAX_INSECURE")
    env_backup_ca = os.environ.get("TEAX_CA_BUNDLE")
    try:
        os.environ["TEAX_INSECURE"] = "1"
        os.environ["TEAX_CA_BUNDLE"] = "/path/to/ca.pem"
        # CA bundle should take precedence
        assert _get_ssl_verify() == "/path/to/ca.pem"
    finally:
        if env_backup_insecure is not None:
            os.environ["TEAX_INSECURE"] = env_backup_insecure
        else:
            os.environ.pop("TEAX_INSECURE", None)
        if env_backup_ca is not None:
            os.environ["TEAX_CA_BUNDLE"] = env_backup_ca
        else:
            os.environ.pop("TEAX_CA_BUNDLE", None)


def test_http_url_blocked_by_default():
    """Test plain HTTP URLs are blocked by default."""
    env_backup = os.environ.get("TEAX_ALLOW_INSECURE_HTTP")
    try:
        os.environ.pop("TEAX_ALLOW_INSECURE_HTTP", None)
        http_login = TeaLogin(
            name="insecure",
            url="http://insecure.example.com",
            token="test-token",
            default=True,
            user="testuser",
        )
        with pytest.raises(ValueError, match="Refusing to connect.*over plain HTTP"):
            GiteaClient(login=http_login)
    finally:
        if env_backup is not None:
            os.environ["TEAX_ALLOW_INSECURE_HTTP"] = env_backup


def test_http_url_allowed_with_env_var():
    """Test plain HTTP URLs allowed when TEAX_ALLOW_INSECURE_HTTP is set."""
    env_backup = os.environ.get("TEAX_ALLOW_INSECURE_HTTP")
    try:
        os.environ["TEAX_ALLOW_INSECURE_HTTP"] = "1"
        http_login = TeaLogin(
            name="insecure",
            url="http://insecure.example.com",
            token="test-token",
            default=True,
            user="testuser",
        )
        # Should emit warning but not raise
        with pytest.warns(UserWarning, match="insecure HTTP connection"):
            client = GiteaClient(login=http_login)
        assert client is not None
    finally:
        if env_backup is not None:
            os.environ["TEAX_ALLOW_INSECURE_HTTP"] = env_backup
        else:
            os.environ.pop("TEAX_ALLOW_INSECURE_HTTP", None)


# --- Path Encoding Tests (Security) ---


def test_seg_encodes_slashes():
    """Test _seg encodes slashes to prevent path traversal."""
    from teax.api import _seg

    # Path traversal attempt should be encoded
    assert _seg("../admin") == "..%2Fadmin"
    assert _seg("owner/../other") == "owner%2F..%2Fother"


def test_seg_encodes_special_chars():
    """Test _seg encodes special URL characters."""
    from teax.api import _seg

    # Query string injection attempt should be encoded
    assert _seg("repo?foo=bar") == "repo%3Ffoo%3Dbar"
    # Hash/fragment should be encoded
    assert _seg("repo#anchor") == "repo%23anchor"


def test_normalize_base_url_standard():
    """Test URL normalization for standard URLs."""
    from teax.api import _normalize_base_url

    assert _normalize_base_url("https://example.com") == "https://example.com/api/v1/"
    assert _normalize_base_url("https://example.com/") == "https://example.com/api/v1/"


def test_normalize_base_url_with_existing_api_path():
    """Test URL normalization doesn't double /api/v1."""
    from teax.api import _normalize_base_url

    # Should not produce /api/v1/api/v1/
    result = _normalize_base_url("https://example.com/api/v1")
    assert result == "https://example.com/api/v1/"
    assert "/api/v1/api/v1" not in result


def test_normalize_base_url_subpath():
    """Test URL normalization with subpath installations."""
    from teax.api import _normalize_base_url

    result = _normalize_base_url("https://example.com/gitea")
    assert result == "https://example.com/gitea/api/v1/"


def test_normalize_base_url_subpath_trailing_slash():
    """Test URL normalization with subpath and trailing slash."""
    from teax.api import _normalize_base_url

    result = _normalize_base_url("https://example.com/gitea/")
    assert result == "https://example.com/gitea/api/v1/"


def test_normalize_base_url_deep_subpath():
    """Test URL normalization with deep subpath."""
    from teax.api import _normalize_base_url

    result = _normalize_base_url("https://example.com/apps/gitea")
    assert result == "https://example.com/apps/gitea/api/v1/"


def test_normalize_base_url_subpath_with_api_v1():
    """Test subpath URL with /api/v1 doesn't double up."""
    from teax.api import _normalize_base_url

    result = _normalize_base_url("https://example.com/gitea/api/v1")
    assert result == "https://example.com/gitea/api/v1/"
    assert "/api/v1/api/v1" not in result


def test_normalize_base_url_strips_whitespace():
    """Test URL normalization strips leading/trailing whitespace."""
    from teax.api import _normalize_base_url

    result = _normalize_base_url("  https://example.com  ")
    assert result == "https://example.com/api/v1/"

    result = _normalize_base_url("\thttps://example.com/gitea\n")
    assert result == "https://example.com/gitea/api/v1/"


# --- Client Initialization Tests ---


def test_client_context_manager(mock_login: TeaLogin):
    """Test client works as context manager."""
    with GiteaClient(login=mock_login) as client:
        assert client.base_url == "https://test.example.com"


def test_client_base_url(client: GiteaClient):
    """Test base URL property."""
    assert client.base_url == "https://test.example.com"


@respx.mock
def test_client_subpath_url_handling():
    """Test API calls work with subpath URLs (e.g., https://example.com/gitea/)."""
    # Gitea hosted at a subpath
    subpath_login = TeaLogin(
        name="subpath.example.com",
        url="https://example.com/gitea/",
        token="test-token-123",
        default=True,
        user="testuser",
    )

    # Mock the API endpoint at the subpath
    respx.get("https://example.com/gitea/api/v1/repos/owner/repo/issues/25").mock(
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

    with GiteaClient(login=subpath_login) as client:
        issue = client.get_issue("owner", "repo", 25)
        assert issue.number == 25
        assert issue.title == "Test Issue"


@respx.mock
def test_client_trailing_slash_handling():
    """Test base URL trailing slash is handled correctly."""
    # URL without trailing slash
    no_slash_login = TeaLogin(
        name="noslash.example.com",
        url="https://example.com",
        token="test-token-123",
        default=True,
        user="testuser",
    )

    respx.get("https://example.com/api/v1/repos/owner/repo/issues/25").mock(
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

    with GiteaClient(login=no_slash_login) as client:
        issue = client.get_issue("owner", "repo", 25)
        assert issue.number == 25


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
    # Mock the label lookup with pagination
    respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                    {"id": 2, "name": "feature", "color": "00ff00", "description": ""},
                ],
            ),
            httpx.Response(200, json=[]),  # End of pagination
        ]
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
    # Mock the label lookup with pagination
    respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                ],
            ),
            httpx.Response(200, json=[]),  # End of pagination
        ]
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
    # Mock the label lookup with pagination
    respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                    {"id": 2, "name": "feature", "color": "00ff00", "description": ""},
                ],
            ),
            httpx.Response(200, json=[]),  # End of pagination
        ]
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
    """Test listing repository labels - stops early when items < limit."""
    # Mock label response with fewer items than limit (50)
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    route.side_effect = [
        httpx.Response(
            200,
            json=[
                {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                {"id": 2, "name": "feature", "color": "00ff00", "description": ""},
                {"id": 3, "name": "docs", "color": "0000ff", "description": ""},
            ],
        ),
    ]

    labels = client.list_repo_labels("owner", "repo")

    assert len(labels) == 3
    assert labels[0].name == "bug"
    assert labels[2].name == "docs"
    # Only 1 request needed when items < limit (no extra empty page request)
    assert route.call_count == 1


@respx.mock
def test_list_repo_labels_pagination_full_page(client: GiteaClient):
    """Test listing labels continues when items == limit."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    # Create exactly 50 labels for first page (to match limit)
    page1_labels = [
        {"id": i, "name": f"label-{i}", "color": "ff0000", "description": ""}
        for i in range(1, 51)
    ]
    page2_labels = [
        {"id": 51, "name": "label-51", "color": "ff0000", "description": ""}
    ]
    route.side_effect = [
        httpx.Response(200, json=page1_labels),
        httpx.Response(200, json=page2_labels),  # Less than limit, stops here
    ]

    labels = client.list_repo_labels("owner", "repo")

    assert len(labels) == 51
    assert labels[0].name == "label-1"
    assert labels[50].name == "label-51"
    # 2 requests: first page (50 items), second page (1 item < limit)
    assert route.call_count == 2


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


@respx.mock
def test_list_repo_labels_populates_cache(client: GiteaClient):
    """Test that list_repo_labels populates the label cache for resolve_label_ids."""
    label_route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    label_route.mock(
        side_effect=[
            httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                    {"id": 2, "name": "feature", "color": "00ff00", "description": ""},
                ],
            ),
        ]
    )
    respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels"
    ).mock(return_value=httpx.Response(200, json=[]))

    # First, call list_repo_labels (should populate cache)
    labels = client.list_repo_labels("owner", "repo")
    assert len(labels) == 2
    assert label_route.call_count == 1
    assert "owner/repo" in client._label_cache  # Cache populated

    # Now add_issue_labels should use the cache, not fetch again
    client.add_issue_labels("owner", "repo", 25, ["bug"])

    # Still only 1 label fetch (the initial list_repo_labels)
    assert label_route.call_count == 1


# --- Label Caching Tests ---


@respx.mock
def test_label_cache_avoids_redundant_calls(client: GiteaClient):
    """Test that label resolution uses cache to avoid redundant API calls."""
    label_route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    label_route.mock(
        side_effect=[
            httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                    {"id": 2, "name": "feature", "color": "00ff00", "description": ""},
                ],
            ),
        ]
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

    # Label lookup should only be called once due to caching (items < limit = 1 call)
    assert label_route.call_count == 1


@respx.mock
def test_label_cache_per_repo(client: GiteaClient):
    """Test that label cache is per-repo."""
    label_route_1 = respx.get("https://test.example.com/api/v1/repos/owner/repo1/labels")
    label_route_1.mock(
        side_effect=[
            httpx.Response(
                200,
                json=[{"id": 1, "name": "bug", "color": "ff0000", "description": ""}],
            ),
        ]
    )
    label_route_2 = respx.get("https://test.example.com/api/v1/repos/owner/repo2/labels")
    label_route_2.mock(
        side_effect=[
            httpx.Response(
                200,
                json=[{"id": 5, "name": "bug", "color": "ff0000", "description": ""}],
            ),
        ]
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

    # Each repo gets 1 call (items < limit = 1 call per repo)
    assert label_route_1.call_count == 1
    assert label_route_2.call_count == 1


@respx.mock
def test_label_cache_cleared_on_close(client: GiteaClient):
    """Test that label cache is cleared when client is closed."""
    label_route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    label_route.mock(
        side_effect=[
            httpx.Response(
                200,
                json=[{"id": 1, "name": "bug", "color": "ff0000", "description": ""}],
            ),
        ]
    )
    respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels"
    ).mock(return_value=httpx.Response(200, json=[]))

    # Populate the cache
    client.add_issue_labels("owner", "repo", 25, ["bug"])
    assert label_route.call_count == 1  # items < limit = 1 call

    # Close and verify cache is cleared
    client.close()
    assert client._label_cache == {}


@respx.mock
def test_label_cache_updated_on_create_label(client: GiteaClient):
    """Test that create_label updates the cache with the new label."""
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
    assert client._label_cache["owner/repo"]["bug"] == 1

    # Creating a label should update the cache (not invalidate)
    client.create_label("owner", "repo", "new-label", "0000ff")
    assert "owner/repo" in client._label_cache
    assert client._label_cache["owner/repo"]["new-label"] == 2

    # Next operation should NOT fetch labels again (cache is still valid)
    client.add_issue_labels("owner", "repo", 25, ["bug"])
    assert label_route.call_count == 1  # No additional API call


# --- Milestone Operations Tests ---


@respx.mock
def test_get_milestone(client: GiteaClient):
    """Test getting a milestone by ID."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones/5").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 5,
                "title": "Sprint 1",
                "state": "open",
            },
        )
    )

    milestone = client.get_milestone("owner", "repo", 5)

    assert milestone.id == 5
    assert milestone.title == "Sprint 1"
    assert milestone.state == "open"


@respx.mock
def test_get_milestone_not_found(client: GiteaClient):
    """Test 404 error when milestone not found."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones/999").mock(
        return_value=httpx.Response(404, json={"message": "Milestone not found"})
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.get_milestone("owner", "repo", 999)

    assert exc_info.value.response.status_code == 404


@respx.mock
def test_list_milestones(client: GiteaClient):
    """Test listing milestones."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "title": "v1.0", "state": "closed"},
                {"id": 2, "title": "v1.1", "state": "open"},
                {"id": 3, "title": "Sprint 1", "state": "open"},
            ],
        )
    )

    milestones = client.list_milestones("owner", "repo")

    assert len(milestones) == 3
    assert milestones[0].title == "v1.0"
    assert milestones[1].title == "v1.1"
    assert milestones[2].title == "Sprint 1"
    # Verify state filter was passed
    assert route.calls.last.request.url.params["state"] == "all"


@respx.mock
def test_list_milestones_populates_cache(client: GiteaClient):
    """Test that list_milestones populates milestone cache."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "title": "v1.0", "state": "closed"},
                {"id": 2, "title": "Sprint 1", "state": "open"},
            ],
        )
    )

    client.list_milestones("owner", "repo")

    # Cache should be populated
    assert "owner/repo" in client._milestone_cache
    assert client._milestone_cache["owner/repo"]["v1.0"] == 1
    assert client._milestone_cache["owner/repo"]["Sprint 1"] == 2


@respx.mock
def test_resolve_milestone_by_id(client: GiteaClient):
    """Test resolving milestone by numeric ID."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones/5").mock(
        return_value=httpx.Response(
            200, json={"id": 5, "title": "Sprint 1", "state": "open"}
        )
    )

    milestone_id = client.resolve_milestone("owner", "repo", "5")

    assert milestone_id == 5


@respx.mock
def test_resolve_milestone_by_name(client: GiteaClient):
    """Test resolving milestone by name."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "title": "v1.0", "state": "closed"},
                {"id": 5, "title": "Sprint 1", "state": "open"},
            ],
        )
    )

    milestone_id = client.resolve_milestone("owner", "repo", "Sprint 1")

    assert milestone_id == 5


@respx.mock
def test_resolve_milestone_name_not_found(client: GiteaClient):
    """Test error when milestone name not found."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "title": "v1.0", "state": "open"}]
        )
    )

    with pytest.raises(ValueError, match="Milestone 'Unknown' not found"):
        client.resolve_milestone("owner", "repo", "Unknown")


@respx.mock
def test_resolve_milestone_id_not_found(client: GiteaClient):
    """Test 404 error when milestone ID not found."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones/999").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.resolve_milestone("owner", "repo", "999")

    assert exc_info.value.response.status_code == 404


@respx.mock
def test_milestone_cache_used_on_second_resolve(client: GiteaClient):
    """Test that milestone cache is used for subsequent resolves."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "title": "v1.0", "state": "closed"},
                {"id": 5, "title": "Sprint 1", "state": "open"},
            ],
        )
    )

    # First resolve populates cache
    id1 = client.resolve_milestone("owner", "repo", "Sprint 1")
    assert id1 == 5
    assert route.call_count == 1

    # Second resolve uses cache
    id2 = client.resolve_milestone("owner", "repo", "v1.0")
    assert id2 == 1
    assert route.call_count == 1  # No additional API call


@respx.mock
def test_milestone_cache_cleared_on_close(client: GiteaClient):
    """Test that milestone cache is cleared when client is closed."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "title": "v1.0", "state": "open"}]
        )
    )

    # Populate cache
    client.list_milestones("owner", "repo")
    assert "owner/repo" in client._milestone_cache

    # Close should clear cache
    client.close()
    assert client._milestone_cache == {}


# --- Security Configuration Tests ---


def test_client_trust_env_disabled(mock_login: TeaLogin, monkeypatch):
    """Test that client ignores proxy environment variables.

    This verifies that httpx.Client is created with trust_env=False,
    preventing API tokens from leaking through HTTP_PROXY/HTTPS_PROXY.
    """
    # Set proxy env vars that would redirect traffic if trust_env were True
    monkeypatch.setenv("HTTP_PROXY", "http://malicious-proxy:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://malicious-proxy:8080")

    client = GiteaClient(login=mock_login)

    # The internal httpx client should have trust_env=False
    # Note: This tests httpx internals, may need update if httpx changes API
    assert client._client._trust_env is False

    # Verify the client's base URL is correct (not redirected to proxy)
    assert client.base_url == mock_login.url.rstrip("/")

    client.close()


# --- Truncation Warning Tests ---


@respx.mock
def test_list_comments_truncation_warning(client: GiteaClient):
    """Test truncation warning when comments exceed max_pages."""
    route = respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/issues/25/comments"
    )
    # Return exactly 50 items per page to simulate max_pages hit
    page_data = [
        {
            "id": i,
            "body": f"Comment {i}",
            "user": {"id": 1, "login": "user", "full_name": ""},
            "created_at": "2024-01-01T00:00:00Z",
        }
        for i in range(50)
    ]
    # With max_pages=2, we need 2 pages of 50 items each
    route.side_effect = [
        httpx.Response(200, json=page_data),
        httpx.Response(200, json=page_data),  # Full page triggers next iteration
    ]

    with pytest.warns(UserWarning, match="Comments list truncated at 2 pages"):
        client.list_comments("owner", "repo", 25, max_pages=2)


@respx.mock
def test_list_repo_labels_truncation_warning(client: GiteaClient):
    """Test truncation warning when labels exceed max_pages."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    # Return exactly 50 items per page to simulate max_pages hit
    page_data = [
        {"id": i, "name": f"label-{i}", "color": "ff0000", "description": ""}
        for i in range(50)
    ]
    route.side_effect = [
        httpx.Response(200, json=page_data),
        httpx.Response(200, json=page_data),  # Full page triggers next iteration
    ]

    with pytest.warns(UserWarning, match="Labels list truncated at 2 pages"):
        client.list_repo_labels("owner", "repo", max_pages=2)


@respx.mock
def test_list_milestones_truncation_warning(client: GiteaClient):
    """Test truncation warning when milestones exceed max_pages."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones")
    # Return exactly 50 items per page to simulate max_pages hit
    page_data = [
        {"id": i, "title": f"Milestone {i}", "state": "open"} for i in range(50)
    ]
    route.side_effect = [
        httpx.Response(200, json=page_data),
        httpx.Response(200, json=page_data),  # Full page triggers next iteration
    ]

    with pytest.warns(UserWarning, match="Milestones list truncated at 2 pages"):
        client.list_milestones("owner", "repo", max_pages=2)
