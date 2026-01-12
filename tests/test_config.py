"""Tests for tea config parsing."""

from pathlib import Path
from textwrap import dedent

import pytest

from teax.config import get_default_login, load_tea_config
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
    assert config.logins[0].token == "secret-token-123"
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
