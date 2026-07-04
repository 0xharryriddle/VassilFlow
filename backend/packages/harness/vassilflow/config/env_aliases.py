"""Environment variable helpers for VassilFlow."""

from __future__ import annotations

import os
from collections.abc import Iterable


def vassilflow_alias_for(name: str) -> str | None:
    """Return a product alias for an environment variable name, if any."""
    return None


def legacy_names_for_vassilflow(name: str) -> tuple[str, ...]:
    """Return legacy names for a VassilFlow environment variable.

    VassilFlow is standalone and does not read upstream environment names.
    """
    return ()


def env_value(name: str, default: str | None = None) -> str | None:
    """Read an environment variable by its exact name."""
    return os.environ.get(name, default)


def first_env_value(names: Iterable[str], default: str | None = None) -> str | None:
    """Return the first configured exact env value."""
    for name in names:
        value = env_value(name)
        if value is not None:
            return value
    return default
