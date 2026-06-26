"""Configuration facade for VassilFlow integrations."""

from __future__ import annotations

from importlib import import_module

_app_config_impl = import_module("deerflow.config.app_config")
_env_aliases_impl = import_module("deerflow.config.env_aliases")
_paths_impl = import_module("deerflow.config.paths")
_title_config_impl = import_module("deerflow.config.title_config")

AppConfig = _app_config_impl.AppConfig
Paths = _paths_impl.Paths
TitleConfig = _title_config_impl.TitleConfig
env_value = _env_aliases_impl.env_value
first_env_value = _env_aliases_impl.first_env_value
get_app_config = _app_config_impl.get_app_config
get_paths = _paths_impl.get_paths
get_title_config = _title_config_impl.get_title_config
reload_app_config = _app_config_impl.reload_app_config
set_title_config = _title_config_impl.set_title_config
vassilflow_alias_for = _env_aliases_impl.vassilflow_alias_for


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
