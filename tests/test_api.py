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


def test_seg_rejects_dot_segments():
    """Test _seg rejects '.' and '..' to prevent path traversal."""
    from teax.api import _seg

    # Single dot (current directory reference)
    with pytest.raises(ValueError, match="dot-segment traversal"):
        _seg(".")

    # Double dot (parent directory reference)
    with pytest.raises(ValueError, match="dot-segment traversal"):
        _seg("..")

    # Valid segments containing dots should still work
    assert _seg(".gitignore") == ".gitignore"
    assert _seg("test..file") == "test..file"
    assert _seg("a.b.c") == "a.b.c"


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

    issue = client.create_issue("owner", "repo", "New Issue", body="Issue body")

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


@respx.mock
def test_edit_issue_state_change(client: GiteaClient):
    """Test changing issue state (close/reopen)."""
    route = respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/42")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 200,
                "number": 42,
                "title": "Test Issue",
                "state": "closed",
                "labels": [],
                "assignees": [],
                "milestone": None,
            },
        )
    )

    result = client.edit_issue("owner", "repo", 42, state="closed")

    import json

    request_body = json.loads(route.calls.last.request.content)
    assert request_body == {"state": "closed"}
    assert result.number == 42
    assert result.state == "closed"


@respx.mock
def test_create_issue_basic(client: GiteaClient):
    """Test creating an issue with just title."""
    route = respx.post("https://test.example.com/api/v1/repos/owner/repo/issues")
    route.mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 300,
                "number": 50,
                "title": "New Issue",
                "state": "open",
                "labels": [],
                "assignees": [],
                "milestone": None,
                "body": "",
            },
        )
    )

    result = client.create_issue("owner", "repo", "New Issue")

    import json

    request_body = json.loads(route.calls.last.request.content)
    assert request_body == {"title": "New Issue"}
    assert result.number == 50
    assert result.title == "New Issue"


@respx.mock
def test_create_issue_with_all_options(client: GiteaClient):
    """Test creating an issue with all options."""
    route = respx.post("https://test.example.com/api/v1/repos/owner/repo/issues")
    route.mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 301,
                "number": 51,
                "title": "Full Issue",
                "state": "open",
                "body": "Issue body here",
                "labels": [{"id": 1, "name": "bug", "color": "ff0000"}],
                "assignees": [{"id": 1, "login": "user1"}],
                "milestone": {"id": 5, "title": "v1.0"},
            },
        )
    )

    result = client.create_issue(
        "owner",
        "repo",
        "Full Issue",
        body="Issue body here",
        labels=[1],
        assignees=["user1"],
        milestone=5,
    )

    import json

    request_body = json.loads(route.calls.last.request.content)
    assert request_body == {
        "title": "Full Issue",
        "body": "Issue body here",
        "labels": [1],
        "assignees": ["user1"],
        "milestone": 5,
    }
    assert result.number == 51


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
    label_route_1 = respx.get(
        "https://test.example.com/api/v1/repos/owner/repo1/labels"
    )
    label_route_1.mock(
        side_effect=[
            httpx.Response(
                200,
                json=[{"id": 1, "name": "bug", "color": "ff0000", "description": ""}],
            ),
        ]
    )
    label_route_2 = respx.get(
        "https://test.example.com/api/v1/repos/owner/repo2/labels"
    )
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


@respx.mock
def test_create_milestone(client: GiteaClient):
    """Test creating a milestone."""
    route = respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/milestones"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 10,
                "title": "Sprint 50",
                "state": "open",
                "description": "",
                "open_issues": 0,
                "closed_issues": 0,
            },
        )
    )

    milestone = client.create_milestone("owner", "repo", "Sprint 50")

    assert route.called
    assert milestone.id == 10
    assert milestone.title == "Sprint 50"
    assert milestone.state == "open"


@respx.mock
def test_create_milestone_with_description_and_due_date(client: GiteaClient):
    """Test creating a milestone with description and due date."""
    route = respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/milestones"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 10,
                "title": "Sprint 50",
                "state": "open",
                "description": "Sprint goals",
                "due_on": "2026-03-01T00:00:00Z",
            },
        )
    )

    milestone = client.create_milestone(
        "owner",
        "repo",
        "Sprint 50",
        description="Sprint goals",
        due_on="2026-03-01T00:00:00Z",
    )

    assert route.called
    # Verify request body
    request_json = route.calls.last.request.content.decode()
    assert "Sprint goals" in request_json
    assert "2026-03-01T00:00:00Z" in request_json
    assert milestone.id == 10
    assert milestone.description == "Sprint goals"


@respx.mock
def test_create_milestone_updates_cache(client: GiteaClient):
    """Test that create_milestone updates the milestone cache."""
    # Pre-populate cache
    client._milestone_cache["owner/repo"] = {"Existing": 1}

    respx.post("https://test.example.com/api/v1/repos/owner/repo/milestones").mock(
        return_value=httpx.Response(
            201,
            json={"id": 10, "title": "Sprint 50", "state": "open"},
        )
    )

    client.create_milestone("owner", "repo", "Sprint 50")

    # Cache should now include the new milestone
    assert client._milestone_cache["owner/repo"]["Sprint 50"] == 10
    assert client._milestone_cache["owner/repo"]["Existing"] == 1


@respx.mock
def test_update_milestone_state(client: GiteaClient):
    """Test updating milestone state (close/reopen)."""
    route = respx.patch(
        "https://test.example.com/api/v1/repos/owner/repo/milestones/5"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"id": 5, "title": "Sprint 50", "state": "closed"},
        )
    )

    milestone = client.update_milestone("owner", "repo", 5, state="closed")

    assert route.called
    assert milestone.state == "closed"


@respx.mock
def test_update_milestone_title(client: GiteaClient):
    """Test updating milestone title."""
    route = respx.patch(
        "https://test.example.com/api/v1/repos/owner/repo/milestones/5"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"id": 5, "title": "Sprint 50 (Extended)", "state": "open"},
        )
    )

    milestone = client.update_milestone(
        "owner", "repo", 5, title="Sprint 50 (Extended)"
    )

    assert route.called
    assert milestone.title == "Sprint 50 (Extended)"


@respx.mock
def test_update_milestone_due_date_clear(client: GiteaClient):
    """Test clearing milestone due date with empty string."""
    route = respx.patch(
        "https://test.example.com/api/v1/repos/owner/repo/milestones/5"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"id": 5, "title": "Sprint 50", "state": "open", "due_on": None},
        )
    )

    milestone = client.update_milestone("owner", "repo", 5, due_on="")

    assert route.called
    # Verify due_on is sent as null in request body
    import json

    request_body = json.loads(route.calls.last.request.content.decode())
    assert request_body["due_on"] is None
    assert milestone.due_on is None


@respx.mock
def test_update_milestone_invalid_state(client: GiteaClient):
    """Test error when updating with invalid state."""
    with pytest.raises(ValueError, match="Invalid state"):
        client.update_milestone("owner", "repo", 5, state="invalid")


@respx.mock
def test_update_milestone_cache_on_title_change(client: GiteaClient):
    """Test that cache is updated when milestone title changes."""
    # Pre-populate cache
    client._milestone_cache["owner/repo"] = {"Sprint 50": 5}

    respx.patch(
        "https://test.example.com/api/v1/repos/owner/repo/milestones/5"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"id": 5, "title": "Sprint 50 (Extended)", "state": "open"},
        )
    )

    client.update_milestone("owner", "repo", 5, title="Sprint 50 (Extended)")

    # Old title should be removed, new title should exist
    assert "Sprint 50" not in client._milestone_cache["owner/repo"]
    assert client._milestone_cache["owner/repo"]["Sprint 50 (Extended)"] == 5


# --- Comment CRUD Tests ---


@respx.mock
def test_create_comment(client: GiteaClient):
    """Test creating a comment on an issue."""
    route = respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/issues/42/comments"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 12345,
                "body": "Test comment",
                "user": {"id": 1, "login": "testuser", "full_name": "Test User"},
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-15T10:00:00Z",
            },
        )
    )

    comment = client.create_comment("owner", "repo", 42, "Test comment")

    assert route.called
    assert comment.id == 12345
    assert comment.body == "Test comment"
    assert comment.user.login == "testuser"


@respx.mock
def test_edit_comment(client: GiteaClient):
    """Test editing an existing comment."""
    route = respx.patch(
        "https://test.example.com/api/v1/repos/owner/repo/issues/comments/12345"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 12345,
                "body": "Updated comment",
                "user": {"id": 1, "login": "testuser", "full_name": "Test User"},
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-15T11:00:00Z",
            },
        )
    )

    comment = client.edit_comment("owner", "repo", 12345, "Updated comment")

    assert route.called
    assert comment.id == 12345
    assert comment.body == "Updated comment"


@respx.mock
def test_delete_comment(client: GiteaClient):
    """Test deleting a comment."""
    route = respx.delete(
        "https://test.example.com/api/v1/repos/owner/repo/issues/comments/12345"
    ).mock(return_value=httpx.Response(204))

    # Should not raise
    client.delete_comment("owner", "repo", 12345)

    assert route.called


# --- Actions/Runner Operations Tests ---


def test_actions_base_path_repo_scope(client: GiteaClient):
    """Test _actions_base_path with repo scope."""
    path = client._actions_base_path(owner="myowner", repo="myrepo")
    assert path == "repos/myowner/myrepo/actions"


def test_actions_base_path_org_scope(client: GiteaClient):
    """Test _actions_base_path with org scope."""
    path = client._actions_base_path(org="myorg")
    assert path == "orgs/myorg/actions"


def test_actions_base_path_global_scope(client: GiteaClient):
    """Test _actions_base_path with global scope."""
    path = client._actions_base_path(global_scope=True)
    assert path == "admin/actions"


def test_actions_base_path_requires_scope(client: GiteaClient):
    """Test _actions_base_path raises error when no scope provided."""
    with pytest.raises(ValueError, match="Must specify --repo, --org, or --global"):
        client._actions_base_path()


def test_actions_base_path_rejects_multiple_scopes(client: GiteaClient):
    """Test _actions_base_path raises error with multiple scopes."""
    with pytest.raises(ValueError, match="Specify only one of"):
        client._actions_base_path(owner="owner", repo="repo", org="org")


def test_actions_base_path_encodes_special_chars(client: GiteaClient):
    """Test _actions_base_path encodes special characters."""
    path = client._actions_base_path(owner="my/owner", repo="my/repo")
    assert path == "repos/my%2Fowner/my%2Frepo/actions"


@respx.mock
def test_list_runners_repo_scope(client: GiteaClient):
    """Test listing runners with repo scope."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runners").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "runner-1",
                    "status": "online",
                    "busy": False,
                    "labels": ["ubuntu-latest"],
                    "version": "v0.2.6",
                },
                {
                    "id": 2,
                    "name": "runner-2",
                    "status": "offline",
                    "busy": False,
                    "labels": ["self-hosted", "linux"],
                    "version": "v0.2.5",
                },
            ],
        )
    )

    runners = client.list_runners(owner="owner", repo="repo")

    assert len(runners) == 2
    assert runners[0].id == 1
    assert runners[0].name == "runner-1"
    assert runners[0].status == "online"
    assert runners[0].labels == ["ubuntu-latest"]
    assert runners[1].id == 2
    assert runners[1].status == "offline"


@respx.mock
def test_list_runners_org_scope(client: GiteaClient):
    """Test listing runners with org scope."""
    respx.get("https://test.example.com/api/v1/orgs/myorg/actions/runners").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 10,
                    "name": "org-runner",
                    "status": "online",
                    "busy": True,
                    "labels": [],
                    "version": "",
                },
            ],
        )
    )

    runners = client.list_runners(org="myorg")

    assert len(runners) == 1
    assert runners[0].id == 10
    assert runners[0].name == "org-runner"
    assert runners[0].busy is True


@respx.mock
def test_list_runners_global_scope(client: GiteaClient):
    """Test listing runners with global scope."""
    respx.get("https://test.example.com/api/v1/admin/actions/runners").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 100,
                    "name": "global-runner",
                    "status": "idle",
                    "busy": False,
                    "labels": ["arm64"],
                    "version": "v0.2.6",
                },
            ],
        )
    )

    runners = client.list_runners(global_scope=True)

    assert len(runners) == 1
    assert runners[0].id == 100
    assert runners[0].name == "global-runner"


@respx.mock
def test_list_runners_with_dict_labels(client: GiteaClient):
    """Test listing runners handles labels as list of dicts."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runners").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "runner-1",
                    "status": "online",
                    "busy": False,
                    "labels": [
                        {"id": 1, "name": "ubuntu-latest", "type": "system"},
                        {"id": 2, "name": "self-hosted", "type": "custom"},
                    ],
                    "version": "v0.2.6",
                },
            ],
        )
    )

    runners = client.list_runners(owner="owner", repo="repo")

    assert len(runners) == 1
    assert runners[0].labels == ["ubuntu-latest", "self-hosted"]


@respx.mock
def test_list_runners_wrapped_response(client: GiteaClient):
    """Test listing runners handles wrapped response format."""
    respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runners").mock(
        return_value=httpx.Response(
            200,
            json={
                "runners": [
                    {
                        "id": 1,
                        "name": "runner-1",
                        "status": "online",
                        "busy": False,
                        "labels": [],
                        "version": "",
                    },
                ]
            },
        )
    )

    runners = client.list_runners(owner="owner", repo="repo")

    assert len(runners) == 1
    assert runners[0].id == 1


@respx.mock
def test_list_runners_pagination_truncation(client: GiteaClient):
    """Test truncation warning when runners exceed max_pages."""
    route = respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/runners"
    )
    page_data = [
        {
            "id": i,
            "name": f"runner-{i}",
            "status": "online",
            "busy": False,
            "labels": [],
            "version": "",
        }
        for i in range(50)
    ]
    route.side_effect = [
        httpx.Response(200, json=page_data),
        httpx.Response(200, json=page_data),
    ]

    with pytest.warns(UserWarning, match="Runners list truncated at 2 pages"):
        client.list_runners(owner="owner", repo="repo", max_pages=2)


@respx.mock
def test_get_runner(client: GiteaClient):
    """Test getting a runner by ID."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/runners/42"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 42,
                "name": "my-runner",
                "status": "online",
                "busy": True,
                "labels": ["ubuntu-latest", "docker"],
                "version": "v0.2.6",
            },
        )
    )

    runner = client.get_runner(42, owner="owner", repo="repo")

    assert runner.id == 42
    assert runner.name == "my-runner"
    assert runner.status == "online"
    assert runner.busy is True
    assert runner.labels == ["ubuntu-latest", "docker"]


@respx.mock
def test_get_runner_not_found(client: GiteaClient):
    """Test 404 error when runner not found."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/runners/999"
    ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.get_runner(999, owner="owner", repo="repo")

    assert exc_info.value.response.status_code == 404


@respx.mock
def test_delete_runner(client: GiteaClient):
    """Test deleting a runner."""
    route = respx.delete(
        "https://test.example.com/api/v1/repos/owner/repo/actions/runners/42"
    )
    route.mock(return_value=httpx.Response(204))

    client.delete_runner(42, owner="owner", repo="repo")

    assert route.called


@respx.mock
def test_delete_runner_org_scope(client: GiteaClient):
    """Test deleting a runner with org scope."""
    route = respx.delete(
        "https://test.example.com/api/v1/orgs/myorg/actions/runners/42"
    )
    route.mock(return_value=httpx.Response(204))

    client.delete_runner(42, org="myorg")

    assert route.called


@respx.mock
def test_get_runner_registration_token(client: GiteaClient):
    """Test getting a registration token."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/runners/registration-token"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"token": "AAABBBCCCDDD123456"},
        )
    )

    token = client.get_runner_registration_token(owner="owner", repo="repo")

    assert token.token == "AAABBBCCCDDD123456"


@respx.mock
def test_get_runner_registration_token_org_scope(client: GiteaClient):
    """Test getting a registration token with org scope."""
    respx.get(
        "https://test.example.com/api/v1/orgs/myorg/actions/runners/registration-token"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"token": "ORG_TOKEN_123"},
        )
    )

    token = client.get_runner_registration_token(org="myorg")

    assert token.token == "ORG_TOKEN_123"


@respx.mock
def test_get_runner_registration_token_global_scope(client: GiteaClient):
    """Test getting a registration token with global scope."""
    respx.get(
        "https://test.example.com/api/v1/admin/actions/runners/registration-token"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"token": "GLOBAL_TOKEN_456"},
        )
    )

    token = client.get_runner_registration_token(global_scope=True)

    assert token.token == "GLOBAL_TOKEN_456"


# --- Package Operations Tests ---


def test_packages_base_url(client: GiteaClient):
    """Test _packages_base_url builds correct URL."""
    url = client._packages_base_url("homelab-teams")
    assert url == "https://test.example.com/api/packages/homelab-teams"


def test_packages_base_url_encodes_special_chars(client: GiteaClient):
    """Test _packages_base_url encodes special characters."""
    url = client._packages_base_url("my/owner")
    assert url == "https://test.example.com/api/packages/my%2Fowner"


def test_packages_base_url_with_api_v1_suffix():
    """Test _packages_base_url correctly strips /api/v1 from login URL."""
    from teax.models import TeaLogin

    # Login URL already includes /api/v1 (common tea config format)
    login = TeaLogin(
        name="test.example.com",
        url="https://test.example.com/api/v1",
        token="test-token-123",
        default=True,
    )
    client = GiteaClient(login=login)
    url = client._packages_base_url("homelab-teams")
    # Should NOT result in /api/v1/api/packages/ (double API path)
    assert url == "https://test.example.com/api/packages/homelab-teams"
    assert "/api/v1/api/" not in url


def test_packages_base_url_with_subpath():
    """Test _packages_base_url handles base URL with subpath correctly."""
    from teax.models import TeaLogin

    # Login URL has subpath (e.g., reverse proxy at /gitea)
    login = TeaLogin(
        name="example.com",
        url="https://example.com/gitea/api/v1",
        token="test-token-123",
        default=True,
    )
    client = GiteaClient(login=login)
    url = client._packages_base_url("myorg")
    assert url == "https://example.com/gitea/api/packages/myorg"


@respx.mock
def test_list_packages(client: GiteaClient):
    """Test listing packages for an owner."""
    respx.get("https://test.example.com/api/packages/homelab-teams").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "owner": {"id": 10, "login": "homelab-teams", "full_name": ""},
                    "name": "teax",
                    "type": "pypi",
                    "version": "0.1.0",
                    "created_at": "2024-01-15T10:00:00Z",
                    "html_url": "https://test.example.com/packages/pypi/teax",
                },
                {
                    "id": 2,
                    "owner": {"id": 10, "login": "homelab-teams", "full_name": ""},
                    "name": "myimage",
                    "type": "container",
                    "version": "latest",
                    "created_at": "2024-01-16T10:00:00Z",
                    "html_url": "https://test.example.com/packages/container/myimage",
                },
            ],
        )
    )

    packages = client.list_packages("homelab-teams")

    assert len(packages) == 2
    assert packages[0].name == "teax"
    assert packages[0].type == "pypi"
    assert packages[0].version == "0.1.0"
    assert packages[1].name == "myimage"
    assert packages[1].type == "container"


@respx.mock
def test_list_packages_with_type_filter(client: GiteaClient):
    """Test listing packages with type filter."""
    route = respx.get("https://test.example.com/api/packages/homelab-teams")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "owner": {"id": 10, "login": "homelab-teams", "full_name": ""},
                    "name": "teax",
                    "type": "pypi",
                    "version": "0.1.0",
                    "created_at": "2024-01-15T10:00:00Z",
                    "html_url": "",
                },
            ],
        )
    )

    packages = client.list_packages("homelab-teams", pkg_type="pypi")

    assert len(packages) == 1
    # Verify type filter was passed as query parameter
    assert route.calls.last.request.url.params["type"] == "pypi"


@respx.mock
def test_list_packages_empty(client: GiteaClient):
    """Test listing packages when none exist."""
    respx.get("https://test.example.com/api/packages/homelab-teams").mock(
        return_value=httpx.Response(200, json=[])
    )

    packages = client.list_packages("homelab-teams")

    assert packages == []


@respx.mock
def test_list_packages_truncation_warning(client: GiteaClient):
    """Test truncation warning when packages exceed max_pages."""
    route = respx.get("https://test.example.com/api/packages/homelab-teams")
    page_data = [
        {
            "id": i,
            "owner": {"id": 10, "login": "homelab-teams", "full_name": ""},
            "name": f"pkg-{i}",
            "type": "pypi",
            "version": "1.0.0",
            "created_at": "2024-01-15T10:00:00Z",
            "html_url": "",
        }
        for i in range(50)
    ]
    route.side_effect = [
        httpx.Response(200, json=page_data),
        httpx.Response(200, json=page_data),
    ]

    with pytest.warns(UserWarning, match="Packages list truncated at 2 pages"):
        client.list_packages("homelab-teams", max_pages=2)


@respx.mock
def test_list_package_versions(client: GiteaClient):
    """Test listing package versions."""
    respx.get("https://test.example.com/api/packages/homelab-teams/pypi/teax").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 3,
                    "version": "0.3.0",
                    "created_at": "2024-01-17T10:00:00Z",
                    "html_url": "https://test.example.com/packages/pypi/teax/0.3.0",
                },
                {
                    "id": 2,
                    "version": "0.2.0",
                    "created_at": "2024-01-16T10:00:00Z",
                    "html_url": "https://test.example.com/packages/pypi/teax/0.2.0",
                },
                {
                    "id": 1,
                    "version": "0.1.0",
                    "created_at": "2024-01-15T10:00:00Z",
                    "html_url": "https://test.example.com/packages/pypi/teax/0.1.0",
                },
            ],
        )
    )

    versions = client.list_package_versions("homelab-teams", "pypi", "teax")

    assert len(versions) == 3
    assert versions[0].version == "0.3.0"
    assert versions[1].version == "0.2.0"
    assert versions[2].version == "0.1.0"


@respx.mock
def test_list_package_versions_empty(client: GiteaClient):
    """Test listing package versions when none exist."""
    respx.get("https://test.example.com/api/packages/homelab-teams/pypi/teax").mock(
        return_value=httpx.Response(200, json=[])
    )

    versions = client.list_package_versions("homelab-teams", "pypi", "teax")

    assert versions == []


@respx.mock
def test_list_package_versions_sorts_by_created_at(client: GiteaClient):
    """Test list_package_versions sorts versions by created_at descending."""
    # Return versions in unsorted order (API doesn't guarantee order)
    respx.get("https://test.example.com/api/packages/homelab-teams/pypi/teax").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "version": "0.1.0",
                    "created_at": "2024-01-15T10:00:00Z",  # Oldest
                    "html_url": "",
                },
                {
                    "id": 3,
                    "version": "0.3.0",
                    "created_at": "2024-01-17T10:00:00Z",  # Newest
                    "html_url": "",
                },
                {
                    "id": 2,
                    "version": "0.2.0",
                    "created_at": "2024-01-16T10:00:00Z",  # Middle
                    "html_url": "",
                },
            ],
        )
    )

    versions = client.list_package_versions("homelab-teams", "pypi", "teax")

    # Should be sorted by created_at descending (newest first)
    assert len(versions) == 3
    assert versions[0].version == "0.3.0"  # Newest
    assert versions[1].version == "0.2.0"  # Middle
    assert versions[2].version == "0.1.0"  # Oldest


@respx.mock
def test_get_package(client: GiteaClient):
    """Test getting package details."""
    respx.get("https://test.example.com/api/packages/homelab-teams/pypi/teax").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "version": "0.1.0",
                    "created_at": "2024-01-15T10:00:00Z",
                    "html_url": "https://test.example.com/packages/pypi/teax/0.1.0",
                },
            ],
        )
    )

    package = client.get_package("homelab-teams", "pypi", "teax")

    assert package.name == "teax"
    assert package.type == "pypi"
    assert package.version == "0.1.0"


@respx.mock
def test_get_package_not_found(client: GiteaClient):
    """Test error when package not found."""
    respx.get(
        "https://test.example.com/api/packages/homelab-teams/pypi/nonexistent"
    ).mock(return_value=httpx.Response(200, json=[]))

    with pytest.raises(ValueError, match="Package 'nonexistent' not found"):
        client.get_package("homelab-teams", "pypi", "nonexistent")


@respx.mock
def test_delete_package_version(client: GiteaClient):
    """Test deleting a package version."""
    route = respx.delete(
        "https://test.example.com/api/packages/homelab-teams/container/myimage/latest"
    )
    route.mock(return_value=httpx.Response(204))

    client.delete_package_version("homelab-teams", "container", "myimage", "latest")

    assert route.called


def test_delete_package_version_pypi_blocked(client: GiteaClient):
    """Test that PyPI package deletion is blocked with helpful message."""
    with pytest.raises(ValueError, match="PyPI packages cannot be deleted via API"):
        client.delete_package_version("homelab-teams", "pypi", "teax", "0.1.0")


def test_delete_package_version_pypi_blocked_case_insensitive(client: GiteaClient):
    """Test that PyPI detection is case-insensitive."""
    with pytest.raises(ValueError, match="PyPI packages cannot be deleted via API"):
        client.delete_package_version("homelab-teams", "PyPI", "teax", "0.1.0")


@respx.mock
def test_delete_package_version_encodes_path(client: GiteaClient):
    """Test that delete_package_version encodes path segments."""
    route = respx.delete(
        "https://test.example.com/api/packages/home%2Flab/container/my%2Fimage/1.0%2F0"
    )
    route.mock(return_value=httpx.Response(204))

    client.delete_package_version("home/lab", "container", "my/image", "1.0/0")

    assert route.called


# --- Workflow Operations Tests ---


@respx.mock
def test_list_workflows(client: GiteaClient):
    """Test listing workflows for a repository."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "workflows": [
                    {
                        "id": "ci.yml",
                        "name": "CI Pipeline",
                        "path": ".gitea/workflows/ci.yml",
                        "state": "active",
                        "created_at": "2024-01-15T10:00:00Z",
                        "updated_at": "2024-01-16T10:00:00Z",
                    },
                    {
                        "id": "deploy.yml",
                        "name": "Deploy",
                        "path": ".gitea/workflows/deploy.yml",
                        "state": "disabled_manually",
                        "created_at": "2024-01-14T10:00:00Z",
                        "updated_at": "2024-01-15T10:00:00Z",
                    },
                ]
            },
        )
    )

    workflows = client.list_workflows("owner", "repo")

    assert len(workflows) == 2
    assert workflows[0].id == "ci.yml"
    assert workflows[0].name == "CI Pipeline"
    assert workflows[0].state == "active"
    assert workflows[1].id == "deploy.yml"
    assert workflows[1].state == "disabled_manually"


@respx.mock
def test_list_workflows_array_response(client: GiteaClient):
    """Test listing workflows when API returns array instead of wrapped object."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "ci.yml",
                    "name": "CI",
                    "path": ".gitea/workflows/ci.yml",
                    "state": "active",
                    "created_at": "",
                    "updated_at": "",
                },
            ],
        )
    )

    workflows = client.list_workflows("owner", "repo")

    assert len(workflows) == 1
    assert workflows[0].id == "ci.yml"


@respx.mock
def test_list_workflows_empty(client: GiteaClient):
    """Test listing workflows when none exist."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows"
    ).mock(return_value=httpx.Response(200, json={"workflows": []}))

    workflows = client.list_workflows("owner", "repo")

    assert workflows == []


@respx.mock
def test_list_workflows_pagination_truncation(client: GiteaClient):
    """Test truncation warning when workflows exceed max_pages."""
    route = respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows"
    )
    page_data = {
        "workflows": [
            {
                "id": f"workflow-{i}.yml",
                "name": f"Workflow {i}",
                "path": f".gitea/workflows/workflow-{i}.yml",
                "state": "active",
                "created_at": "",
                "updated_at": "",
            }
            for i in range(50)
        ]
    }
    route.side_effect = [
        httpx.Response(200, json=page_data),
        httpx.Response(200, json=page_data),  # Full page triggers next iteration
    ]

    with pytest.warns(UserWarning, match="Workflows list truncated at 2 pages"):
        client.list_workflows("owner", "repo", max_pages=2)


@respx.mock
def test_list_workflows_missing_key_raises(client: GiteaClient):
    """Test that missing 'workflows' key in dict response raises TypeError."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"other_key": []},  # Missing "workflows" key
        )
    )

    with pytest.raises(TypeError, match="dict missing 'workflows' key"):
        client.list_workflows("owner", "repo")


@respx.mock
def test_list_workflows_invalid_workflows_type_raises(client: GiteaClient):
    """Test that non-list 'workflows' value raises TypeError."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"workflows": "not-a-list"},  # Invalid type
        )
    )

    with pytest.raises(TypeError, match="Unexpected 'workflows' value type"):
        client.list_workflows("owner", "repo")


@respx.mock
def test_get_workflow(client: GiteaClient):
    """Test getting a workflow by ID."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "ci.yml",
                "name": "CI Pipeline",
                "path": ".gitea/workflows/ci.yml",
                "state": "active",
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-16T10:00:00Z",
            },
        )
    )

    workflow = client.get_workflow("owner", "repo", "ci.yml")

    assert workflow.id == "ci.yml"
    assert workflow.name == "CI Pipeline"
    assert workflow.state == "active"


@respx.mock
def test_get_workflow_not_found(client: GiteaClient):
    """Test 404 error when workflow not found."""
    respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/nonexistent.yml"
    ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.get_workflow("owner", "repo", "nonexistent.yml")

    assert exc_info.value.response.status_code == 404


@respx.mock
def test_dispatch_workflow(client: GiteaClient):
    """Test dispatching a workflow run."""
    route = respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml/dispatches"
    )
    route.mock(return_value=httpx.Response(204))

    client.dispatch_workflow("owner", "repo", "ci.yml", "main")

    assert route.called
    import json

    request_body = json.loads(route.calls.last.request.content)
    assert request_body == {"ref": "main"}


@respx.mock
def test_dispatch_workflow_with_inputs(client: GiteaClient):
    """Test dispatching a workflow with inputs."""
    route = respx.post(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/deploy.yml/dispatches"
    )
    route.mock(return_value=httpx.Response(204))

    inputs = {"version": "1.0.0", "environment": "production"}
    client.dispatch_workflow("owner", "repo", "deploy.yml", "v1.0.0", inputs)

    assert route.called
    import json

    request_body = json.loads(route.calls.last.request.content)
    assert request_body == {"ref": "v1.0.0", "inputs": inputs}


@respx.mock
def test_enable_workflow(client: GiteaClient):
    """Test enabling a workflow."""
    route = respx.put(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml/enable"
    )
    route.mock(return_value=httpx.Response(204))

    client.enable_workflow("owner", "repo", "ci.yml")

    assert route.called


@respx.mock
def test_disable_workflow(client: GiteaClient):
    """Test disabling a workflow."""
    route = respx.put(
        "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml/disable"
    )
    route.mock(return_value=httpx.Response(204))

    client.disable_workflow("owner", "repo", "ci.yml")

    assert route.called


@respx.mock
def test_workflow_id_path_encoding(client: GiteaClient):
    """Test that workflow_id with special characters is properly encoded."""
    # Use url__regex to match the encoded URL since respx URL comparison can be tricky
    route = respx.get(url__regex=r".*/actions/workflows/\.\.%2Fetc%2Fpasswd$")
    route.mock(return_value=httpx.Response(404, json={"message": "Not found"}))

    with pytest.raises(httpx.HTTPStatusError):
        client.get_workflow("owner", "repo", "../etc/passwd")

    assert route.called


# --- Workflow Run Operations Tests ---


@respx.mock
def test_list_runs(client: GiteaClient):
    """Test listing workflow runs."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "id": 1,
                        "run_number": 42,
                        "run_attempt": 1,
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "abc123",
                        "head_branch": "main",
                        "event": "push",
                        "display_title": "Test commit",
                        "path": ".github/workflows/ci.yml",
                        "started_at": "2024-01-01T00:00:00Z",
                        "completed_at": "2024-01-01T00:05:00Z",
                        "html_url": "https://example.com/runs/1",
                    }
                ]
            },
        )
    )

    runs = client.list_runs("owner", "repo")

    assert len(runs) == 1
    assert runs[0].id == 1
    assert runs[0].run_number == 42
    assert runs[0].conclusion == "success"
    assert runs[0].head_branch == "main"


@respx.mock
def test_list_runs_with_workflow_filter(client: GiteaClient):
    """Test listing runs with workflow filter."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "id": 1,
                        "run_number": 1,
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "abc",
                        "head_branch": "main",
                        "event": "push",
                        "path": ".github/workflows/ci.yml",
                    },
                    {
                        "id": 2,
                        "run_number": 2,
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "def",
                        "head_branch": "main",
                        "event": "push",
                        "path": ".github/workflows/deploy.yml",
                    },
                ]
            },
        )
    )

    runs = client.list_runs("owner", "repo", workflow="ci.yml")

    # Only ci.yml should be returned
    assert len(runs) == 1
    assert runs[0].path.endswith("ci.yml")


@respx.mock
def test_list_runs_with_workflow_filter_refs_suffix(client: GiteaClient):
    """Test listing runs with workflow filter when path has @refs suffix."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "id": 1,
                        "run_number": 1,
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "abc",
                        "head_branch": "main",
                        "event": "push",
                        # Gitea sometimes returns path with @refs/... suffix
                        "path": ".gitea/workflows/staging-deploy.yml@refs/heads/main",
                    },
                    {
                        "id": 2,
                        "run_number": 2,
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "def",
                        "head_branch": "main",
                        "event": "push",
                        "path": ".gitea/workflows/staging-verify.yml@refs/heads/main",
                    },
                ]
            },
        )
    )

    # Filter should match even with @refs suffix
    runs = client.list_runs("owner", "repo", workflow="staging-deploy.yml")

    assert len(runs) == 1
    assert "staging-deploy.yml" in runs[0].path


@respx.mock
def test_list_runs_empty(client: GiteaClient):
    """Test listing runs when none exist."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs")
    route.mock(return_value=httpx.Response(200, json={"workflow_runs": []}))

    runs = client.list_runs("owner", "repo")

    assert runs == []


@respx.mock
def test_list_runs_with_head_sha_filter(client: GiteaClient):
    """Test listing runs filtered by commit SHA."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "id": 42,
                        "run_number": 15,
                        "run_attempt": 1,
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "abc12345def67890",
                        "head_branch": "main",
                        "event": "push",
                        "display_title": "CI Run",
                        "path": ".gitea/workflows/ci.yml",
                        "started_at": "",
                        "completed_at": "",
                        "html_url": "",
                        "url": "",
                        "repository_id": 1,
                    },
                    {
                        "id": 41,
                        "run_number": 14,
                        "run_attempt": 1,
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "xyz99999abc11111",
                        "head_branch": "main",
                        "event": "push",
                        "display_title": "CI Run",
                        "path": ".gitea/workflows/ci.yml",
                        "started_at": "",
                        "completed_at": "",
                        "html_url": "",
                        "url": "",
                        "repository_id": 1,
                    },
                ]
            },
        )
    )

    # Filter by SHA prefix should only return matching run
    runs = client.list_runs("owner", "repo", head_sha="abc123")

    assert len(runs) == 1
    assert runs[0].id == 42
    assert runs[0].head_sha.startswith("abc123")


@respx.mock
def test_list_run_jobs(client: GiteaClient):
    """Test listing jobs for a run."""
    route = respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
    )
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 100,
                        "run_id": 42,
                        "name": "build",
                        "status": "completed",
                        "conclusion": "success",
                        "started_at": "2024-01-01T00:00:00Z",
                        "completed_at": "2024-01-01T00:02:00Z",
                        "steps": [
                            {
                                "number": 1,
                                "name": "Checkout",
                                "status": "completed",
                                "conclusion": "success",
                            },
                            {
                                "number": 2,
                                "name": "Build",
                                "status": "completed",
                                "conclusion": "success",
                            },
                        ],
                    }
                ]
            },
        )
    )

    jobs = client.list_run_jobs("owner", "repo", 42)

    assert len(jobs) == 1
    assert jobs[0].id == 100
    assert jobs[0].name == "build"
    assert len(jobs[0].steps) == 2


@respx.mock
def test_get_job(client: GiteaClient):
    """Test getting a single job."""
    route = respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/100"
    )
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 100,
                "run_id": 42,
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "steps": [
                    {
                        "number": 1,
                        "name": "Run tests",
                        "status": "completed",
                        "conclusion": "failure",
                    },
                ],
            },
        )
    )

    job = client.get_job("owner", "repo", 100)

    assert job.id == 100
    assert job.conclusion == "failure"


@respx.mock
def test_get_job_with_null_steps(client: GiteaClient):
    """Test that job with null steps is handled (API sometimes returns null)."""
    route = respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/100"
    )
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 100,
                "run_id": 42,
                "name": "test",
                "status": "in_progress",
                "conclusion": None,
                "steps": None,  # API returns null for running jobs
            },
        )
    )

    job = client.get_job("owner", "repo", 100)

    assert job.id == 100
    assert job.steps == []  # Normalized to empty list


@respx.mock
def test_get_job_with_missing_steps_key(client: GiteaClient):
    """Test that job with missing steps key defaults to empty list."""
    route = respx.get(
        "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/100"
    )
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 100,
                "run_id": 42,
                "name": "test",
                "status": "queued",
                "conclusion": None,
                # Note: "steps" key is completely missing
            },
        )
    )

    job = client.get_job("owner", "repo", 100)

    assert job.id == 100
    assert job.steps == []  # Default to empty list when key missing


@respx.mock
def test_get_job_logs(client: GiteaClient):
    """Test getting job logs."""
    url = "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/100/logs"
    route = respx.get(url)
    log_text = "Step 1: Checkout\nStep 2: Build\nError: Test failed"
    route.mock(return_value=httpx.Response(200, text=log_text))

    logs = client.get_job_logs("owner", "repo", 100)

    assert "Step 1: Checkout" in logs
    assert "Error: Test failed" in logs


@respx.mock
def test_delete_run(client: GiteaClient):
    """Test deleting a run."""
    route = respx.delete(
        "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42"
    )
    route.mock(return_value=httpx.Response(204))

    client.delete_run("owner", "repo", 42)

    assert route.called


# --- Package Linking Tests ---


@respx.mock
def test_link_package(client: GiteaClient):
    """Test linking a package to a repository."""
    route = respx.post(
        url__regex=r".*/api/packages/homelab/container/myimage/-/link/myrepo$"
    )
    route.mock(return_value=httpx.Response(200))

    client.link_package("homelab", "container", "myimage", "myrepo")

    assert route.called


@respx.mock
def test_unlink_package(client: GiteaClient):
    """Test unlinking a package from a repository."""
    route = respx.post(
        url__regex=r".*/api/packages/homelab/container/myimage/-/unlink$"
    )
    route.mock(return_value=httpx.Response(200))

    client.unlink_package("homelab", "container", "myimage")

    assert route.called


@respx.mock
def test_get_latest_package_version(client: GiteaClient):
    """Test getting the latest package version."""
    route = respx.get(url__regex=r".*/api/packages/homelab/pypi/teax/-/latest$")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "owner": {"id": 1, "login": "homelab"},
                "name": "teax",
                "type": "pypi",
                "version": "1.0.0",
                "created_at": "2024-01-01T00:00:00Z",
            },
        )
    )

    pkg = client.get_latest_package_version("homelab", "pypi", "teax")

    assert pkg.name == "teax"
    assert pkg.version == "1.0.0"


# --- list_issues Tests ---


@respx.mock
def test_list_issues_basic(client: GiteaClient):
    """Test basic issue listing."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/issues")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "number": 1,
                    "title": "First issue",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
                {
                    "id": 2,
                    "number": 2,
                    "title": "Second issue",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            ],
        )
    )

    issues = client.list_issues("owner", "repo")

    assert len(issues) == 2
    assert issues[0].number == 1
    assert issues[1].number == 2


@respx.mock
def test_list_issues_with_filters(client: GiteaClient):
    """Test issue listing with filter parameters."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/issues")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "number": 1,
                    "title": "Ready issue",
                    "state": "open",
                    "labels": [{"id": 1, "name": "ready", "color": "00ff00"}],
                    "assignees": [],
                    "milestone": None,
                },
            ],
        )
    )

    issues = client.list_issues(
        "owner",
        "repo",
        state="open",
        labels=["ready"],
        assignee="testuser",
    )

    assert len(issues) == 1
    assert issues[0].title == "Ready issue"
    # Verify params were passed
    request = route.calls[0].request
    assert "state=open" in str(request.url)
    assert "labels=ready" in str(request.url)
    assert "assignee=testuser" in str(request.url)


@respx.mock
def test_list_issues_pagination(client: GiteaClient):
    """Test issue listing with pagination."""
    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/issues")
    # Page 1: 50 issues
    page1 = [
        {
            "id": i,
            "number": i,
            "title": f"Issue {i}",
            "state": "open",
            "labels": [],
            "assignees": [],
            "milestone": None,
        }
        for i in range(1, 51)
    ]
    # Page 2: 10 issues (less than limit, signals end)
    page2 = [
        {
            "id": i,
            "number": i,
            "title": f"Issue {i}",
            "state": "open",
            "labels": [],
            "assignees": [],
            "milestone": None,
        }
        for i in range(51, 61)
    ]
    route.side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ]

    issues = client.list_issues("owner", "repo")

    assert len(issues) == 60
    assert route.call_count == 2


@respx.mock
def test_list_issues_pagination_truncation(client: GiteaClient):
    """Test that list_issues emits warning when truncated."""
    import warnings

    route = respx.get("https://test.example.com/api/v1/repos/owner/repo/issues")
    # Always return full page (50 items)
    full_page = [
        {
            "id": i,
            "number": i,
            "title": f"Issue {i}",
            "state": "open",
            "labels": [],
            "assignees": [],
            "milestone": None,
        }
        for i in range(1, 51)
    ]
    route.side_effect = [httpx.Response(200, json=full_page)] * 3

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        issues = client.list_issues("owner", "repo", max_pages=2)

        assert len(issues) == 100  # 50 * 2 pages
        assert len(w) == 1
        assert "truncated" in str(w[0].message).lower()


# --- ensure_label Tests ---


@respx.mock
def test_ensure_label_creates_new(client: GiteaClient):
    """Test ensure_label creates label when it doesn't exist."""
    # First call: create succeeds
    create_route = respx.post("https://test.example.com/api/v1/repos/owner/repo/labels")
    create_route.mock(
        return_value=httpx.Response(
            201,
            json={"id": 42, "name": "sprint/28", "color": "1d76db"},
        )
    )

    label, was_created = client.ensure_label("owner", "repo", "sprint/28")

    assert label.name == "sprint/28"
    assert was_created is True


@respx.mock
def test_ensure_label_already_exists(client: GiteaClient):
    """Test ensure_label returns existing label on 409 conflict."""
    # Create fails with 409
    create_route = respx.post("https://test.example.com/api/v1/repos/owner/repo/labels")
    create_route.mock(return_value=httpx.Response(409))

    # List labels returns existing label
    list_route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    list_route.mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 42, "name": "sprint/28", "color": "1d76db"}],
        )
    )

    label, was_created = client.ensure_label("owner", "repo", "sprint/28")

    assert label.name == "sprint/28"
    assert was_created is False


@respx.mock
def test_ensure_label_from_cache(client: GiteaClient):
    """Test ensure_label uses cache when label already known."""
    # Populate cache by listing labels
    list_route = respx.get("https://test.example.com/api/v1/repos/owner/repo/labels")
    list_route.mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 42, "name": "sprint/28", "color": "1d76db"}],
        )
    )

    # First call populates cache
    client.list_repo_labels("owner", "repo")

    # ensure_label should find it in cache
    label, was_created = client.ensure_label("owner", "repo", "sprint/28")

    assert label.name == "sprint/28"
    assert was_created is False
    # Should have called list twice (once for initial, once for ensure_label)
    assert list_route.call_count == 2


# --- Access Token Tests ---


@respx.mock
def test_create_access_token(client: GiteaClient):
    """Test creating an access token."""
    route = respx.post("https://test.example.com/api/v1/users/testuser/tokens")
    route.mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 42,
                "name": "my-ci-token",
                "sha1": "abc123def456",
                "token_last_eight": "def456",
                "scopes": ["write:repository", "write:package"],
            },
        )
    )

    token = client.create_access_token(
        username="testuser",
        password="mypassword",
        name="my-ci-token",
        scopes=["write:repository", "write:package"],
    )

    assert route.called
    assert token.id == 42
    assert token.name == "my-ci-token"
    assert token.sha1 == "abc123def456"
    assert token.scopes == ["write:repository", "write:package"]

    # Verify Basic auth header was sent
    import base64

    request = route.calls[0].request
    auth_header = request.headers["Authorization"]
    expected = base64.b64encode(b"testuser:mypassword").decode()
    assert auth_header == f"Basic {expected}"


@respx.mock
def test_create_access_token_no_scopes(client: GiteaClient):
    """Test creating an access token without scopes (all permissions)."""
    route = respx.post("https://test.example.com/api/v1/users/testuser/tokens")
    route.mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 43,
                "name": "full-access",
                "sha1": "xyz789",
                "token_last_eight": "xyz789",
                "scopes": [],
            },
        )
    )

    token = client.create_access_token(
        username="testuser",
        password="mypassword",
        name="full-access",
    )

    assert token.id == 43
    assert token.name == "full-access"
    assert token.sha1 == "xyz789"

    # Verify request body doesn't include scopes when not provided
    import json

    request_body = json.loads(route.calls[0].request.content)
    assert request_body == {"name": "full-access"}


@respx.mock
def test_create_access_token_auth_failure(client: GiteaClient):
    """Test 401 error when password is wrong."""
    route = respx.post("https://test.example.com/api/v1/users/testuser/tokens")
    route.mock(return_value=httpx.Response(401, json={"message": "Unauthorized"}))

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.create_access_token(
            username="testuser",
            password="wrongpassword",
            name="my-token",
        )

    assert exc_info.value.response.status_code == 401


@respx.mock
def test_create_access_token_name_exists(client: GiteaClient):
    """Test 422 error when token name already exists."""
    route = respx.post("https://test.example.com/api/v1/users/testuser/tokens")
    route.mock(
        return_value=httpx.Response(
            422,
            json={"message": "access token name has been used already"},
        )
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.create_access_token(
            username="testuser",
            password="mypassword",
            name="existing-token",
        )

    assert exc_info.value.response.status_code == 422


@respx.mock
def test_create_access_token_encodes_username(client: GiteaClient):
    """Test that username with special characters is properly encoded."""
    # Use regex to match the encoded URL
    route = respx.post(url__regex=r".*/users/user%2Fwith%2Fslash/tokens$")
    route.mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 1,
                "name": "token",
                "sha1": "abc",
                "scopes": [],
            },
        )
    )

    client.create_access_token(
        username="user/with/slash",
        password="pass",
        name="token",
    )

    assert route.called
