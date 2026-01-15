"""Tests for tea config parsing."""

from pathlib import Path
from textwrap import dedent

import pytest

from teax.config import get_default_login, get_login_by_name, load_tea_config
from teax.models import TeaConfig


@pytest.fixture
def sample_config(tmp_path: Path) -> Path:
    """Create a sample tea config file."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        dedent("""
        logins:
          - name: gitea.example.com
            url: https://gitea.example.com
            token: secret-token-123
            default: true
            user: testuser
          - name: backup.example.com
            url: https://backup.example.com
            token: backup-token
            default: false
            user: backupuser
        """).strip()
    )
    return config_path


@pytest.fixture
def empty_config(tmp_path: Path) -> Path:
    """Create an empty tea config file."""
    config_path = tmp_path / "config.yml"
    config_path.write_text("")
    return config_path


def test_load_tea_config(sample_config: Path):
    """Test loading a valid tea config."""
    config = load_tea_config(sample_config)

    assert isinstance(config, TeaConfig)
    assert len(config.logins) == 2
    assert config.logins[0].name == "gitea.example.com"
    assert config.logins[0].token.get_secret_value() == "secret-token-123"
    assert config.logins[0].default is True


def test_load_tea_config_not_found(tmp_path: Path):
    """Test loading from non-existent file."""
    with pytest.raises(FileNotFoundError, match="tea config not found"):
        load_tea_config(tmp_path / "nonexistent.yml")


def test_load_empty_config(empty_config: Path):
    """Test loading an empty config file."""
    config = load_tea_config(empty_config)
    assert config.logins == []


def test_get_default_login(sample_config: Path):
    """Test getting the default login."""
    config = load_tea_config(sample_config)
    login = get_default_login(config)

    assert login.name == "gitea.example.com"
    assert login.default is True


def test_get_default_login_fallback(tmp_path: Path):
    """Test fallback to first login when no default set."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        dedent("""
        logins:
          - name: first.example.com
            url: https://first.example.com
            token: token1
            user: user1
          - name: second.example.com
            url: https://second.example.com
            token: token2
            user: user2
        """).strip()
    )
    config = load_tea_config(config_path)
    login = get_default_login(config)

    assert login.name == "first.example.com"


def test_get_default_login_no_logins():
    """Test error when no logins configured."""
    config = TeaConfig(logins=[])
    with pytest.raises(ValueError, match="No tea logins configured"):
        get_default_login(config)


def test_get_login_by_name(sample_config: Path):
    """Test getting a specific login by name."""
    config = load_tea_config(sample_config)
    login = get_login_by_name("backup.example.com", config)

    assert login.name == "backup.example.com"
    assert login.token.get_secret_value() == "backup-token"
    assert login.user == "backupuser"


def test_get_login_by_name_not_found(sample_config: Path):
    """Test error when login name not found."""
    config = load_tea_config(sample_config)
    with pytest.raises(ValueError, match="Login 'nonexistent' not found"):
        get_login_by_name("nonexistent", config)


def test_token_not_exposed_in_repr(sample_config: Path):
    """Test that SecretStr token is not visible in repr/str output."""
    config = load_tea_config(sample_config)
    login = config.logins[0]

    # Token should be masked in repr output
    repr_str = repr(login)
    assert "secret-token-123" not in repr_str
    assert "**********" in repr_str  # Pydantic's SecretStr masking

    # Can still access the actual value when needed
    assert login.token.get_secret_value() == "secret-token-123"


# --- Config error handling tests ---


def test_load_invalid_yaml(tmp_path: Path):
    """Test loading a file with invalid YAML."""
    config_path = tmp_path / "config.yml"
    config_path.write_text("invalid: yaml: content: [unclosed")

    with pytest.raises(ValueError, match="Invalid YAML in tea config"):
        load_tea_config(config_path)


def test_load_invalid_schema(tmp_path: Path):
    """Test loading a file with invalid schema."""
    config_path = tmp_path / "config.yml"
    # logins should be a list, not a dict
    config_path.write_text(
        dedent("""
        logins:
          invalid_key: not_a_list
        """).strip()
    )

    with pytest.raises(ValueError, match="Invalid tea config format"):
        load_tea_config(config_path)


def test_load_permission_denied(tmp_path: Path, monkeypatch):
    """Test loading when permission is denied."""
    config_path = tmp_path / "config.yml"
    config_path.write_text("logins: []")

    # Mock open to raise PermissionError
    original_open = Path.open

    def mock_open(self, *args, **kwargs):
        if self == config_path:
            raise PermissionError("Permission denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", mock_open)

    with pytest.raises(ValueError, match="Permission denied reading tea config"):
        load_tea_config(config_path)


def test_load_is_directory(tmp_path: Path):
    """Test loading when path is a directory."""
    dir_path = tmp_path / "config.yml"
    dir_path.mkdir()

    with pytest.raises(ValueError, match="Expected file but found directory"):
        load_tea_config(dir_path)


def test_load_other_os_error(tmp_path: Path, monkeypatch):
    """Test loading when other OS error occurs."""
    config_path = tmp_path / "config.yml"
    config_path.write_text("logins: []")

    # Mock open to raise a generic OSError
    original_open = Path.open

    def mock_open(self, *args, **kwargs):
        if self == config_path:
            err = OSError("Disk error")
            err.strerror = "Input/output error"
            raise err
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", mock_open)

    with pytest.raises(ValueError, match="Cannot read tea config.*Input/output error"):
        load_tea_config(config_path)
