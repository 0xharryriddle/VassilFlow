"""Configuration facade for VassilFlow integrations."""

from deerflow.config.app_config import AppConfig, get_app_config, reload_app_config
from deerflow.config.env_aliases import env_value, first_env_value, vassilflow_alias_for
from deerflow.config.paths import Paths, get_paths
from deerflow.config.title_config import TitleConfig, get_title_config, set_title_config


def load_config(config_path: str | None = None) -> AppConfig:
    """Load a VassilFlow application config from disk.

    This is the VassilFlow-named convenience alias for the current
    ``reload_app_config`` implementation.
    """

    return reload_app_config(config_path)


__all__ = [
    "AppConfig",
    "Paths",
    "TitleConfig",
    "env_value",
    "first_env_value",
    "get_app_config",
    "get_paths",
    "get_title_config",
    "load_config",
    "reload_app_config",
    "set_title_config",
    "vassilflow_alias_for",
]
