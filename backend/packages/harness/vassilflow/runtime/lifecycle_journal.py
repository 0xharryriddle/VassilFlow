"""Durable, user-scoped journal for domain lifecycle projections."""

from __future__ import annotations

import hashlib
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

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows-only branch
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX-only branch
    msvcrt = None

logger = logging.getLogger(__name__)

LIFECYCLE_EVENT_SCHEMA = "vassilflow.lifecycle.event.v1"
LIFECYCLE_SOURCE_PREPARE_SCHEMA = "vassilflow.lifecycle.source_prepare.v1"
LIFECYCLE_SOURCE_COMMIT_SCHEMA = "vassilflow.lifecycle.source_commit.v1"
LIFECYCLE_SOURCE_ABORT_SCHEMA = "vassilflow.lifecycle.source_abort.v1"
LIFECYCLE_ATTEMPT_START_SCHEMA = "vassilflow.lifecycle.attempt.start.v1"
LIFECYCLE_ATTEMPT_LEASE_SCHEMA = "vassilflow.lifecycle.attempt.lease.v1"
LIFECYCLE_ATTEMPT_OUTCOME_SCHEMA = "vassilflow.lifecycle.attempt.outcome.v1"

_OPERATION_ID_RE = re.compile(r"^lco_[0-9a-f]{32}$")
_ATTEMPT_ID_RE = re.compile(r"^lca_[0-9a-f]{32}$")
_HANDLER_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_OWNER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_EVENT_NAMES = frozenset({"thread_deleted", "thread_branched"})
_MAX_DOCUMENT_BYTES = 64 * 1024
_MAX_OPERATIONS = 10_000
_MAX_HANDLERS = 64
_MAX_ATTEMPTS_PER_HANDLER = 100
_MAX_LIST_LIMIT = _MAX_OPERATIONS
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class LifecycleJournalError(RuntimeError):
    """Base error for durable lifecycle projection state."""


class LifecycleJournalConflictError(LifecycleJournalError):
    """Raised when immutable lifecycle state would be replaced."""


class LifecycleJournalIntegrityError(LifecycleJournalError):
    """Raised when persisted lifecycle state fails verification."""


class LifecycleOperationNotFoundError(LifecycleJournalError):
    """Raised when a lifecycle operation does not exist."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise LifecycleJournalIntegrityError("Lifecycle timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise LifecycleJournalIntegrityError("Lifecycle timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise LifecycleJournalIntegrityError("Lifecycle timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _validate_owner_id(value: str) -> str:
    if not isinstance(value, str) or _OWNER_ID_RE.fullmatch(value) is None:
        raise LifecycleJournalError("Lifecycle owner ID is invalid")
    return value


def validate_lifecycle_handler_key(value: str) -> str:
    """Validate one stable, server-owned lifecycle handler key."""

    if not isinstance(value, str) or _HANDLER_KEY_RE.fullmatch(value) is None:
        raise LifecycleJournalError("Lifecycle handler key is invalid")
    return value


def _validate_operation_id(value: str) -> str:
    if not isinstance(value, str) or _OPERATION_ID_RE.fullmatch(value) is None:
        raise LifecycleJournalError("Lifecycle operation ID is invalid")
    return value


def _validate_attempt_id(value: str) -> str:
    if not isinstance(value, str) or _ATTEMPT_ID_RE.fullmatch(value) is None:
        raise LifecycleJournalError("Lifecycle attempt ID is invalid")
    return value


def _bounded_identity(value: Any, *, field_name: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise LifecycleJournalError(f"{field_name} is invalid")
    return value


def _normalize_event_payload(
    event_name: str,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    if event_name not in _EVENT_NAMES:
        raise LifecycleJournalError("Lifecycle event name is invalid")
    if not isinstance(payload, Mapping):
        raise LifecycleJournalError("Lifecycle event payload must be an object")
    if event_name == "thread_deleted":
        if set(payload) != {"thread_id"}:
            raise LifecycleJournalError("Deleted-thread lifecycle payload is invalid")
        return {
            "thread_id": _bounded_identity(
                payload.get("thread_id"),
                field_name="Lifecycle thread ID",
            )
        }

    required = {
        "source_thread_id",
        "target_thread_id",
        "assistant_id",
        "workspace_clone_mode",
    }
    if set(payload) != required:
        raise LifecycleJournalError("Branched-thread lifecycle payload is invalid")
    normalized = {
        "source_thread_id": _bounded_identity(
            payload.get("source_thread_id"),
            field_name="Lifecycle source thread ID",
        ),
        "target_thread_id": _bounded_identity(
            payload.get("target_thread_id"),
            field_name="Lifecycle target thread ID",
        ),
        "assistant_id": _bounded_identity(
            payload.get("assistant_id"),
            field_name="Lifecycle assistant ID",
            maximum=128,
        ),
        "workspace_clone_mode": _bounded_identity(
            payload.get("workspace_clone_mode"),
            field_name="Lifecycle workspace clone mode",
            maximum=64,
        ),
    }
    if normalized["source_thread_id"] == normalized["target_thread_id"]:
        raise LifecycleJournalError("Lifecycle branch identities must differ")
    return normalized


def _event_identity_payload(
    event_name: str,
    payload: Mapping[str, str],
) -> dict[str, str]:
    """Return stable source identities, excluding post-mutation observations."""

    if event_name == "thread_branched":
        return {
            "source_thread_id": payload["source_thread_id"],
            "target_thread_id": payload["target_thread_id"],
            "assistant_id": payload["assistant_id"],
        }
    return dict(payload)


def _normalize_handler_keys(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise LifecycleJournalError("Lifecycle handler keys must be a list")
    if len(values) > _MAX_HANDLERS:
        raise LifecycleJournalError("Lifecycle handler count exceeds the limit")
    normalized = [validate_lifecycle_handler_key(value) for value in values]
    if len(set(normalized)) != len(normalized):
        raise LifecycleJournalError("Lifecycle handler keys must be unique")
    return normalized


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        data = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LifecycleJournalError("Lifecycle metadata is not valid JSON") from exc
    if len(data) > _MAX_DOCUMENT_BYTES:
        raise LifecycleJournalError("Lifecycle metadata exceeds the storage limit")
    return data


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        data = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LifecycleJournalError("Lifecycle metadata is not valid JSON") from exc
    if len(data) > _MAX_DOCUMENT_BYTES:
        raise LifecycleJournalError("Lifecycle metadata exceeds the storage limit")
    return data


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value is not allowed: {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise LifecycleJournalIntegrityError("Lifecycle metadata is missing or unsafe")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LifecycleJournalIntegrityError("Lifecycle metadata could not be read") from exc
    if len(data) > _MAX_DOCUMENT_BYTES:
        raise LifecycleJournalIntegrityError("Lifecycle metadata exceeds the storage limit")
    try:
        payload = json.loads(
            data,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise LifecycleJournalIntegrityError("Lifecycle metadata is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise LifecycleJournalIntegrityError("Lifecycle metadata must be a JSON object")
    return payload


def _write_bytes_exclusive(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        path.chmod(0o600)
    except FileExistsError as exc:
        raise LifecycleJournalConflictError("Lifecycle operation attempted to replace immutable data") from exc


def _atomic_replace_json(path: Path, payload: Mapping[str, Any]) -> None:
    # Keep the sibling name shorter than the target for Windows paths that
    # are already close to MAX_PATH.
    staging = path.parent / f".{uuid4().hex[:8]}"
    try:
        _write_bytes_exclusive(staging, _json_bytes(payload))
        os.replace(staging, path)
        _sync_directory(path.parent)
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove staged lifecycle coordination metadata",
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
        raise LifecycleJournalError("Lifecycle journal locking is unavailable")
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


def _validate_event(
    payload: Mapping[str, Any],
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    required = {
        "schema",
        "operation_id",
        "owner_user_id",
        "event",
        "idempotency_sha256",
        "payload",
        "handlers",
        "created_at",
    }
    schema = payload.get("schema")
    if set(payload) != required or schema != LIFECYCLE_EVENT_SCHEMA:
        raise LifecycleJournalIntegrityError("Lifecycle event record has an invalid schema")
    try:
        operation_id = _validate_operation_id(cast(str, payload.get("operation_id")))
        stored_owner = _validate_owner_id(cast(str, payload.get("owner_user_id")))
        event_name = cast(str, payload.get("event"))
        event_payload = _normalize_event_payload(
            event_name,
            cast(Mapping[str, Any], payload.get("payload")),
        )
        handlers = _normalize_handler_keys(cast(Sequence[str], payload.get("handlers")))
    except LifecycleJournalError as exc:
        raise LifecycleJournalIntegrityError("Lifecycle event record failed validation") from exc
    digest = payload.get("idempotency_sha256")
    if stored_owner != owner_user_id or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise LifecycleJournalIntegrityError("Lifecycle event identity is invalid")
    created_at = cast(str, payload.get("created_at"))
    _parse_timestamp(created_at)
    expected_digests = {
        hashlib.sha256(
            _canonical_json_bytes(
                {
                    "owner_user_id": stored_owner,
                    "event": event_name,
                    "payload": identity_payload,
                }
            )
        ).hexdigest()
        for identity_payload in (
            event_payload,
            _event_identity_payload(event_name, event_payload),
        )
    }
    if digest not in expected_digests or operation_id != f"lco_{digest[:32]}":
        raise LifecycleJournalIntegrityError("Lifecycle idempotency identity is invalid")
    return {
        "schema": schema,
        "operation_id": operation_id,
        "owner_user_id": stored_owner,
        "event": event_name,
        "idempotency_sha256": digest,
        "payload": event_payload,
        "handlers": handlers,
        "created_at": created_at,
    }


def _validate_source_prepare(
    payload: Mapping[str, Any],
    *,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "schema",
        "operation_id",
        "prepared_at",
    }
    if set(payload) != required or payload.get("schema") != LIFECYCLE_SOURCE_PREPARE_SCHEMA or payload.get("operation_id") != event["operation_id"]:
        raise LifecycleJournalIntegrityError("Lifecycle source preparation is invalid")
    prepared_at = cast(str, payload.get("prepared_at"))
    _parse_timestamp(prepared_at)
    return {
        "schema": LIFECYCLE_SOURCE_PREPARE_SCHEMA,
        "operation_id": event["operation_id"],
        "prepared_at": prepared_at,
    }


def _validate_source_commit(
    payload: Mapping[str, Any],
    *,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "schema",
        "operation_id",
        "payload",
        "committed_at",
    }
    if set(payload) != required or payload.get("schema") != LIFECYCLE_SOURCE_COMMIT_SCHEMA or payload.get("operation_id") != event["operation_id"]:
        raise LifecycleJournalIntegrityError("Lifecycle source commit is invalid")
    try:
        committed_payload = _normalize_event_payload(
            cast(str, event["event"]),
            cast(Mapping[str, Any], payload.get("payload")),
        )
    except LifecycleJournalError as exc:
        raise LifecycleJournalIntegrityError("Lifecycle source commit payload is invalid") from exc
    if _event_identity_payload(
        cast(str, event["event"]),
        committed_payload,
    ) != _event_identity_payload(
        cast(str, event["event"]),
        cast(Mapping[str, str], event["payload"]),
    ):
        raise LifecycleJournalIntegrityError("Lifecycle source commit identity does not match its event")
    committed_at = cast(str, payload.get("committed_at"))
    _parse_timestamp(committed_at)
    return {
        "schema": LIFECYCLE_SOURCE_COMMIT_SCHEMA,
        "operation_id": event["operation_id"],
        "payload": committed_payload,
        "committed_at": committed_at,
    }


def _validate_source_abort(
    payload: Mapping[str, Any],
    *,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "schema",
        "operation_id",
        "aborted_at",
        "error_type",
    }
    error_type = payload.get("error_type")
    if set(payload) != required or payload.get("schema") != LIFECYCLE_SOURCE_ABORT_SCHEMA or payload.get("operation_id") != event["operation_id"] or not isinstance(error_type, str) or not error_type or len(error_type) > 128:
        raise LifecycleJournalIntegrityError("Lifecycle source abort is invalid")
    aborted_at = cast(str, payload.get("aborted_at"))
    _parse_timestamp(aborted_at)
    return {
        "schema": LIFECYCLE_SOURCE_ABORT_SCHEMA,
        "operation_id": event["operation_id"],
        "aborted_at": aborted_at,
        "error_type": error_type,
    }


def _validate_attempt_start(
    payload: Mapping[str, Any],
    *,
    operation_id: str,
    handler_key: str,
    attempt_id: str,
) -> dict[str, Any]:
    required = {
        "schema",
        "operation_id",
        "handler_key",
        "attempt_id",
        "started_at",
    }
    if set(payload) != required or payload.get("schema") != LIFECYCLE_ATTEMPT_START_SCHEMA or payload.get("operation_id") != operation_id or payload.get("handler_key") != handler_key or payload.get("attempt_id") != attempt_id:
        raise LifecycleJournalIntegrityError("Lifecycle attempt start is invalid")
    _parse_timestamp(payload.get("started_at"))
    return dict(payload)


def _validate_attempt_lease(
    payload: Mapping[str, Any],
    *,
    operation_id: str,
    handler_key: str,
    attempt_id: str,
) -> dict[str, Any]:
    required = {
        "schema",
        "operation_id",
        "handler_key",
        "attempt_id",
        "generation",
        "renewed_at",
        "expires_at",
    }
    generation = payload.get("generation")
    if (
        set(payload) != required
        or payload.get("schema") != LIFECYCLE_ATTEMPT_LEASE_SCHEMA
        or payload.get("operation_id") != operation_id
        or payload.get("handler_key") != handler_key
        or payload.get("attempt_id") != attempt_id
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or not 1 <= generation <= _MAX_ATTEMPTS_PER_HANDLER
    ):
        raise LifecycleJournalIntegrityError("Lifecycle attempt lease is invalid")
    renewed_at = _parse_timestamp(payload.get("renewed_at"))
    expires_at = _parse_timestamp(payload.get("expires_at"))
    if expires_at < renewed_at:
        raise LifecycleJournalIntegrityError("Lifecycle attempt lease expiry is invalid")
    return dict(payload)


def _validate_attempt_outcome(
    payload: Mapping[str, Any],
    *,
    operation_id: str,
    handler_key: str,
    attempt_id: str,
) -> dict[str, Any]:
    required = {
        "schema",
        "operation_id",
        "handler_key",
        "attempt_id",
        "status",
        "completed_at",
        "error_type",
    }
    status = payload.get("status")
    error_type = payload.get("error_type")
    if (
        set(payload) != required
        or payload.get("schema") != LIFECYCLE_ATTEMPT_OUTCOME_SCHEMA
        or payload.get("operation_id") != operation_id
        or payload.get("handler_key") != handler_key
        or payload.get("attempt_id") != attempt_id
        or status not in {"succeeded", "failed"}
        or (status == "succeeded" and error_type is not None)
        or (status == "failed" and (not isinstance(error_type, str) or not error_type or len(error_type) > 128))
    ):
        raise LifecycleJournalIntegrityError("Lifecycle attempt outcome is invalid")
    _parse_timestamp(payload.get("completed_at"))
    return dict(payload)


class FileThreadLifecycleJournal:
    """Persist immutable lifecycle events and per-handler attempts."""

    def __init__(
        self,
        root: Path,
        *,
        owner_user_id: str,
        clock: Callable[[], datetime] | None = None,
        attempt_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.owner_user_id = _validate_owner_id(owner_user_id)
        self._clock = clock or _utc_now
        self._attempt_id_factory = attempt_id_factory or (lambda: f"lca_{uuid4().hex}")

    def _prepare_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise LifecycleJournalIntegrityError("Lifecycle journal root is missing or unsafe")

    def _operation_dir(self, operation_id: str) -> Path:
        return self.root / _validate_operation_id(operation_id)

    def prepare(
        self,
        *,
        event_name: str,
        payload: Mapping[str, Any],
        handler_keys: Sequence[str],
    ) -> dict[str, Any]:
        """Create one idempotent source intent before the core mutation."""

        normalized_payload = _normalize_event_payload(event_name, payload)
        normalized_handlers = _normalize_handler_keys(handler_keys)
        digest = hashlib.sha256(
            _canonical_json_bytes(
                {
                    "owner_user_id": self.owner_user_id,
                    "event": event_name,
                    "payload": _event_identity_payload(
                        event_name,
                        normalized_payload,
                    ),
                }
            )
        ).hexdigest()
        operation_id = f"lco_{digest[:32]}"
        candidate = {
            "schema": LIFECYCLE_EVENT_SCHEMA,
            "operation_id": operation_id,
            "owner_user_id": self.owner_user_id,
            "event": event_name,
            "idempotency_sha256": digest,
            "payload": normalized_payload,
            "handlers": normalized_handlers,
            "created_at": _timestamp(self._clock()),
        }
        self._prepare_root()
        operation_dir = self._operation_dir(operation_id)
        with _exclusive_file_lock(self.root / ".lifecycle.lock"):
            if operation_dir.exists() or operation_dir.is_symlink():
                existing = self._load_event(operation_dir, operation_id)
                # A deployment may add a handler after this event was first
                # recorded. Existing operations retain their original fan-out.
                comparable = {
                    "schema",
                    "operation_id",
                    "owner_user_id",
                    "event",
                    "idempotency_sha256",
                }
                if all(existing[key] == candidate[key] for key in comparable) and _event_identity_payload(
                    event_name,
                    existing["payload"],
                ) == _event_identity_payload(
                    event_name,
                    normalized_payload,
                ):
                    return self.get(operation_id)
                raise LifecycleJournalConflictError("Lifecycle idempotency key conflicts with an existing event")
            staging = self.root / f".{operation_id}.stage-{uuid4().hex}"
            try:
                staging.mkdir()
                _write_bytes_exclusive(
                    staging / "event.json",
                    _json_bytes(candidate),
                )
                _write_bytes_exclusive(
                    staging / "source_prepared.json",
                    _json_bytes(
                        {
                            "schema": (LIFECYCLE_SOURCE_PREPARE_SCHEMA),
                            "operation_id": operation_id,
                            "prepared_at": candidate["created_at"],
                        }
                    ),
                )
                (staging / "attempts").mkdir()
                os.replace(staging, operation_dir)
                _sync_directory(self.root)
            finally:
                try:
                    (staging / "event.json").unlink(missing_ok=True)
                    (staging / "source_prepared.json").unlink(missing_ok=True)
                    (staging / "attempts").rmdir()
                    staging.rmdir()
                except OSError:
                    if staging.exists():
                        logger.warning(
                            "Could not remove staged lifecycle event",
                            exc_info=True,
                        )
        return self.get(operation_id)

    def record(
        self,
        *,
        event_name: str,
        payload: Mapping[str, Any],
        handler_keys: Sequence[str],
    ) -> dict[str, Any]:
        """Create and immediately commit an event for compatibility callers."""

        operation = self.prepare(
            event_name=event_name,
            payload=payload,
            handler_keys=handler_keys,
        )
        return self.commit_source(
            operation["operation_id"],
            payload=payload,
        )

    def commit_source(
        self,
        operation_id: str,
        *,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Publish the immutable source-mutation result before fan-out."""

        operation_id = _validate_operation_id(operation_id)
        operation_dir = self._operation_dir(operation_id)
        self._prepare_root()
        with _exclusive_file_lock(self.root / ".lifecycle.lock"):
            event = self._load_event(operation_dir, operation_id)
            normalized_payload = _normalize_event_payload(
                cast(str, event["event"]),
                payload,
            )
            candidate = {
                "schema": LIFECYCLE_SOURCE_COMMIT_SCHEMA,
                "operation_id": operation_id,
                "payload": normalized_payload,
                "committed_at": _timestamp(self._clock()),
            }
            abort_path = operation_dir / "source_aborted.json"
            if abort_path.exists() or abort_path.is_symlink():
                _validate_source_abort(
                    _read_json_object(abort_path),
                    event=event,
                )
                raise LifecycleJournalConflictError("Lifecycle source intent was already aborted")
            commit_path = operation_dir / "source_committed.json"
            if commit_path.exists() or commit_path.is_symlink():
                existing = _validate_source_commit(
                    _read_json_object(commit_path),
                    event=event,
                )
                if existing["payload"] == candidate["payload"]:
                    return self.get(operation_id)
                raise LifecycleJournalConflictError("Lifecycle source intent has a different committed payload")
            _validate_source_commit(candidate, event=event)
            _write_bytes_exclusive(commit_path, _json_bytes(candidate))
            _sync_directory(operation_dir)
        return self.get(operation_id)

    def abort_source(
        self,
        operation_id: str,
        *,
        error_type: str,
    ) -> dict[str, Any]:
        """Publish an immutable terminal marker when the source mutation fails."""

        operation_id = _validate_operation_id(operation_id)
        if not isinstance(error_type, str) or not error_type or len(error_type) > 128:
            raise LifecycleJournalError("Lifecycle source failure type is invalid")
        operation_dir = self._operation_dir(operation_id)
        self._prepare_root()
        with _exclusive_file_lock(self.root / ".lifecycle.lock"):
            event = self._load_event(operation_dir, operation_id)
            commit_path = operation_dir / "source_committed.json"
            if commit_path.exists() or commit_path.is_symlink():
                _validate_source_commit(
                    _read_json_object(commit_path),
                    event=event,
                )
                raise LifecycleJournalConflictError("Lifecycle source intent was already committed")
            candidate = {
                "schema": LIFECYCLE_SOURCE_ABORT_SCHEMA,
                "operation_id": operation_id,
                "aborted_at": _timestamp(self._clock()),
                "error_type": error_type,
            }
            abort_path = operation_dir / "source_aborted.json"
            if abort_path.exists() or abort_path.is_symlink():
                existing = _validate_source_abort(
                    _read_json_object(abort_path),
                    event=event,
                )
                if existing["error_type"] == candidate["error_type"]:
                    return self.get(operation_id)
                raise LifecycleJournalConflictError("Lifecycle source intent has a different abort outcome")
            _write_bytes_exclusive(abort_path, _json_bytes(candidate))
            _sync_directory(operation_dir)
        return self.get(operation_id)

    def _load_event(
        self,
        operation_dir: Path,
        operation_id: str,
    ) -> dict[str, Any]:
        if not operation_dir.exists() and not operation_dir.is_symlink():
            raise LifecycleOperationNotFoundError("Lifecycle operation was not found")
        if operation_dir.is_symlink() or not operation_dir.is_dir():
            raise LifecycleJournalIntegrityError("Lifecycle operation directory is unsafe")
        event = _validate_event(
            _read_json_object(operation_dir / "event.json"),
            owner_user_id=self.owner_user_id,
        )
        if event["operation_id"] != operation_id:
            raise LifecycleJournalIntegrityError("Lifecycle operation directory and record identities differ")
        return event

    def _attempts_for_handler(
        self,
        operation_dir: Path,
        *,
        operation_id: str,
        handler_key: str,
    ) -> list[dict[str, Any]]:
        handler_dir = operation_dir / "attempts" / handler_key
        if not handler_dir.exists() and not handler_dir.is_symlink():
            return []
        if handler_dir.is_symlink() or not handler_dir.is_dir():
            raise LifecycleJournalIntegrityError("Lifecycle handler attempt directory is unsafe")
        attempts: list[dict[str, Any]] = []
        for index, entry in enumerate(handler_dir.iterdir()):
            if index >= _MAX_ATTEMPTS_PER_HANDLER:
                raise LifecycleJournalIntegrityError("Lifecycle handler retry count exceeds the limit")
            attempt_id = _validate_attempt_id(entry.name)
            if entry.is_symlink() or not entry.is_dir():
                raise LifecycleJournalIntegrityError("Lifecycle attempt directory is unsafe")
            start = _validate_attempt_start(
                _read_json_object(entry / "started.json"),
                operation_id=operation_id,
                handler_key=handler_key,
                attempt_id=attempt_id,
            )
            lease_path = entry / "lease.json"
            lease = (
                _validate_attempt_lease(
                    _read_json_object(lease_path),
                    operation_id=operation_id,
                    handler_key=handler_key,
                    attempt_id=attempt_id,
                )
                if lease_path.exists() or lease_path.is_symlink()
                else None
            )
            if lease is not None and _parse_timestamp(lease["renewed_at"]) < _parse_timestamp(start["started_at"]):
                raise LifecycleJournalIntegrityError("Lifecycle attempt lease predates its start")
            outcome_path = entry / "outcome.json"
            outcome = (
                _validate_attempt_outcome(
                    _read_json_object(outcome_path),
                    operation_id=operation_id,
                    handler_key=handler_key,
                    attempt_id=attempt_id,
                )
                if outcome_path.exists() or outcome_path.is_symlink()
                else None
            )
            attempts.append(
                {
                    "attempt_id": attempt_id,
                    "started_at": start["started_at"],
                    "completed_at": (outcome["completed_at"] if outcome is not None else None),
                    "status": (outcome["status"] if outcome is not None else "running"),
                    "error_type": (outcome["error_type"] if outcome is not None else None),
                    "generation": (lease["generation"] if lease is not None else None),
                    "lease_renewed_at": (lease["renewed_at"] if lease is not None else None),
                    "lease_expires_at": (lease["expires_at"] if lease is not None else None),
                }
            )
        attempts.sort(
            key=lambda item: (
                cast(str, item["started_at"]),
                cast(str, item["attempt_id"]),
            )
        )
        leased_generations = [cast(int, attempt["generation"]) for attempt in attempts if attempt["generation"] is not None]
        if len(set(leased_generations)) != len(leased_generations):
            raise LifecycleJournalIntegrityError("Lifecycle attempt lease generations are duplicated")
        used_generations = set(leased_generations)
        next_generation = 1
        for attempt in attempts:
            if attempt["generation"] is not None:
                continue
            while next_generation in used_generations:
                next_generation += 1
            if next_generation > _MAX_ATTEMPTS_PER_HANDLER:
                raise LifecycleJournalIntegrityError("Lifecycle attempt generation exceeds the limit")
            attempt["generation"] = next_generation
            used_generations.add(next_generation)
            next_generation += 1
        attempts.sort(
            key=lambda item: (
                cast(int, item["generation"]),
                cast(str, item["started_at"]),
                cast(str, item["attempt_id"]),
            )
        )
        return attempts

    def _source_projection(
        self,
        operation_dir: Path,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        prepare_path = operation_dir / "source_prepared.json"
        commit_path = operation_dir / "source_committed.json"
        abort_path = operation_dir / "source_aborted.json"
        has_prepare = prepare_path.exists() or prepare_path.is_symlink()
        has_commit = commit_path.exists() or commit_path.is_symlink()
        has_abort = abort_path.exists() or abort_path.is_symlink()
        if has_commit and has_abort:
            raise LifecycleJournalIntegrityError("Lifecycle source intent has conflicting outcomes")
        if has_prepare:
            _validate_source_prepare(
                _read_json_object(prepare_path),
                event=event,
            )
        if has_commit:
            commit = _validate_source_commit(
                _read_json_object(commit_path),
                event=event,
            )
            return {
                "source_status": "committed",
                "source_committed_at": commit["committed_at"],
                "source_aborted_at": None,
                "source_error_type": None,
                "payload": commit["payload"],
            }
        if has_abort:
            abort = _validate_source_abort(
                _read_json_object(abort_path),
                event=event,
            )
            return {
                "source_status": "aborted",
                "source_committed_at": None,
                "source_aborted_at": abort["aborted_at"],
                "source_error_type": abort["error_type"],
                "payload": event["payload"],
            }
        if not has_prepare:
            return {
                "source_status": "committed",
                "source_committed_at": event["created_at"],
                "source_aborted_at": None,
                "source_error_type": None,
                "payload": event["payload"],
            }
        return {
            "source_status": "prepared",
            "source_committed_at": None,
            "source_aborted_at": None,
            "source_error_type": None,
            "payload": event["payload"],
        }

    def get(self, operation_id: str) -> dict[str, Any]:
        """Load one verified operation projection."""

        operation_id = _validate_operation_id(operation_id)
        operation_dir = self._operation_dir(operation_id)
        event = self._load_event(operation_dir, operation_id)
        source = self._source_projection(operation_dir, event)
        handlers: list[dict[str, Any]] = []
        for handler_key in event["handlers"]:
            attempts = self._attempts_for_handler(
                operation_dir,
                operation_id=operation_id,
                handler_key=handler_key,
            )
            if any(attempt["status"] == "succeeded" for attempt in attempts):
                status = "succeeded"
            elif not attempts:
                status = "pending"
            else:
                status = attempts[-1]["status"]
            handlers.append(
                {
                    "handler_key": handler_key,
                    "status": status,
                    "attempt_count": len(attempts),
                    "attempts": attempts,
                }
            )
        statuses = {handler["status"] for handler in handlers}
        if source["source_status"] == "prepared":
            status = "prepared"
        elif source["source_status"] == "aborted":
            status = "aborted"
        elif not handlers or statuses == {"succeeded"}:
            status = "succeeded"
        elif "running" in statuses:
            status = "running"
        elif "failed" in statuses:
            status = "failed"
        else:
            status = "pending"
        return {
            **event,
            **source,
            "status": status,
            "handler_states": handlers,
        }

    def begin_attempt(
        self,
        operation_id: str,
        handler_key: str,
        *,
        running_lease: timedelta,
    ) -> str | None:
        """Start a retry unless this handler succeeded or has a live attempt."""

        operation_id = _validate_operation_id(operation_id)
        handler_key = validate_lifecycle_handler_key(handler_key)
        if running_lease < timedelta(0):
            raise LifecycleJournalError("Lifecycle running-attempt lease is invalid")
        self._prepare_root()
        operation_dir = self._operation_dir(operation_id)
        with _exclusive_file_lock(self.root / ".lifecycle.lock"):
            event = self._load_event(operation_dir, operation_id)
            source = self._source_projection(operation_dir, event)
            if source["source_status"] != "committed":
                raise LifecycleJournalError("Lifecycle source intent is not committed")
            if handler_key not in event["handlers"]:
                raise LifecycleJournalError("Lifecycle handler is not registered for this event")
            attempts = self._attempts_for_handler(
                operation_dir,
                operation_id=operation_id,
                handler_key=handler_key,
            )
            if any(attempt["status"] == "succeeded" for attempt in attempts):
                return None
            if len(attempts) >= _MAX_ATTEMPTS_PER_HANDLER:
                raise LifecycleJournalError("Lifecycle handler retry count exceeds the limit")
            now = self._clock().astimezone(UTC)
            for attempt in attempts:
                if attempt["status"] != "running":
                    continue
                lease_expires_at = attempt["lease_expires_at"]
                if lease_expires_at is not None:
                    if _parse_timestamp(lease_expires_at) > now:
                        return None
                    continue
                started_at = _parse_timestamp(attempt["started_at"])
                if now - started_at < running_lease:
                    return None
            generation = max(cast(int, attempt["generation"]) for attempt in attempts) + 1 if attempts else 1
            if generation > _MAX_ATTEMPTS_PER_HANDLER:
                raise LifecycleJournalError("Lifecycle handler retry count exceeds the limit")
            for _attempt in range(16):
                attempt_id = _validate_attempt_id(self._attempt_id_factory())
                attempt_dir = operation_dir / "attempts" / handler_key / attempt_id
                if attempt_dir.exists() or attempt_dir.is_symlink():
                    continue
                attempt_dir.mkdir(parents=True)
                started_at = _timestamp(now)
                start = {
                    "schema": LIFECYCLE_ATTEMPT_START_SCHEMA,
                    "operation_id": operation_id,
                    "handler_key": handler_key,
                    "attempt_id": attempt_id,
                    "started_at": started_at,
                }
                lease = {
                    "schema": LIFECYCLE_ATTEMPT_LEASE_SCHEMA,
                    "operation_id": operation_id,
                    "handler_key": handler_key,
                    "attempt_id": attempt_id,
                    "generation": generation,
                    "renewed_at": started_at,
                    "expires_at": _timestamp(now + running_lease),
                }
                try:
                    _write_bytes_exclusive(
                        attempt_dir / "started.json",
                        _json_bytes(start),
                    )
                    _write_bytes_exclusive(
                        attempt_dir / "lease.json",
                        _json_bytes(lease),
                    )
                    _sync_directory(attempt_dir)
                except Exception:
                    try:
                        (attempt_dir / "lease.json").unlink(missing_ok=True)
                        (attempt_dir / "started.json").unlink(missing_ok=True)
                        attempt_dir.rmdir()
                    except OSError:
                        logger.warning(
                            "Could not remove incomplete lifecycle attempt",
                            exc_info=True,
                        )
                    raise
                return attempt_id
        raise LifecycleJournalConflictError("Could not allocate a unique lifecycle attempt ID")

    def renew_attempt(
        self,
        operation_id: str,
        handler_key: str,
        attempt_id: str,
        *,
        lease_duration: timedelta,
    ) -> dict[str, Any]:
        """Renew only the newest unresolved handler-attempt generation."""

        operation_id = _validate_operation_id(operation_id)
        handler_key = validate_lifecycle_handler_key(handler_key)
        attempt_id = _validate_attempt_id(attempt_id)
        if lease_duration <= timedelta(0):
            raise LifecycleJournalError("Lifecycle attempt lease duration is invalid")
        self._prepare_root()
        operation_dir = self._operation_dir(operation_id)
        with _exclusive_file_lock(self.root / ".lifecycle.lock"):
            event = self._load_event(operation_dir, operation_id)
            source = self._source_projection(operation_dir, event)
            if source["source_status"] != "committed":
                raise LifecycleJournalError("Lifecycle source intent is not committed")
            if handler_key not in event["handlers"]:
                raise LifecycleJournalError("Lifecycle handler is not registered for this event")
            attempts = self._attempts_for_handler(
                operation_dir,
                operation_id=operation_id,
                handler_key=handler_key,
            )
            current = next(
                (attempt for attempt in attempts if attempt["attempt_id"] == attempt_id),
                None,
            )
            if current is None:
                raise LifecycleJournalError("Lifecycle handler attempt was not found")
            newest_generation = max(cast(int, attempt["generation"]) for attempt in attempts)
            if current["status"] != "running" or cast(int, current["generation"]) != newest_generation or any(attempt["status"] == "succeeded" for attempt in attempts):
                raise LifecycleJournalConflictError("Lifecycle handler attempt no longer owns its lease")
            now = self._clock().astimezone(UTC)
            lease = {
                "schema": LIFECYCLE_ATTEMPT_LEASE_SCHEMA,
                "operation_id": operation_id,
                "handler_key": handler_key,
                "attempt_id": attempt_id,
                "generation": current["generation"],
                "renewed_at": _timestamp(now),
                "expires_at": _timestamp(now + lease_duration),
            }
            _atomic_replace_json(
                operation_dir / "attempts" / handler_key / attempt_id / "lease.json",
                lease,
            )
            return dict(lease)

    def finish_attempt(
        self,
        operation_id: str,
        handler_key: str,
        attempt_id: str,
        *,
        succeeded: bool,
        error_type: str | None = None,
    ) -> dict[str, Any]:
        """Append one terminal handler-attempt outcome."""

        operation_id = _validate_operation_id(operation_id)
        handler_key = validate_lifecycle_handler_key(handler_key)
        attempt_id = _validate_attempt_id(attempt_id)
        if succeeded:
            error_type = None
        elif not isinstance(error_type, str) or not error_type or len(error_type) > 128:
            raise LifecycleJournalError("Lifecycle failure type is invalid")
        outcome = {
            "schema": LIFECYCLE_ATTEMPT_OUTCOME_SCHEMA,
            "operation_id": operation_id,
            "handler_key": handler_key,
            "attempt_id": attempt_id,
            "status": "succeeded" if succeeded else "failed",
            "completed_at": _timestamp(self._clock()),
            "error_type": error_type,
        }
        self._prepare_root()
        operation_dir = self._operation_dir(operation_id)
        attempt_dir = operation_dir / "attempts" / handler_key / attempt_id
        with _exclusive_file_lock(self.root / ".lifecycle.lock"):
            event = self._load_event(operation_dir, operation_id)
            if handler_key not in event["handlers"]:
                raise LifecycleJournalError("Lifecycle handler is not registered for this event")
            source = self._source_projection(operation_dir, event)
            if source["source_status"] != "committed":
                raise LifecycleJournalError("Lifecycle source intent is not committed")
            attempts = self._attempts_for_handler(
                operation_dir,
                operation_id=operation_id,
                handler_key=handler_key,
            )
            current = next(
                (attempt for attempt in attempts if attempt["attempt_id"] == attempt_id),
                None,
            )
            if current is None:
                raise LifecycleJournalError("Lifecycle handler attempt was not found")
            outcome_path = attempt_dir / "outcome.json"
            if current["status"] != "running":
                existing = _validate_attempt_outcome(
                    _read_json_object(outcome_path),
                    operation_id=operation_id,
                    handler_key=handler_key,
                    attempt_id=attempt_id,
                )
                if existing["status"] == outcome["status"] and existing["error_type"] == outcome["error_type"]:
                    return self.get(operation_id)
                raise LifecycleJournalConflictError("Lifecycle attempt already has a different outcome")
            newest_generation = max(cast(int, attempt["generation"]) for attempt in attempts)
            if cast(int, current["generation"]) != newest_generation or any(attempt["status"] == "succeeded" for attempt in attempts if attempt["attempt_id"] != attempt_id):
                raise LifecycleJournalConflictError("Lifecycle handler attempt was superseded")
            _write_bytes_exclusive(outcome_path, _json_bytes(outcome))
            _sync_directory(attempt_dir)
        return self.get(operation_id)

    def list(
        self,
        *,
        limit: int = 100,
        unfinished_only: bool = False,
        oldest_first: bool = False,
    ) -> list[dict[str, Any]]:
        """List newest verified lifecycle operations."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIST_LIMIT:
            raise LifecycleJournalError("Lifecycle list limit is invalid")
        if not isinstance(unfinished_only, bool) or not isinstance(
            oldest_first,
            bool,
        ):
            raise LifecycleJournalError("Lifecycle list filter is invalid")
        if not self.root.exists():
            return []
        if self.root.is_symlink() or not self.root.is_dir():
            raise LifecycleJournalIntegrityError("Lifecycle journal root is unsafe")
        operation_ids: list[str] = []
        scanned = 0
        for entry in self.root.iterdir():
            if entry.name.startswith("."):
                continue
            scanned += 1
            if scanned > _MAX_OPERATIONS:
                raise LifecycleJournalError("Lifecycle journal scan exceeds the safety limit")
            operation_ids.append(_validate_operation_id(entry.name))
        operations = [self.get(operation_id) for operation_id in operation_ids]
        operations.sort(
            key=lambda item: (
                cast(str, item["created_at"]),
                cast(str, item["operation_id"]),
            ),
            reverse=not oldest_first,
        )
        if unfinished_only:
            operations = [operation for operation in operations if operation["status"] not in {"succeeded", "aborted"}]
        return operations[:limit]


__all__ = [
    "FileThreadLifecycleJournal",
    "LIFECYCLE_ATTEMPT_LEASE_SCHEMA",
    "LIFECYCLE_ATTEMPT_OUTCOME_SCHEMA",
    "LIFECYCLE_ATTEMPT_START_SCHEMA",
    "LIFECYCLE_EVENT_SCHEMA",
    "LIFECYCLE_SOURCE_ABORT_SCHEMA",
    "LIFECYCLE_SOURCE_COMMIT_SCHEMA",
    "LIFECYCLE_SOURCE_PREPARE_SCHEMA",
    "LifecycleJournalConflictError",
    "LifecycleJournalError",
    "LifecycleJournalIntegrityError",
    "LifecycleOperationNotFoundError",
    "validate_lifecycle_handler_key",
]
