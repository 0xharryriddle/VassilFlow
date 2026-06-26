"""Environment variable compatibility helpers for the VassilFlow transition."""

from __future__ import annotations

import os
from collections.abc import Iterable


def vassilflow_alias_for(name: str) -> str | None:
    """Return the VassilFlow alias for legacy DeerFlow environment names."""
    if name.startswith("DEER_FLOW_"):
        return f"VASSILFLOW_{name.removeprefix('DEER_FLOW_')}"
    if name.startswith("DEERFLOW_"):
        return f"VASSILFLOW_{name.removeprefix('DEERFLOW_')}"
    return None


def env_value(name: str, default: str | None = None) -> str | None:
    """Read an env var, preferring its ``VASSILFLOW_*`` alias when available."""
    alias = vassilflow_alias_for(name)
    if alias is not None:
        value = os.environ.get(alias)
        if value is not None:
            return value

    value = os.environ.get(name)
    if value is not None:
        return value
    return default


def first_env_value(names: Iterable[str], default: str | None = None) -> str | None:
    """Return the first configured env value, with VassilFlow aliases honored."""
    for name in names:
        value = env_value(name)
        if value is not None:
            return value
    return default
