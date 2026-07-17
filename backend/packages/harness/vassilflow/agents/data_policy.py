"""Pure helpers for enforcing Agent access to thread-scoped data."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from typing import Any

from vassilflow.config.agent_contract import AgentDataAccess

DATA_SCOPE_BY_DIRECTORY: dict[str, AgentDataAccess] = {
    "uploads": "thread_uploads",
    "workspace": "thread_workspace",
    "outputs": "thread_outputs",
}
ALL_DATA_SCOPES = frozenset(DATA_SCOPE_BY_DIRECTORY.values())
_VIRTUAL_ROOT = "/mnt/user-data"
_USER_DATA_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])/mnt/user-data(?P<suffix>(?:[/\\][^\s'\"`|;&<>]*)?)",
    re.IGNORECASE,
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[/\\]")
_PATH_ARGUMENT_KEYS = frozenset(
    {
        "command",
        "cwd",
        "destination_path",
        "directory",
        "file_path",
        "filepath",
        "filepaths",
        "image_path",
        "input_dir",
        "input_path",
        "output_dir",
        "output_path",
        "path",
        "paths",
        "source_path",
        "template_path",
    }
)
_OPAQUE_THREAD_DATA_KEYS = frozenset(
    {
        "parent_revision_id",
        "project_id",
        "revision_id",
    }
)


def _iter_policy_strings(
    value: Any,
    *,
    key: str | None = None,
):
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            normalized_key = str(child_key).lower()
            yield from _iter_policy_strings(child_value, key=normalized_key)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _iter_policy_strings(item, key=key)
        return
    if isinstance(value, str) and key in _PATH_ARGUMENT_KEYS:
        yield key, value.replace("\\", "/")


def _contains_opaque_thread_data_reference(value: Any) -> bool:
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if str(child_key).lower() in _OPAQUE_THREAD_DATA_KEYS and isinstance(child_value, str) and child_value.strip():
                return True
            if _contains_opaque_thread_data_reference(child_value):
                return True
    elif isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_opaque_thread_data_reference(item) for item in value)
    return False


def _scope_for_normalized_path(path: str) -> frozenset[AgentDataAccess]:
    normalized = posixpath.normpath(path)
    if normalized == _VIRTUAL_ROOT:
        return ALL_DATA_SCOPES
    if not normalized.startswith(f"{_VIRTUAL_ROOT}/"):
        return ALL_DATA_SCOPES
    directory = normalized[len(_VIRTUAL_ROOT) + 1 :].split("/", 1)[0].lower()
    scope = DATA_SCOPE_BY_DIRECTORY.get(directory)
    return frozenset({scope}) if scope is not None else ALL_DATA_SCOPES


def _relative_path_scopes(value: str, *, key: str) -> set[AgentDataAccess]:
    scopes: set[AgentDataAccess] = set()
    if key == "command" and value.strip():
        # Arbitrary shell code can construct paths dynamically, so argument
        # parsing cannot prove that it stays inside one mounted scope.
        return set(ALL_DATA_SCOPES)
    else:
        stripped = value.strip()
        if not stripped:
            return {"thread_workspace"}
        candidates = [stripped]

    for raw_candidate in candidates:
        candidate = raw_candidate.strip("()[]{}:,!")
        if "=" in candidate:
            option, possible_path = candidate.split("=", 1)
            if option.startswith("-") or option.isidentifier():
                candidate = possible_path
        candidate = candidate.strip("()[]{}:,!")
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered.startswith(("http://", "https://", "data:")):
            continue
        if lowered.startswith("file://"):
            candidate = candidate[7:]
        if candidate.startswith(_VIRTUAL_ROOT):
            scopes.update(_scope_for_normalized_path(candidate))
            continue
        if key == "command" and not (candidate.startswith((".", "/", "~", "$", "%")) or "/" in candidate or _WINDOWS_ABSOLUTE_PATH.match(candidate) or re.search(r"\.[A-Za-z0-9]{1,12}$", candidate)):
            continue
        if candidate.startswith(("/", "~", "$", "%")) or _WINDOWS_ABSOLUTE_PATH.match(candidate):
            scopes.update(ALL_DATA_SCOPES)
            continue
        resolved = posixpath.normpath(f"{_VIRTUAL_ROOT}/workspace/{candidate}")
        scopes.update(_scope_for_normalized_path(resolved))
    return scopes


def referenced_data_scopes(
    arguments: Mapping[str, Any],
) -> frozenset[AgentDataAccess]:
    """Resolve absolute and relative tool paths against the thread workspace."""

    scopes: set[AgentDataAccess] = set()
    if _contains_opaque_thread_data_reference(arguments):
        scopes.update(ALL_DATA_SCOPES)
    for key, value in _iter_policy_strings(arguments):
        for match in _USER_DATA_PATH.finditer(value):
            scopes.update(_scope_for_normalized_path(match.group(0)))
        scopes.update(_relative_path_scopes(value, key=key))
    return frozenset(scopes)
