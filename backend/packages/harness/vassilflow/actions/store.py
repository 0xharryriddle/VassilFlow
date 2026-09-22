"""Append-only, user-scoped storage for action provenance records."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, cast
from uuid import uuid4

from .models import (
    ACTION_LEASE_SCHEMA,
    ACTION_OUTCOME_SCHEMA,
    ACTION_REPAIR_CLAIM_SCHEMA,
    ACTION_SCHEMA,
    ACTION_SOURCES,
    ACTION_START_SCHEMA,
    ACTION_STATUSES,
    ACTION_TERMINAL_STATUSES,
    ActionSource,
    ActionStatus,
)

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows-only branch
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX-only branch
    msvcrt = None

logger = logging.getLogger(__name__)

_ACTION_ID_RE = re.compile(r"^act_[0-9a-f]{32}$")
_ACTION_LEASE_ID_RE = re.compile(r"^acl_[0-9a-f]{32}$")
_ACTION_REPAIR_CLAIM_ID_RE = re.compile(r"^arc_[0-9a-f]{32}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_REFERENCE_KIND_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_OWNER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_MAX_DOCUMENT_BYTES = 128 * 1024
_MAX_METADATA_BYTES = 32 * 1024
_MAX_REFERENCES = 100
_MAX_REFERENCE_VALUE_LENGTH = 512
_MAX_ERROR_MESSAGE_LENGTH = 2_000
_MAX_LIST_LIMIT = _MAX_SCAN_ENTRIES = 10_000
_DEFAULT_LEASE_DURATION = timedelta(minutes=30)
_DEFAULT_REPAIR_CLAIM_DURATION = timedelta(minutes=15)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class ActionStoreError(RuntimeError):
    """Base error for action contract persistence."""


class ActionNotFoundError(ActionStoreError):
    """Raised when an action does not exist in the current user's store."""


class ActionConflictError(ActionStoreError):
    """Raised when immutable action state would be replaced."""


class ActionIntegrityError(ActionStoreError):
    """Raised when persisted action data fails structural verification."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _bounded_text(
    value: str | None,
    *,
    field_name: str,
    maximum: int = _MAX_REFERENCE_VALUE_LENGTH,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ActionStoreError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise ActionStoreError(f"{field_name} is invalid")
    return normalized


def _validate_action_id(value: str) -> str:
    if not isinstance(value, str) or _ACTION_ID_RE.fullmatch(value) is None:
        raise ActionStoreError("Action ID is invalid")
    return value


def _validate_lease_id(value: str) -> str:
    if not isinstance(value, str) or _ACTION_LEASE_ID_RE.fullmatch(value) is None:
        raise ActionStoreError("Action lease ID is invalid")
    return value


def _validate_repair_claim_id(value: str) -> str:
    if not isinstance(value, str) or _ACTION_REPAIR_CLAIM_ID_RE.fullmatch(value) is None:
        raise ActionStoreError("Action repair claim ID is invalid")
    return value


def _normalize_owner_id(value: str) -> str:
    if not isinstance(value, str) or _OWNER_ID_RE.fullmatch(value) is None:
        raise ActionStoreError("Action owner ID is invalid")
    return value


def _normalize_operation(value: str) -> str:
    if not isinstance(value, str) or _OPERATION_RE.fullmatch(value) is None:
        raise ActionStoreError("Action operation is invalid")
    return value


def _normalize_reference(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ActionStoreError("Action reference must be an object")
    unknown = set(value) - {"kind", "id", "role"}
    if unknown:
        raise ActionStoreError("Action reference contains unsupported fields")
    kind = value.get("kind")
    if not isinstance(kind, str) or _REFERENCE_KIND_RE.fullmatch(kind) is None:
        raise ActionStoreError("Action reference kind is invalid")
    reference_id = _bounded_text(cast(str | None, value.get("id")), field_name="Action reference ID")
    if reference_id is None:
        raise ActionStoreError("Action reference ID is required")
    normalized = {"kind": kind, "id": reference_id}
    role = _bounded_text(cast(str | None, value.get("role")), field_name="Action reference role", maximum=64)
    if role is not None:
        normalized["role"] = role
    return normalized


def _normalize_references(
    values: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, str]]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ActionStoreError("Action references must be a list")
    if len(values) > _MAX_REFERENCES:
        raise ActionStoreError("Action references exceed the storage limit")
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for value in values:
        reference = _normalize_reference(value)
        identity = (reference["kind"], reference["id"], reference.get("role"))
        if identity not in seen:
            normalized.append(reference)
            seen.add(identity)
    return normalized


def _normalize_artifact(
    value: Mapping[str, Any] | None,
    *,
    field_name: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"sha256", "size_bytes"}:
        raise ActionStoreError(f"{field_name} must contain sha256 and size_bytes")
    sha256 = value.get("sha256")
    size_bytes = value.get("size_bytes")
    if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None or isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise ActionStoreError(f"{field_name} is invalid")
    return {"sha256": sha256, "size_bytes": size_bytes}


def _normalize_error(value: Mapping[str, Any] | None) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"type", "message"}:
        raise ActionStoreError("Action error must contain type and message")
    error_type = _bounded_text(
        cast(str | None, value.get("type")),
        field_name="Action error type",
        maximum=128,
    )
    message = _bounded_text(
        cast(str | None, value.get("message")),
        field_name="Action error message",
        maximum=_MAX_ERROR_MESSAGE_LENGTH,
    )
    if error_type is None or message is None:
        raise ActionStoreError("Action error is invalid")
    return {"type": error_type, "message": message}


def _normalize_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        raise ActionStoreError("Action metadata nesting exceeds the storage limit")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            raise ActionStoreError("Action metadata contains a non-finite number")
        return value
    if isinstance(value, list):
        if len(value) > 500:
            raise ActionStoreError("Action metadata list exceeds the storage limit")
        return [_normalize_json_value(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        if len(value) > 200:
            raise ActionStoreError("Action metadata object exceeds the storage limit")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128 or "\x00" in key:
                raise ActionStoreError("Action metadata key is invalid")
            normalized[key] = _normalize_json_value(item, depth=depth + 1)
        return normalized
    raise ActionStoreError("Action metadata must be JSON-compatible")


def _normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ActionStoreError("Action metadata must be an object")
    normalized = cast(dict[str, Any], _normalize_json_value(value))
    if len(_json_bytes(normalized, maximum=_MAX_METADATA_BYTES)) > _MAX_METADATA_BYTES:
        raise ActionStoreError("Action metadata exceeds the storage limit")
    return normalized


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value is not allowed: {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_bytes(payload: Mapping[str, Any], *, maximum: int = _MAX_DOCUMENT_BYTES) -> bytes:
    try:
        data = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ActionStoreError("Action metadata is not valid JSON") from exc
    if len(data) > maximum:
        raise ActionStoreError("Action metadata exceeds the storage limit")
    return data


def _read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ActionIntegrityError("Action metadata is missing or unsafe")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ActionIntegrityError("Action metadata could not be read") from exc
    if len(data) > _MAX_DOCUMENT_BYTES:
        raise ActionIntegrityError("Action metadata exceeds the storage limit")
    try:
        payload = json.loads(
            data,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ActionIntegrityError("Action metadata is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ActionIntegrityError("Action metadata must be a JSON object")
    return payload


def _write_bytes_exclusive(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        path.chmod(0o600)
    except FileExistsError as exc:
        raise ActionConflictError("Action attempted to replace immutable data") from exc


def _atomic_replace_json(path: Path, payload: Mapping[str, Any]) -> None:
    staging = path.parent / f".{path.name}.stage-{uuid4().hex}"
    try:
        _write_bytes_exclusive(staging, _json_bytes(payload))
        os.replace(staging, path)
        _sync_directory(path.parent)
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove staged Action coordination metadata",
                exc_info=True,
            )


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _lock_file_exclusive(lock_file: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return
    if msvcrt is None:  # pragma: no cover - unsupported interpreter platform
        raise ActionStoreError("Action locking is unavailable")
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
        os.fsync(lock_file.fileno())
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)


def _unlock_file(lock_file: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        return
    if msvcrt is None:  # pragma: no cover - unsupported interpreter platform
        return
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock(path):
        with path.open("a+b") as lock_file:
            locked = False
            try:
                _lock_file_exclusive(lock_file)
                locked = True
                yield
            finally:
                if locked:
                    _unlock_file(lock_file)


def _validate_start(payload: Mapping[str, Any], *, owner_user_id: str) -> dict[str, Any]:
    required = {
        "schema",
        "action_id",
        "owner_user_id",
        "operation",
        "source",
        "assistant_id",
        "thread_id",
        "run_id",
        "references",
        "started_at",
        "metadata",
    }
    if set(payload) != required or payload.get("schema") != ACTION_START_SCHEMA:
        raise ActionIntegrityError("Action start record has an invalid schema")
    try:
        action_id = _validate_action_id(cast(str, payload.get("action_id")))
        stored_owner = _normalize_owner_id(cast(str, payload.get("owner_user_id")))
        operation = _normalize_operation(cast(str, payload.get("operation")))
        source = cast(str, payload.get("source"))
        if source not in ACTION_SOURCES:
            raise ActionStoreError("Action source is invalid")
        assistant_id = _bounded_text(
            cast(str | None, payload.get("assistant_id")),
            field_name="Action assistant ID",
            maximum=128,
        )
        thread_id = _bounded_text(
            cast(str | None, payload.get("thread_id")),
            field_name="Action thread ID",
        )
        run_id = _bounded_text(
            cast(str | None, payload.get("run_id")),
            field_name="Action run ID",
        )
        references = _normalize_references(cast(list[Mapping[str, Any]], payload.get("references")))
        started_at = _bounded_text(
            cast(str | None, payload.get("started_at")),
            field_name="Action start timestamp",
            maximum=64,
        )
        metadata = _normalize_metadata(cast(Mapping[str, Any], payload.get("metadata")))
    except ActionStoreError as exc:
        raise ActionIntegrityError("Action start record failed validation") from exc
    if stored_owner != owner_user_id:
        raise ActionIntegrityError("Action owner does not match its user-scoped store")
    if started_at is None:
        raise ActionIntegrityError("Action start timestamp is missing")
    try:
        datetime.fromisoformat(started_at)
    except ValueError as exc:
        raise ActionIntegrityError("Action start timestamp is invalid") from exc
    if source == "agent_run":
        if assistant_id is None or thread_id is None or run_id is None:
            raise ActionIntegrityError("Agent action identity is incomplete")
    elif assistant_id is not None or thread_id is not None or run_id is not None:
        raise ActionIntegrityError("Direct user action cannot claim Agent run identity")
    return {
        "schema": ACTION_START_SCHEMA,
        "action_id": action_id,
        "owner_user_id": stored_owner,
        "operation": operation,
        "source": source,
        "assistant_id": assistant_id,
        "thread_id": thread_id,
        "run_id": run_id,
        "references": references,
        "started_at": started_at,
        "metadata": metadata,
    }


def _validate_outcome(
    payload: Mapping[str, Any],
    *,
    action_id: str,
) -> dict[str, Any]:
    required = {
        "schema",
        "action_id",
        "status",
        "completed_at",
        "references",
        "before_artifact",
        "after_artifact",
        "evidence",
        "error",
        "metadata",
    }
    if set(payload) != required or payload.get("schema") != ACTION_OUTCOME_SCHEMA:
        raise ActionIntegrityError("Action outcome record has an invalid schema")
    try:
        stored_action_id = _validate_action_id(cast(str, payload.get("action_id")))
        status = cast(str, payload.get("status"))
        if status not in ACTION_TERMINAL_STATUSES:
            raise ActionStoreError("Action outcome status is invalid")
        completed_at = _bounded_text(
            cast(str | None, payload.get("completed_at")),
            field_name="Action completion timestamp",
            maximum=64,
        )
        references = _normalize_references(cast(list[Mapping[str, Any]], payload.get("references")))
        before_artifact = _normalize_artifact(
            cast(Mapping[str, Any] | None, payload.get("before_artifact")),
            field_name="Action before artifact",
        )
        after_artifact = _normalize_artifact(
            cast(Mapping[str, Any] | None, payload.get("after_artifact")),
            field_name="Action after artifact",
        )
        evidence = _normalize_references(cast(list[Mapping[str, Any]], payload.get("evidence")))
        error = _normalize_error(cast(Mapping[str, Any] | None, payload.get("error")))
        metadata = _normalize_metadata(cast(Mapping[str, Any], payload.get("metadata")))
    except ActionStoreError as exc:
        raise ActionIntegrityError("Action outcome record failed validation") from exc
    if stored_action_id != action_id or completed_at is None:
        raise ActionIntegrityError("Action outcome identity is invalid")
    try:
        datetime.fromisoformat(completed_at)
    except ValueError as exc:
        raise ActionIntegrityError("Action completion timestamp is invalid") from exc
    if status in {"failed", "rejected", "partial"} and error is None:
        raise ActionIntegrityError("Unsuccessful action outcome requires an error")
    if status == "succeeded" and error is not None:
        raise ActionIntegrityError("Successful action outcome cannot contain an error")
    return {
        "schema": ACTION_OUTCOME_SCHEMA,
        "action_id": stored_action_id,
        "status": status,
        "completed_at": completed_at,
        "references": references,
        "before_artifact": before_artifact,
        "after_artifact": after_artifact,
        "evidence": evidence,
        "error": error,
        "metadata": metadata,
    }


def _parse_aware_timestamp(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ActionIntegrityError(f"{field_name} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ActionIntegrityError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ActionIntegrityError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _validate_lease(
    payload: Mapping[str, Any],
    *,
    action_id: str,
) -> dict[str, Any]:
    required = {
        "schema",
        "action_id",
        "lease_id",
        "renewed_at",
        "expires_at",
    }
    lease_id = payload.get("lease_id")
    if set(payload) != required or payload.get("schema") != ACTION_LEASE_SCHEMA or payload.get("action_id") != action_id or not isinstance(lease_id, str) or _ACTION_LEASE_ID_RE.fullmatch(lease_id) is None:
        raise ActionIntegrityError("Action lease record is invalid")
    renewed_at = _parse_aware_timestamp(
        payload.get("renewed_at"),
        field_name="Action lease renewal timestamp",
    )
    expires_at = _parse_aware_timestamp(
        payload.get("expires_at"),
        field_name="Action lease expiry timestamp",
    )
    if expires_at <= renewed_at:
        raise ActionIntegrityError("Action lease expiry is invalid")
    return dict(payload)


def _validate_repair_claim(
    payload: Mapping[str, Any],
    *,
    action_id: str,
) -> dict[str, Any]:
    required = {
        "schema",
        "action_id",
        "claim_id",
        "claimed_at",
        "expires_at",
    }
    claim_id = payload.get("claim_id")
    if set(payload) != required or payload.get("schema") != ACTION_REPAIR_CLAIM_SCHEMA or payload.get("action_id") != action_id or not isinstance(claim_id, str) or _ACTION_REPAIR_CLAIM_ID_RE.fullmatch(claim_id) is None:
        raise ActionIntegrityError("Action repair claim is invalid")
    claimed_at = _parse_aware_timestamp(
        payload.get("claimed_at"),
        field_name="Action repair claim timestamp",
    )
    expires_at = _parse_aware_timestamp(
        payload.get("expires_at"),
        field_name="Action repair claim expiry timestamp",
    )
    if expires_at <= claimed_at:
        raise ActionIntegrityError("Action repair claim expiry is invalid")
    return dict(payload)


def _project_action(
    start: Mapping[str, Any],
    outcome: Mapping[str, Any] | None,
) -> dict[str, Any]:
    references = list(cast(list[dict[str, str]], start["references"]))
    seen = {(item["kind"], item["id"], item.get("role")) for item in references}
    if outcome is not None:
        for item in cast(list[dict[str, str]], outcome["references"]):
            identity = (item["kind"], item["id"], item.get("role"))
            if identity not in seen:
                references.append(item)
                seen.add(identity)
    return {
        "schema": ACTION_SCHEMA,
        "action_id": start["action_id"],
        "owner_user_id": start["owner_user_id"],
        "operation": start["operation"],
        "source": start["source"],
        "assistant_id": start["assistant_id"],
        "thread_id": start["thread_id"],
        "run_id": start["run_id"],
        "started_at": start["started_at"],
        "completed_at": outcome["completed_at"] if outcome is not None else None,
        "status": outcome["status"] if outcome is not None else "running",
        "references": references,
        "before_artifact": outcome["before_artifact"] if outcome is not None else None,
        "after_artifact": outcome["after_artifact"] if outcome is not None else None,
        "evidence": outcome["evidence"] if outcome is not None else [],
        "error": outcome["error"] if outcome is not None else None,
        "metadata": {
            **cast(dict[str, Any], start["metadata"]),
            **(cast(dict[str, Any], outcome["metadata"]) if outcome is not None else {}),
        },
    }


class FileActionStore:
    """Persist immutable action starts and terminal outcomes under one user root."""

    def __init__(
        self,
        root: Path,
        *,
        owner_user_id: str,
        action_id_factory: Callable[[], str] | None = None,
        lease_id_factory: Callable[[], str] | None = None,
        repair_claim_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        lease_duration: timedelta = _DEFAULT_LEASE_DURATION,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ActionStoreError("Action lease duration is invalid")
        self.root = Path(root)
        self.owner_user_id = _normalize_owner_id(owner_user_id)
        self._action_id_factory = action_id_factory or (lambda: f"act_{uuid4().hex}")
        self._lease_id_factory = lease_id_factory or (lambda: f"acl_{uuid4().hex}")
        self._repair_claim_id_factory = repair_claim_id_factory or (lambda: f"arc_{uuid4().hex}")
        self._clock = clock or _utc_now
        self._lease_duration = lease_duration

    def _prepare_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ActionIntegrityError("Action store root is missing or unsafe")

    def _action_dir(self, action_id: str) -> Path:
        return self.root / _validate_action_id(action_id)

    def start(
        self,
        *,
        operation: str,
        source: ActionSource,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        references: Sequence[Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an action start record and return its running projection."""

        operation = _normalize_operation(operation)
        if source not in ACTION_SOURCES:
            raise ActionStoreError("Action source is invalid")
        assistant_id = _bounded_text(assistant_id, field_name="Action assistant ID", maximum=128)
        thread_id = _bounded_text(thread_id, field_name="Action thread ID")
        run_id = _bounded_text(run_id, field_name="Action run ID")
        if source == "agent_run":
            if assistant_id is None or thread_id is None or run_id is None:
                raise ActionStoreError("Agent action identity is incomplete")
        elif assistant_id is not None or thread_id is not None or run_id is not None:
            raise ActionStoreError("Direct user action cannot claim Agent run identity")
        normalized_references = _normalize_references(references)
        normalized_metadata = _normalize_metadata(metadata)
        self._prepare_root()

        with _exclusive_file_lock(self.root / ".actions.lock"):
            for _attempt in range(10):
                action_id = _validate_action_id(self._action_id_factory())
                action_dir = self._action_dir(action_id)
                if action_dir.exists() or action_dir.is_symlink():
                    continue
                staging = self.root / f".{action_id}.stage-{uuid4().hex}"
                now = self._clock()
                if now.tzinfo is None:
                    now = now.replace(tzinfo=UTC)
                now = now.astimezone(UTC)
                payload = {
                    "schema": ACTION_START_SCHEMA,
                    "action_id": action_id,
                    "owner_user_id": self.owner_user_id,
                    "operation": operation,
                    "source": source,
                    "assistant_id": assistant_id,
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "references": normalized_references,
                    "started_at": _timestamp(now),
                    "metadata": normalized_metadata,
                }
                lease = {
                    "schema": ACTION_LEASE_SCHEMA,
                    "action_id": action_id,
                    "lease_id": _validate_lease_id(self._lease_id_factory()),
                    "renewed_at": _timestamp(now),
                    "expires_at": _timestamp(now + self._lease_duration),
                }
                try:
                    staging.mkdir()
                    _write_bytes_exclusive(staging / "started.json", _json_bytes(payload))
                    _write_bytes_exclusive(
                        staging / "lease.json",
                        _json_bytes(lease),
                    )
                    os.replace(staging, action_dir)
                    _sync_directory(self.root)
                finally:
                    try:
                        (staging / "started.json").unlink(missing_ok=True)
                        (staging / "lease.json").unlink(missing_ok=True)
                        staging.rmdir()
                    except OSError:
                        if staging.exists():
                            logger.warning("Could not remove staged action metadata", exc_info=True)
                return _project_action(payload, None)
        raise ActionConflictError("Could not allocate a unique action ID")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _outcome_candidate(
        self,
        action_id: str,
        *,
        status: ActionStatus,
        references: Sequence[Mapping[str, Any]] | None,
        before_artifact: Mapping[str, Any] | None,
        after_artifact: Mapping[str, Any] | None,
        evidence: Sequence[Mapping[str, Any]] | None,
        error: Mapping[str, Any] | None,
        metadata: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if status not in ACTION_TERMINAL_STATUSES:
            raise ActionStoreError("Action outcome status is invalid")
        normalized_error = _normalize_error(error)
        if status in {"failed", "rejected", "partial"} and normalized_error is None:
            raise ActionStoreError("Unsuccessful action outcome requires an error")
        if status == "succeeded" and normalized_error is not None:
            raise ActionStoreError("Successful action outcome cannot contain an error")
        return {
            "schema": ACTION_OUTCOME_SCHEMA,
            "action_id": action_id,
            "status": status,
            "completed_at": _timestamp(self._now()),
            "references": _normalize_references(references),
            "before_artifact": _normalize_artifact(
                before_artifact,
                field_name="Action before artifact",
            ),
            "after_artifact": _normalize_artifact(
                after_artifact,
                field_name="Action after artifact",
            ),
            "evidence": _normalize_references(evidence),
            "error": normalized_error,
            "metadata": _normalize_metadata(metadata),
        }

    def _load_lease_unlocked(
        self,
        action_dir: Path,
        action_id: str,
    ) -> dict[str, Any] | None:
        path = action_dir / "lease.json"
        if not path.exists() and not path.is_symlink():
            return None
        return _validate_lease(
            _read_json_object(path),
            action_id=action_id,
        )

    def _load_repair_claim_unlocked(
        self,
        action_dir: Path,
        action_id: str,
    ) -> dict[str, Any] | None:
        path = action_dir / "repair_claim.json"
        if not path.exists() and not path.is_symlink():
            return None
        return _validate_repair_claim(
            _read_json_object(path),
            action_id=action_id,
        )

    def _existing_outcome_unlocked(
        self,
        action_dir: Path,
        action_id: str,
        start: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        outcome_path = action_dir / "outcome.json"
        if not outcome_path.exists() and not outcome_path.is_symlink():
            return None
        existing = _validate_outcome(
            _read_json_object(outcome_path),
            action_id=action_id,
        )
        comparable_keys = set(candidate) - {"completed_at"}
        if all(existing[key] == candidate[key] for key in comparable_keys):
            return _project_action(start, existing)
        raise ActionConflictError("Action already has a different terminal outcome")

    def _append_outcome_unlocked(
        self,
        action_dir: Path,
        start: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        outcome_path = action_dir / "outcome.json"
        staging = action_dir / f".outcome.stage-{uuid4().hex}"
        try:
            _write_bytes_exclusive(staging, _json_bytes(candidate))
            os.replace(staging, outcome_path)
            (action_dir / "lease.json").unlink(missing_ok=True)
            (action_dir / "repair_claim.json").unlink(missing_ok=True)
            _sync_directory(action_dir)
        finally:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Could not remove staged action outcome",
                    exc_info=True,
                )
        return _project_action(start, candidate)

    def finish(
        self,
        action_id: str,
        *,
        status: ActionStatus,
        references: Sequence[Mapping[str, Any]] | None = None,
        before_artifact: Mapping[str, Any] | None = None,
        after_artifact: Mapping[str, Any] | None = None,
        evidence: Sequence[Mapping[str, Any]] | None = None,
        error: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one terminal outcome unless repair owns the Action."""

        action_id = _validate_action_id(action_id)
        candidate = self._outcome_candidate(
            action_id,
            status=status,
            references=references,
            before_artifact=before_artifact,
            after_artifact=after_artifact,
            evidence=evidence,
            error=error,
            metadata=metadata,
        )
        self._prepare_root()
        action_dir = self._action_dir(action_id)
        with _exclusive_file_lock(self.root / ".actions.lock"):
            start = self._load_start(action_dir, action_id)
            existing = self._existing_outcome_unlocked(
                action_dir,
                action_id,
                start,
                candidate,
            )
            if existing is not None:
                return existing
            claim = self._load_repair_claim_unlocked(
                action_dir,
                action_id,
            )
            if claim is not None:
                expires_at = _parse_aware_timestamp(
                    claim["expires_at"],
                    field_name="Action repair claim expiry timestamp",
                )
                if expires_at > self._now():
                    raise ActionConflictError("Action outcome is owned by repair")
                (action_dir / "repair_claim.json").unlink(missing_ok=True)
            return self._append_outcome_unlocked(
                action_dir,
                start,
                candidate,
            )

    def renew(
        self,
        action_id: str,
        *,
        lease_duration: timedelta | None = None,
    ) -> dict[str, Any]:
        """Renew the worker lease while an Action is still executing."""

        action_id = _validate_action_id(action_id)
        duration = lease_duration or self._lease_duration
        if duration <= timedelta(0):
            raise ActionStoreError("Action lease duration is invalid")
        self._prepare_root()
        action_dir = self._action_dir(action_id)
        with _exclusive_file_lock(self.root / ".actions.lock"):
            self._load_start(action_dir, action_id)
            outcome_path = action_dir / "outcome.json"
            if outcome_path.exists() or outcome_path.is_symlink():
                return self.get(action_id)
            claim = self._load_repair_claim_unlocked(
                action_dir,
                action_id,
            )
            if (
                claim is not None
                and _parse_aware_timestamp(
                    claim["expires_at"],
                    field_name="Action repair claim expiry timestamp",
                )
                > self._now()
            ):
                raise ActionConflictError("Action lease cannot be renewed while repair owns it")
            current = self._load_lease_unlocked(
                action_dir,
                action_id,
            )
            now = self._now()
            lease = {
                "schema": ACTION_LEASE_SCHEMA,
                "action_id": action_id,
                "lease_id": (current["lease_id"] if current is not None else _validate_lease_id(self._lease_id_factory())),
                "renewed_at": _timestamp(now),
                "expires_at": _timestamp(now + duration),
            }
            _atomic_replace_json(action_dir / "lease.json", lease)
            return dict(lease)

    def _reconciliation_state_unlocked(
        self,
        action_dir: Path,
        action_id: str,
    ) -> str:
        self._load_start(action_dir, action_id)
        outcome_path = action_dir / "outcome.json"
        if outcome_path.exists() or outcome_path.is_symlink():
            return "terminal"
        now = self._now()
        lease = self._load_lease_unlocked(
            action_dir,
            action_id,
        )
        if (
            lease is not None
            and _parse_aware_timestamp(
                lease["expires_at"],
                field_name="Action lease expiry timestamp",
            )
            > now
        ):
            return "active"
        claim = self._load_repair_claim_unlocked(
            action_dir,
            action_id,
        )
        if (
            claim is not None
            and _parse_aware_timestamp(
                claim["expires_at"],
                field_name="Action repair claim expiry timestamp",
            )
            > now
        ):
            return "claimed"
        return "eligible"

    def inspect_reconciliation_state(self, action_id: str) -> str:
        """Read coordination state without creating a lock or directory."""

        action_id = _validate_action_id(action_id)
        return self._reconciliation_state_unlocked(
            self._action_dir(action_id),
            action_id,
        )

    def reconciliation_state(self, action_id: str) -> str:
        """Return terminal, active, claimed, or eligible under the store lock."""

        action_id = _validate_action_id(action_id)
        self._prepare_root()
        action_dir = self._action_dir(action_id)
        with _exclusive_file_lock(self.root / ".actions.lock"):
            return self._reconciliation_state_unlocked(
                action_dir,
                action_id,
            )

    def claim_reconciliation(
        self,
        action_id: str,
        *,
        claim_duration: timedelta = _DEFAULT_REPAIR_CLAIM_DURATION,
    ) -> str | None:
        """Atomically claim one expired running Action for repair."""

        action_id = _validate_action_id(action_id)
        if claim_duration <= timedelta(0):
            raise ActionStoreError("Action repair claim duration is invalid")
        self._prepare_root()
        action_dir = self._action_dir(action_id)
        with _exclusive_file_lock(self.root / ".actions.lock"):
            self._load_start(action_dir, action_id)
            outcome_path = action_dir / "outcome.json"
            if outcome_path.exists() or outcome_path.is_symlink():
                return None
            now = self._now()
            lease = self._load_lease_unlocked(
                action_dir,
                action_id,
            )
            if (
                lease is not None
                and _parse_aware_timestamp(
                    lease["expires_at"],
                    field_name="Action lease expiry timestamp",
                )
                > now
            ):
                return None
            claim_path = action_dir / "repair_claim.json"
            existing = self._load_repair_claim_unlocked(
                action_dir,
                action_id,
            )
            if (
                existing is not None
                and _parse_aware_timestamp(
                    existing["expires_at"],
                    field_name="Action repair claim expiry timestamp",
                )
                > now
            ):
                return None
            claim_id = _validate_repair_claim_id(self._repair_claim_id_factory())
            claim = {
                "schema": ACTION_REPAIR_CLAIM_SCHEMA,
                "action_id": action_id,
                "claim_id": claim_id,
                "claimed_at": _timestamp(now),
                "expires_at": _timestamp(now + claim_duration),
            }
            _atomic_replace_json(claim_path, claim)
            return claim_id

    def release_reconciliation(
        self,
        action_id: str,
        claim_id: str,
    ) -> None:
        """Release an unresolved repair claim without changing the Action."""

        action_id = _validate_action_id(action_id)
        claim_id = _validate_repair_claim_id(claim_id)
        action_dir = self._action_dir(action_id)
        with _exclusive_file_lock(self.root / ".actions.lock"):
            claim = self._load_repair_claim_unlocked(
                action_dir,
                action_id,
            )
            if claim is None:
                return
            if claim["claim_id"] != claim_id:
                raise ActionConflictError("Action repair claim is owned by another worker")
            (action_dir / "repair_claim.json").unlink(missing_ok=True)
            _sync_directory(action_dir)

    def finish_reconciliation(
        self,
        action_id: str,
        claim_id: str,
        *,
        status: ActionStatus,
        references: Sequence[Mapping[str, Any]] | None = None,
        before_artifact: Mapping[str, Any] | None = None,
        after_artifact: Mapping[str, Any] | None = None,
        evidence: Sequence[Mapping[str, Any]] | None = None,
        error: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a repaired outcome only for the current claim owner."""

        action_id = _validate_action_id(action_id)
        claim_id = _validate_repair_claim_id(claim_id)
        candidate = self._outcome_candidate(
            action_id,
            status=status,
            references=references,
            before_artifact=before_artifact,
            after_artifact=after_artifact,
            evidence=evidence,
            error=error,
            metadata=metadata,
        )
        self._prepare_root()
        action_dir = self._action_dir(action_id)
        with _exclusive_file_lock(self.root / ".actions.lock"):
            start = self._load_start(action_dir, action_id)
            existing = self._existing_outcome_unlocked(
                action_dir,
                action_id,
                start,
                candidate,
            )
            if existing is not None:
                return existing
            claim = self._load_repair_claim_unlocked(
                action_dir,
                action_id,
            )
            if claim is None or claim["claim_id"] != claim_id:
                raise ActionConflictError("Action repair claim is no longer owned")
            return self._append_outcome_unlocked(
                action_dir,
                start,
                candidate,
            )

    def _load_start(self, action_dir: Path, action_id: str) -> dict[str, Any]:
        if not action_dir.exists() and not action_dir.is_symlink():
            raise ActionNotFoundError("Action was not found")
        if action_dir.is_symlink() or not action_dir.is_dir():
            raise ActionIntegrityError("Action directory is unsafe")
        start = _validate_start(
            _read_json_object(action_dir / "started.json"),
            owner_user_id=self.owner_user_id,
        )
        if start["action_id"] != action_id:
            raise ActionIntegrityError("Action directory and record identities differ")
        return start

    def get(self, action_id: str) -> dict[str, Any]:
        """Load one verified action projection."""

        action_id = _validate_action_id(action_id)
        action_dir = self._action_dir(action_id)
        start = self._load_start(action_dir, action_id)
        outcome_path = action_dir / "outcome.json"
        if not outcome_path.exists() and not outcome_path.is_symlink():
            return _project_action(start, None)
        outcome = _validate_outcome(
            _read_json_object(outcome_path),
            action_id=action_id,
        )
        return _project_action(start, outcome)

    def list(
        self,
        *,
        limit: int = 100,
        operation: str | None = None,
        resource_kind: str | None = None,
        resource_id: str | None = None,
        status: ActionStatus | None = None,
        started_before: datetime | None = None,
        oldest_first: bool = False,
    ) -> list[dict[str, Any]]:
        """List newest verified actions with optional semantic filters."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIST_LIMIT:
            raise ActionStoreError("Action list limit is invalid")
        if operation is not None:
            operation = _normalize_operation(operation)
        if resource_kind is not None:
            if _REFERENCE_KIND_RE.fullmatch(resource_kind) is None:
                raise ActionStoreError("Action resource kind is invalid")
        resource_id = _bounded_text(resource_id, field_name="Action resource ID")
        if (resource_kind is None) != (resource_id is None):
            raise ActionStoreError("Action resource filters require kind and ID")
        if status is not None and status not in ACTION_STATUSES:
            raise ActionStoreError("Action status filter is invalid")
        if started_before is not None:
            if not isinstance(started_before, datetime):
                raise ActionStoreError("Action timestamp filter is invalid")
            if started_before.tzinfo is None:
                started_before = started_before.replace(tzinfo=UTC)
            started_before = started_before.astimezone(UTC)
        if not isinstance(oldest_first, bool):
            raise ActionStoreError("Action sort direction is invalid")
        if not self.root.exists():
            return []
        if self.root.is_symlink() or not self.root.is_dir():
            raise ActionIntegrityError("Action store root is unsafe")

        action_ids: list[str] = []
        for index, entry in enumerate(self.root.iterdir()):
            if index >= _MAX_SCAN_ENTRIES:
                raise ActionStoreError("Action store scan exceeds the safety limit")
            if _ACTION_ID_RE.fullmatch(entry.name) is not None:
                action_ids.append(entry.name)

        actions = [self.get(action_id) for action_id in action_ids]
        actions.sort(
            key=lambda item: (cast(str, item["started_at"]), cast(str, item["action_id"])),
            reverse=not oldest_first,
        )
        filtered: list[dict[str, Any]] = []
        for action in actions:
            if operation is not None and action["operation"] != operation:
                continue
            if status is not None and action["status"] != status:
                continue
            if started_before is not None:
                action_started_at = datetime.fromisoformat(cast(str, action["started_at"]))
                if action_started_at.tzinfo is None:
                    action_started_at = action_started_at.replace(tzinfo=UTC)
                if action_started_at.astimezone(UTC) > started_before:
                    continue
            if resource_kind is not None and not any(item["kind"] == resource_kind and item["id"] == resource_id for item in action["references"]):
                continue
            filtered.append(action)
            if len(filtered) >= limit:
                break
        return filtered
