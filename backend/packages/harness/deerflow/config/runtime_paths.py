"""Runtime path resolution for standalone harness usage."""

import os
from pathlib import Path

from deerflow.config.env_aliases import env_value

DEFAULT_RUNTIME_HOME_NAME = ".vassilflow"
LEGACY_RUNTIME_HOME_NAME = ".deer-flow"


def project_root() -> Path:
    """Return the caller project root for runtime-owned files."""
    if env_root := env_value("DEER_FLOW_PROJECT_ROOT"):
        root = Path(env_root).resolve()
        if not root.exists():
            raise ValueError(f"DEER_FLOW_PROJECT_ROOT/VASSILFLOW_PROJECT_ROOT is set to '{env_root}', but the resolved path '{root}' does not exist.")
        if not root.is_dir():
            raise ValueError(f"DEER_FLOW_PROJECT_ROOT/VASSILFLOW_PROJECT_ROOT is set to '{env_root}', but the resolved path '{root}' is not a directory.")
        return root
    return Path.cwd().resolve()


def default_runtime_home(root: Path | None = None) -> Path:
    """Return the default runtime home, preserving existing legacy state.

    Fresh VassilFlow workspaces use ``.vassilflow``. During the transition,
    workspaces that already have ``.deer-flow`` and no ``.vassilflow`` keep using
    the legacy directory so persisted DB/session/thread data is not orphaned by a
    default-name upgrade.
    """
    base = (root or project_root()).resolve()
    current = base / DEFAULT_RUNTIME_HOME_NAME
    legacy = base / LEGACY_RUNTIME_HOME_NAME

    if current.exists():
        return current
    if legacy.exists():
        return legacy
    return current


def runtime_home() -> Path:
    """Return the writable VassilFlow state directory."""
    if env_home := env_value("DEER_FLOW_HOME"):
        return Path(env_home).resolve()
    return default_runtime_home()


def resolve_path(value: str | os.PathLike[str], *, base: Path | None = None) -> Path:
    """Resolve absolute paths as-is and relative paths against the project root."""
    path = Path(value)
    if not path.is_absolute():
        path = (base or project_root()) / path
    return path.resolve()


def existing_project_file(names: tuple[str, ...]) -> Path | None:
    """Return the first existing named file under the project root."""
    root = project_root()
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None
