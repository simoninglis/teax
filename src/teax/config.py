"""Read and parse tea CLI configuration."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from teax.models import TeaConfig, TeaLogin


def get_tea_config_path() -> Path:
    """Get the path to tea's config file."""
    return Path.home() / ".config" / "tea" / "config.yml"


def load_tea_config(config_path: Path | None = None) -> TeaConfig:
    """Load tea configuration from YAML file.

    Args:
        config_path: Optional custom config path. Defaults to ~/.config/tea/config.yml

    Returns:
        Parsed tea configuration

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    path = config_path or get_tea_config_path()

    if not path.exists():
        raise FileNotFoundError(
            f"tea config not found at {path}. "
            "Please configure tea first: tea login add"
        )

    try:
        with path.open(encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in tea config: {e}") from e

    if raw_config is None:
        return TeaConfig()

    try:
        return TeaConfig.model_validate(raw_config)
    except ValidationError as e:
        raise ValueError(f"Invalid tea config format: {e}") from e


def get_default_login(config: TeaConfig | None = None) -> TeaLogin:
    """Get the default tea login.

    Args:
        config: Optional pre-loaded config. Loads from file if not provided.

    Returns:
        The default login configuration

    Raises:
        ValueError: If no logins configured or no default set
    """
    if config is None:
        config = load_tea_config()

    if not config.logins:
        raise ValueError(
            "No tea logins configured. Please add one: tea login add"
        )

    # Find default login
    for login in config.logins:
        if login.default:
            return login

    # Fall back to first login
    return config.logins[0]


def get_login_by_name(name: str, config: TeaConfig | None = None) -> TeaLogin:
    """Get a specific tea login by name.

    Args:
        name: The login name to find
        config: Optional pre-loaded config

    Returns:
        The matching login configuration

    Raises:
        ValueError: If login not found
    """
    if config is None:
        config = load_tea_config()

    for login in config.logins:
        if login.name == name:
            return login

    available = [login.name for login in config.logins]
    raise ValueError(
        f"Login '{name}' not found. Available: {', '.join(available)}"
    )
