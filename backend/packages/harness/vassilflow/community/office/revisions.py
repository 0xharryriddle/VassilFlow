"""Immutable, user-scoped project revisions for VassilFlow Office edits."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import weakref
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows-only branch
    fcntl = None  # type: ignore[assignment]
    import msvcrt

from .errors import (
    OfficePackageError,
    OfficeRevisionConflictError,
    OfficeRevisionError,
    OfficeRevisionIntegrityError,
)
from .generation import validate_generation_evidence
from .render import RenderedOfficePage

PROJECT_SCHEMA = "vassilflow.office.project.v1"
REVISION_SCHEMA = "vassilflow.office.revision.v1"
RECEIPT_SCHEMA = "vassilflow.office.semantic_change_receipt.v1"
RENDER_MANIFEST_SCHEMA = "vassilflow.office.render_manifest.v1"
RENDER_EVIDENCE_SCHEMA = "vassilflow.office.render_evidence.v1"
PROJECT_REVIEW_SCHEMA = "vassilflow.office.project_review.v1"
FINAL_SELECTION_SCHEMA = "vassilflow.office.final_selection.v1"

_PROJECT_ID_RE = re.compile(r"^ofp_[0-9a-f]{32}$")
_REVISION_ID_RE = re.compile(r"^ofr_[0-9a-f]{32}$")
_EVIDENCE_ID_RE = re.compile(r"^ofe_[0-9a-f]{32}$")
_REVIEW_ID_RE = re.compile(r"^ofv_[0-9a-f]{32}$")
_FINAL_SELECTION_ID_RE = re.compile(r"^ofs_[0-9a-f]{32}$")
_OPERATION_ID_RE = re.compile(r"^op-[0-9]{4}-[0-9a-f]{12}$")
_TEMPLATE_ID_RE = re.compile(r"^oft_[0-9a-f]{32}$")
_FORMATS = frozenset({"docx", "pptx", "xlsx"})
_MAX_METADATA_BYTES = 16 * 1024 * 1024
_MAX_CONTEXT_TEXT_CHARS = 2_048
_ID_GENERATION_ATTEMPTS = 16
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_RENDER_PAGE_COUNT = 10_000
_MAX_RENDER_PAGES_PER_EVIDENCE = 12
_MAX_RENDER_DIMENSION = 10_000
_MAX_RENDER_EVIDENCE_RECORDS = 10_000
_MAX_RENDER_EVIDENCE_LIST_LIMIT = 500
_MAX_PROJECT_RECORDS = 10_000
_MAX_PROJECT_LIST_LIMIT = 500
_MAX_REVISION_RECORDS = 10_000
_MAX_REVISION_LIST_LIMIT = 500
_MAX_REVIEW_RECORDS = 10_000
_MAX_REVIEW_LIST_LIMIT = 500
_MAX_REVIEW_EVIDENCE = 1_000
_MAX_REVIEW_NOTE_CHARS = 2_048

logger = logging.getLogger(__name__)

_LOCKS: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
_LOCKS_GUARD = threading.Lock()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _new_project_id() -> str:
    return f"ofp_{uuid4().hex}"


def _new_revision_id() -> str:
    return f"ofr_{uuid4().hex}"


def _new_evidence_id() -> str:
    return f"ofe_{uuid4().hex}"


def _new_review_id() -> str:
    return f"ofv_{uuid4().hex}"


def _new_final_selection_id() -> str:
    return f"ofs_{uuid4().hex}"


def _validate_project_id(project_id: str) -> str:
    if not isinstance(project_id, str) or _PROJECT_ID_RE.fullmatch(project_id) is None:
        raise OfficeRevisionError("Invalid Office project ID")
    return project_id


def _validate_revision_id(revision_id: str) -> str:
    if not isinstance(revision_id, str) or _REVISION_ID_RE.fullmatch(revision_id) is None:
        raise OfficeRevisionError("Invalid Office revision ID")
    return revision_id


def _validate_evidence_id(evidence_id: str) -> str:
    if not isinstance(evidence_id, str) or _EVIDENCE_ID_RE.fullmatch(evidence_id) is None:
        raise OfficeRevisionError("Invalid Office render evidence ID")
    return evidence_id


def _validate_review_id(review_id: str) -> str:
    if not isinstance(review_id, str) or _REVIEW_ID_RE.fullmatch(review_id) is None:
        raise OfficeRevisionError("Invalid Office project review ID")
    return review_id


def _validate_final_selection_id(selection_id: str) -> str:
    if not isinstance(selection_id, str) or _FINAL_SELECTION_ID_RE.fullmatch(selection_id) is None:
        raise OfficeRevisionError("Invalid Office final selection ID")
    return selection_id


def _normalize_format(suffix: str) -> str:
    normalized = suffix.lower().lstrip(".")
    if normalized not in _FORMATS:
        raise OfficeRevisionError(f"Unsupported Office revision format: {suffix}")
    return normalized


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _verify_counted_list(
    payload: dict[str, Any],
    *,
    values_key: str,
    returned_key: str,
    count_key: str,
    truncated_key: str,
) -> list[Any]:
    values = payload.get(values_key)
    count = payload.get(count_key)
    returned = payload.get(returned_key)
    truncated = payload.get(truncated_key)
    if not isinstance(values, list) or not _nonnegative_int(count) or not _nonnegative_int(returned) or returned != len(values) or not isinstance(truncated, bool) or count < returned or truncated != (returned < count):
        raise OfficeRevisionIntegrityError(f"Office revision receipt {values_key} bounds are invalid")
    return values


def _verify_receipt_shape(receipt: dict[str, Any]) -> None:
    if receipt.get("status") not in {"changed", "unchanged"}:
        raise OfficeRevisionIntegrityError("Office revision receipt status is invalid")
    for endpoint_name in ("source", "result"):
        endpoint = receipt.get(endpoint_name)
        if not isinstance(endpoint, dict) or not isinstance(endpoint.get("sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", endpoint["sha256"]) is None or not _nonnegative_int(endpoint.get("size_bytes")):
            raise OfficeRevisionIntegrityError(f"Office revision receipt {endpoint_name} identity is invalid")
    operation_count = receipt.get("operation_count")
    if not _nonnegative_int(operation_count):
        raise OfficeRevisionIntegrityError("Office revision receipt operation count is invalid")
    operation_ids = _verify_counted_list(
        receipt,
        values_key="applied_operation_ids",
        returned_key="operation_ids_returned",
        count_key="operation_count",
        truncated_key="operation_ids_truncated",
    )
    if any(not isinstance(operation_id, str) or _OPERATION_ID_RE.fullmatch(operation_id) is None for operation_id in operation_ids) or len(set(operation_ids)) != len(operation_ids):
        raise OfficeRevisionIntegrityError("Office revision receipt operation IDs are invalid")
    operations = _verify_counted_list(
        receipt,
        values_key="operations",
        returned_key="operations_returned",
        count_key="operation_count",
        truncated_key="operations_truncated",
    )
    if len(operations) != len(operation_ids):
        raise OfficeRevisionIntegrityError("Office revision receipt operation evidence is incomplete")
    for expected_position, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            raise OfficeRevisionIntegrityError("Office revision receipt operation record is invalid")
        target_paths = _verify_counted_list(
            operation,
            values_key="target_paths",
            returned_key="target_paths_returned",
            count_key="target_path_count",
            truncated_key="target_paths_truncated",
        )
        if (
            operation.get("position") != expected_position
            or operation.get("operation_id") != operation_ids[expected_position - 1]
            or not isinstance(operation.get("type"), str)
            or not _nonnegative_int(operation.get("match_count"))
            or any(not isinstance(path, str) or not path for path in target_paths)
        ):
            raise OfficeRevisionIntegrityError("Office revision receipt operation evidence is invalid")

    semantic = receipt.get("semantic_changes")
    if not isinstance(semantic, dict) or semantic.get("coverage") not in {"complete", "partial"}:
        raise OfficeRevisionIntegrityError("Office revision receipt semantic evidence is invalid")
    changed_paths = _verify_counted_list(
        semantic,
        values_key="changed_target_paths",
        returned_key="changed_target_paths_returned",
        count_key="changed_target_count",
        truncated_key="changed_target_paths_truncated",
    )
    deltas = _verify_counted_list(
        semantic,
        values_key="semantic_deltas",
        returned_key="semantic_deltas_returned",
        count_key="semantic_delta_count",
        truncated_key="semantic_deltas_truncated",
    )
    if (
        not _nonnegative_int(semantic.get("evaluated_target_count"))
        or any(not isinstance(path, str) or not path for path in changed_paths)
        or any(
            not isinstance(delta, dict) or not isinstance(delta.get("path"), str) or not isinstance(delta.get("semantic_kind"), str) or not isinstance(delta.get("property"), str) or "before" not in delta or "after" not in delta
            for delta in deltas
        )
    ):
        raise OfficeRevisionIntegrityError("Office revision receipt semantic deltas are invalid")

    package = receipt.get("package_changes")
    if not isinstance(package, dict):
        raise OfficeRevisionIntegrityError("Office revision receipt package evidence is invalid")
    parts = _verify_counted_list(
        package,
        values_key="parts",
        returned_key="parts_returned",
        count_key="part_change_count",
        truncated_key="parts_truncated",
    )
    relationships = _verify_counted_list(
        package,
        values_key="relationships",
        returned_key="relationships_returned",
        count_key="relationship_change_count",
        truncated_key="relationships_truncated",
    )
    if (
        not isinstance(package.get("part_status_counts"), dict)
        or not isinstance(package.get("relationship_status_counts"), dict)
        or any(not isinstance(change, dict) for change in parts)
        or any(not isinstance(change, dict) for change in relationships)
    ):
        raise OfficeRevisionIntegrityError("Office revision receipt package changes are invalid")
    limits = receipt.get("limits")
    if not isinstance(limits, dict) or not limits or any(not isinstance(value, int) or value <= 0 for value in limits.values()):
        raise OfficeRevisionIntegrityError("Office revision receipt limits are invalid")


def _bounded_context_text(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > _MAX_CONTEXT_TEXT_CHARS:
        raise OfficeRevisionError(f"Office revision {field_name} is invalid")
    if any(ord(character) < 32 for character in value):
        raise OfficeRevisionError(f"Office revision {field_name} contains control characters")
    return value


def _normalize_template_resource(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "template_id",
        "version",
        "source_sha256",
    }:
        raise OfficeRevisionError("Office revision template resource is invalid")
    template_id = value.get("template_id")
    version = value.get("version")
    source_sha256 = value.get("source_sha256")
    if (
        not isinstance(template_id, str)
        or _TEMPLATE_ID_RE.fullmatch(template_id) is None
        or not isinstance(version, int)
        or isinstance(version, bool)
        or version < 1
        or not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise OfficeRevisionError("Office revision template resource is invalid")
    return {
        "template_id": template_id,
        "version": version,
        "source_sha256": source_sha256,
    }


def _normalize_template_policy(
    value: dict[str, Any] | None,
    *,
    template_resource: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if (
        template_resource is None
        or not isinstance(value, dict)
        or set(value)
        != {
            "template_id",
            "version",
            "source_sha256",
            "structure_fingerprint",
            "allowed_target_paths",
            "requested_target_paths",
            "changed_target_paths",
        }
    ):
        raise OfficeRevisionError("Office revision template policy evidence is invalid")
    if any(value.get(key) != template_resource[key] for key in template_resource):
        raise OfficeRevisionError("Office revision template policy resource is inconsistent")
    structure_fingerprint = value.get("structure_fingerprint")
    if not isinstance(structure_fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", structure_fingerprint) is None:
        raise OfficeRevisionError("Office revision template structure evidence is invalid")
    paths: dict[str, list[str]] = {}
    for field_name in (
        "allowed_target_paths",
        "requested_target_paths",
        "changed_target_paths",
    ):
        field_paths = value.get(field_name)
        if not isinstance(field_paths, list) or any(not isinstance(path, str) or not path for path in field_paths) or field_paths != sorted(set(field_paths)):
            raise OfficeRevisionError("Office revision template target evidence is invalid")
        paths[field_name] = field_paths
    if not set(paths["requested_target_paths"]) <= set(paths["allowed_target_paths"]) or not set(paths["changed_target_paths"]) <= set(paths["allowed_target_paths"]):
        raise OfficeRevisionError("Office revision template policy escaped its allowlist")
    return {
        **template_resource,
        "structure_fingerprint": structure_fingerprint,
        **paths,
    }


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value is not allowed: {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_bytes(payload: dict[str, Any]) -> bytes:
    try:
        data = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OfficeRevisionError("Office revision metadata is not valid JSON") from exc
    if len(data) > _MAX_METADATA_BYTES:
        raise OfficeRevisionError("Office revision metadata exceeds the storage limit")
    return data


def _read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise OfficeRevisionIntegrityError("Office revision metadata is missing or unsafe")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise OfficeRevisionIntegrityError("Office revision metadata could not be read") from exc
    if len(data) > _MAX_METADATA_BYTES:
        raise OfficeRevisionIntegrityError("Office revision metadata exceeds the storage limit")
    try:
        payload = json.loads(
            data,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise OfficeRevisionIntegrityError("Office revision metadata is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise OfficeRevisionIntegrityError("Office revision metadata must be a JSON object")
    return payload


def _write_bytes_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        path.chmod(0o600)
    except FileExistsError as exc:
        raise OfficeRevisionIntegrityError("Office revision attempted to replace immutable data") from exc


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


def _atomic_replace_json(path: Path, payload: dict[str, Any]) -> None:
    staging = path.with_name(f".{path.name}.stage-{uuid4().hex}")
    try:
        _write_bytes_exclusive(staging, _json_bytes(payload))
        os.replace(staging, path)
        _sync_directory(path.parent)
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove staged Office project metadata", exc_info=True)


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


def _safe_cleanup_staging(path: Path, parent: Path) -> None:
    try:
        resolved_parent = parent.resolve()
        resolved_path = path.resolve()
        if resolved_path.parent != resolved_parent or not path.name.startswith(".s-"):
            logger.error("Refused to clean unexpected Office staging path")
            return
        if path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.exists():
            shutil.rmtree(path)
    except OSError:
        logger.warning("Could not remove staged Office revision data", exc_info=True)


@dataclass(frozen=True, slots=True)
class OfficeRevisionCommit:
    """Public identifiers for one durably committed Office edit revision."""

    project_id: str
    revision_id: str
    parent_revision_id: str | None
    sequence: int
    project_created: bool
    revision_count: int
    artifact_sha256: str
    artifact_size_bytes: int
    baseline_revision_id: str | None = None

    def as_tool_metadata(self) -> dict[str, Any]:
        revision: dict[str, Any] = {
            "schema": REVISION_SCHEMA,
            "revision_id": self.revision_id,
            "parent_revision_id": self.parent_revision_id,
            "sequence": self.sequence,
            "artifact": {
                "sha256": self.artifact_sha256,
                "size_bytes": self.artifact_size_bytes,
            },
        }
        if self.baseline_revision_id is not None:
            revision["baseline_revision_id"] = self.baseline_revision_id
        return {
            "project": {
                "schema": PROJECT_SCHEMA,
                "project_id": self.project_id,
                "created": self.project_created,
                "current_revision_id": self.revision_id,
                "revision_count": self.revision_count,
                "storage_scope": "trusted_user",
            },
            "revision": revision,
        }


@dataclass(frozen=True, slots=True)
class OfficeRenderEvidenceCommit:
    """Public identifiers for one immutable render-preview evidence record."""

    project_id: str
    revision_id: str
    evidence_id: str
    source_sha256: str
    page_count: int
    rendered_page_count: int
    start_page: int
    end_page: int
    has_more: bool
    visual_review_status: str

    def as_tool_metadata(self) -> dict[str, Any]:
        return {
            "render_evidence": {
                "schema": RENDER_EVIDENCE_SCHEMA,
                "evidence_id": self.evidence_id,
                "project_id": self.project_id,
                "revision_id": self.revision_id,
                "source_sha256": self.source_sha256,
                "page_count": self.page_count,
                "rendered_page_count": self.rendered_page_count,
                "start_page": self.start_page,
                "end_page": self.end_page,
                "has_more": self.has_more,
                "visual_review_status": self.visual_review_status,
                "storage_scope": "trusted_user",
            }
        }


@dataclass(frozen=True, slots=True)
class OfficeResolvedRenderEvidenceSet:
    """Newest coherent render evidence available for one exact revision."""

    evidence: tuple[dict[str, Any], ...]
    page_count: int
    rendered_page_count: int
    complete: bool

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(record["evidence_id"] for record in self.evidence)


@dataclass(frozen=True, slots=True)
class OfficeProjectReviewCommit:
    """Public identity for one immutable project visual-review decision."""

    project_id: str
    revision_id: str
    review_id: str
    status: str
    evidence_ids: tuple[str, ...]
    page_count: int


@dataclass(frozen=True, slots=True)
class OfficeFinalSelectionCommit:
    """Public identity for one immutable approved final-artifact selection."""

    project_id: str
    selection_id: str
    revision_id: str
    review_id: str
    artifact_sha256: str


def resolve_render_evidence_set(
    revision: dict[str, Any],
    evidence: Sequence[dict[str, Any]],
) -> OfficeResolvedRenderEvidenceSet:
    """Choose the newest coherent page set from verified immutable evidence."""

    if not evidence:
        return OfficeResolvedRenderEvidenceSet((), 0, 0, False)

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    group_order: list[tuple[Any, ...]] = []
    artifact = revision["artifact"]
    for record in evidence:
        manifest = record["render_manifest"]
        source = record["source"]
        if record["revision_id"] != revision["revision_id"] or source != {
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
        }:
            raise OfficeRevisionConflictError("Office project render evidence is stale for the selected revision")
        identity = (
            source["sha256"],
            source["size_bytes"],
            manifest["page_count"],
            manifest["renderer"],
            manifest["renderer_version"],
            manifest["pdfium_version"],
            manifest["pipeline_fingerprint"],
            manifest["dpi"],
        )
        if identity not in groups:
            groups[identity] = []
            group_order.append(identity)
        groups[identity].append(record)

    best: tuple[list[dict[str, Any]], int, int] | None = None
    for identity in group_order:
        page_count = int(identity[2])
        pages: dict[int, str] = {}
        selected: list[dict[str, Any]] = []
        for record in groups[identity]:
            record_pages = {preview["page"]: preview["sha256"] for preview in record["preview_pages"]}
            if any(page in pages and pages[page] != sha256 for page, sha256 in record_pages.items()):
                continue
            if not any(page not in pages for page in record_pages):
                continue
            pages.update(record_pages)
            selected.append(record)
            if len(pages) == page_count:
                break
        candidate = (selected, page_count, len(pages))
        if best is None or candidate[2] > best[2]:
            best = candidate
        if candidate[2] == page_count:
            best = candidate
            break

    if best is None:
        return OfficeResolvedRenderEvidenceSet((), 0, 0, False)
    selected, page_count, rendered_page_count = best
    selected.sort(
        key=lambda record: (
            record["render_manifest"]["start_page"],
            record["evidence_id"],
        )
    )
    return OfficeResolvedRenderEvidenceSet(
        tuple(selected),
        page_count,
        rendered_page_count,
        rendered_page_count == page_count,
    )


class OfficeRevisionStore:
    """Filesystem store whose revision directories are published once and never rewritten."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        project_id_factory: Callable[[], str] | None = None,
        revision_id_factory: Callable[[], str] | None = None,
        evidence_id_factory: Callable[[], str] | None = None,
        review_id_factory: Callable[[], str] | None = None,
        final_selection_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.projects_dir = self.root / "projects"
        self._clock = clock or (lambda: datetime.now(UTC))
        self._project_id_factory = project_id_factory or _new_project_id
        self._revision_id_factory = revision_id_factory or _new_revision_id
        self._evidence_id_factory = evidence_id_factory or _new_evidence_id
        self._review_id_factory = review_id_factory or _new_review_id
        self._final_selection_id_factory = final_selection_id_factory or _new_final_selection_id

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            raise OfficeRevisionError("Office revision clock must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def _project_dir(self, project_id: str) -> Path:
        return self.projects_dir / _validate_project_id(project_id)

    def _revision_dir(self, project_id: str, revision_id: str) -> Path:
        return self._project_dir(project_id) / "revisions" / _validate_revision_id(revision_id)

    def _render_evidence_dir(self, project_id: str, evidence_id: str) -> Path:
        return self._project_dir(project_id) / "renders" / _validate_evidence_id(evidence_id)

    def _review_dir(self, project_id: str, review_id: str) -> Path:
        return self._project_dir(project_id) / "reviews" / _validate_review_id(review_id)

    def _final_selection_dir(self, project_id: str, selection_id: str) -> Path:
        return self._project_dir(project_id) / "finals" / _validate_final_selection_id(selection_id)

    def _next_revision_id(self, revisions_dir: Path, *, reserved: set[str] | None = None) -> str:
        reserved = reserved or set()
        for _ in range(_ID_GENERATION_ATTEMPTS):
            revision_id = _validate_revision_id(self._revision_id_factory())
            if revision_id not in reserved and not (revisions_dir / revision_id).exists():
                return revision_id
        raise OfficeRevisionError("Could not allocate a unique Office revision ID")

    def _next_evidence_id(self, renders_dir: Path) -> str:
        for _ in range(_ID_GENERATION_ATTEMPTS):
            evidence_id = _validate_evidence_id(self._evidence_id_factory())
            if not (renders_dir / evidence_id).exists():
                return evidence_id
        raise OfficeRevisionError("Could not allocate a unique Office render evidence ID")

    def _next_review_id(self, reviews_dir: Path) -> str:
        for _ in range(_ID_GENERATION_ATTEMPTS):
            review_id = _validate_review_id(self._review_id_factory())
            if not (reviews_dir / review_id).exists():
                return review_id
        raise OfficeRevisionError("Could not allocate a unique Office project review ID")

    def _next_final_selection_id(self, finals_dir: Path) -> str:
        for _ in range(_ID_GENERATION_ATTEMPTS):
            selection_id = _validate_final_selection_id(self._final_selection_id_factory())
            if not (finals_dir / selection_id).exists():
                return selection_id
        raise OfficeRevisionError("Could not allocate a unique Office final selection ID")

    def _verify_evidence(
        self,
        *,
        source: bytes,
        result: bytes,
        format_name: str,
        receipt: dict[str, Any],
        source_validation: dict[str, Any],
        result_validation: dict[str, Any],
    ) -> tuple[str, str]:
        source_sha256 = _sha256(source)
        result_sha256 = _sha256(result)
        expected_status = "changed" if source_sha256 != result_sha256 else "unchanged"
        if not isinstance(receipt, dict):
            raise OfficeRevisionIntegrityError("Office revision receipt must be a JSON object")
        if (
            receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("format") != format_name
            or receipt.get("status") != expected_status
            or receipt.get("source") != {"sha256": source_sha256, "size_bytes": len(source)}
            or receipt.get("result") != {"sha256": result_sha256, "size_bytes": len(result)}
        ):
            raise OfficeRevisionIntegrityError("Office revision receipt does not match the artifact bytes")
        _verify_receipt_shape(receipt)
        for label, validation in (
            ("source", source_validation),
            ("result", result_validation),
        ):
            if not isinstance(validation, dict):
                raise OfficeRevisionIntegrityError(f"Office revision {label} validation is invalid")
            if validation.get("valid") is not True or validation.get("format") != format_name:
                raise OfficeRevisionIntegrityError(f"Office revision {label} validation is incomplete")
        _json_bytes(receipt)
        _json_bytes(source_validation)
        _json_bytes(result_validation)
        return source_sha256, result_sha256

    @staticmethod
    def _quality_at_commit(validation: dict[str, Any]) -> dict[str, Any]:
        return {
            "package_validation": validation,
            "preflight_status": "not_recorded",
            "render_status": "not_recorded",
            "visual_review_status": "not_performed",
        }

    def _baseline_metadata(
        self,
        *,
        project_id: str,
        revision_id: str,
        created_at: str,
        format_name: str,
        source: bytes,
        source_sha256: str,
        source_path: str,
        thread_id: str | None,
        source_validation: dict[str, Any],
        template_resource: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "schema": REVISION_SCHEMA,
            "project_id": project_id,
            "revision_id": revision_id,
            "sequence": 1,
            "kind": "baseline",
            "parent_revision_id": None,
            "created_at": created_at,
            "format": format_name,
            "artifact": {
                "filename": f"artifact.{format_name}",
                "sha256": source_sha256,
                "size_bytes": len(source),
            },
            "provenance": {
                "thread_id": thread_id,
                "source_path": source_path,
                "output_path": None,
                "tool": None,
            },
            "operation_receipt": None,
            "quality_at_commit": self._quality_at_commit(source_validation),
            "resource_versions": {
                "template": template_resource,
                "brand": None,
            },
            "template_policy": None,
        }

    def _edit_metadata(
        self,
        *,
        project_id: str,
        revision_id: str,
        parent_revision_id: str,
        sequence: int,
        created_at: str,
        format_name: str,
        source: bytes,
        result: bytes,
        source_sha256: str,
        result_sha256: str,
        source_path: str,
        output_path: str,
        thread_id: str | None,
        receipt: dict[str, Any],
        result_validation: dict[str, Any],
        template_resource: dict[str, Any] | None,
        template_policy: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "schema": REVISION_SCHEMA,
            "project_id": project_id,
            "revision_id": revision_id,
            "sequence": sequence,
            "kind": "edit",
            "parent_revision_id": parent_revision_id,
            "created_at": created_at,
            "format": format_name,
            "artifact": {
                "filename": f"artifact.{format_name}",
                "sha256": result_sha256,
                "size_bytes": len(result),
            },
            "input": {
                "revision_id": parent_revision_id,
                "sha256": source_sha256,
                "size_bytes": len(source),
            },
            "provenance": {
                "thread_id": thread_id,
                "source_path": source_path,
                "output_path": output_path,
                "tool": "office_edit",
            },
            "operation_receipt": receipt,
            "quality_at_commit": self._quality_at_commit(result_validation),
            "resource_versions": {
                "template": template_resource,
                "brand": None,
            },
            "template_policy": template_policy,
        }

    def _generation_metadata(
        self,
        *,
        project_id: str,
        revision_id: str,
        created_at: str,
        artifact: bytes,
        artifact_sha256: str,
        output_path: str,
        thread_id: str | None,
        intent: Mapping[str, Any],
        receipt: Mapping[str, Any],
        preflight: Mapping[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        quality = self._quality_at_commit(validation)
        quality["preflight_status"] = "recorded"
        return {
            "schema": REVISION_SCHEMA,
            "project_id": project_id,
            "revision_id": revision_id,
            "sequence": 1,
            "kind": "generation",
            "parent_revision_id": None,
            "created_at": created_at,
            "format": "pptx",
            "artifact": {
                "filename": "artifact.pptx",
                "sha256": artifact_sha256,
                "size_bytes": len(artifact),
            },
            "provenance": {
                "thread_id": thread_id,
                "source_path": None,
                "output_path": output_path,
                "tool": "office_generate",
            },
            "operation_receipt": None,
            "generation": {
                "intent": dict(intent),
                "receipt": dict(receipt),
                "preflight": dict(preflight),
            },
            "quality_at_commit": quality,
            "resource_versions": {
                "template": None,
                "brand": None,
            },
            "template_policy": None,
        }

    def _restore_metadata(
        self,
        *,
        project_id: str,
        revision_id: str,
        parent_revision_id: str,
        restored_from_revision_id: str,
        sequence: int,
        created_at: str,
        format_name: str,
        source: bytes,
        result: bytes,
        source_sha256: str,
        result_sha256: str,
        source_path: str,
        output_path: str,
        thread_id: str | None,
        receipt: dict[str, Any],
        result_validation: dict[str, Any],
        template_resource: dict[str, Any] | None,
        template_policy: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "schema": REVISION_SCHEMA,
            "project_id": project_id,
            "revision_id": revision_id,
            "sequence": sequence,
            "kind": "restore",
            "parent_revision_id": parent_revision_id,
            "restored_from_revision_id": restored_from_revision_id,
            "created_at": created_at,
            "format": format_name,
            "artifact": {
                "filename": f"artifact.{format_name}",
                "sha256": result_sha256,
                "size_bytes": len(result),
            },
            "input": {
                "revision_id": parent_revision_id,
                "sha256": source_sha256,
                "size_bytes": len(source),
            },
            "restore_source": {
                "revision_id": restored_from_revision_id,
                "sha256": result_sha256,
                "size_bytes": len(result),
            },
            "provenance": {
                "thread_id": thread_id,
                "source_path": source_path,
                "output_path": output_path,
                "tool": "office_restore",
            },
            "operation_receipt": receipt,
            "quality_at_commit": self._quality_at_commit(result_validation),
            "resource_versions": {
                "template": template_resource,
                "brand": None,
            },
            "template_policy": template_policy,
        }

    def _write_revision(
        self,
        revision_dir: Path,
        *,
        format_name: str,
        artifact: bytes,
        metadata: dict[str, Any],
    ) -> None:
        revision_dir.mkdir()
        _write_bytes_exclusive(revision_dir / f"artifact.{format_name}", artifact)
        _write_bytes_exclusive(revision_dir / "revision.json", _json_bytes(metadata))
        _sync_directory(revision_dir)

    def _load_project_unlocked(self, project_id: str) -> dict[str, Any]:
        project_dir = self._project_dir(project_id)
        if project_dir.is_symlink() or not project_dir.is_dir():
            raise OfficeRevisionError("Office project was not found")
        project = _read_json_object(project_dir / "project.json")
        current_revision_id = project.get("current_revision_id")
        current_artifact_sha256 = project.get("current_artifact_sha256")
        revision_count = project.get("revision_count")
        if (
            project.get("schema") != PROJECT_SCHEMA
            or project.get("project_id") != project_id
            or project.get("format") not in _FORMATS
            or not isinstance(project.get("created_at"), str)
            or not isinstance(project.get("updated_at"), str)
            or not isinstance(current_revision_id, str)
            or _REVISION_ID_RE.fullmatch(current_revision_id) is None
            or not isinstance(current_artifact_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", current_artifact_sha256) is None
            or not isinstance(revision_count, int)
            or isinstance(revision_count, bool)
            or revision_count < 1
        ):
            raise OfficeRevisionIntegrityError("Office project metadata identity is invalid")
        primary_thread_id = project.get("primary_thread_id")
        if primary_thread_id is not None:
            try:
                _bounded_context_text(primary_thread_id, field_name="primary thread ID")
            except OfficeRevisionError as exc:
                raise OfficeRevisionIntegrityError("Office project primary thread identity is invalid") from exc
        project_resources = project.get("resource_versions")
        if project_resources is not None:
            if not isinstance(project_resources, dict) or set(project_resources) != {"template", "brand"} or project_resources.get("brand") is not None:
                raise OfficeRevisionIntegrityError("Office project resource versions are invalid")
            try:
                _normalize_template_resource(project_resources.get("template"))
            except OfficeRevisionError as exc:
                raise OfficeRevisionIntegrityError("Office project template resource is invalid") from exc
        final_fields = {
            "final_selection_id": project.get("final_selection_id"),
            "final_revision_id": project.get("final_revision_id"),
            "final_artifact_sha256": project.get("final_artifact_sha256"),
        }
        if any(value is not None for value in final_fields.values()):
            try:
                _validate_final_selection_id(final_fields["final_selection_id"])
                _validate_revision_id(final_fields["final_revision_id"])
            except OfficeRevisionError as exc:
                raise OfficeRevisionIntegrityError("Office project final selection identity is invalid") from exc
            final_sha256 = final_fields["final_artifact_sha256"]
            if not isinstance(final_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", final_sha256) is None:
                raise OfficeRevisionIntegrityError("Office project final artifact identity is invalid")
        return project

    def _load_revision_unlocked(self, project_id: str, revision_id: str) -> dict[str, Any]:
        revision_dir = self._revision_dir(project_id, revision_id)
        if revision_dir.is_symlink() or not revision_dir.is_dir():
            raise OfficeRevisionError("Office revision was not found")
        revision = _read_json_object(revision_dir / "revision.json")
        if revision.get("schema") != REVISION_SCHEMA or revision.get("project_id") != project_id or revision.get("revision_id") != revision_id:
            raise OfficeRevisionIntegrityError("Office revision metadata identity is invalid")
        format_name = revision.get("format")
        artifact = revision.get("artifact")
        if format_name not in _FORMATS or not isinstance(artifact, dict):
            raise OfficeRevisionIntegrityError("Office revision artifact metadata is invalid")
        expected_filename = f"artifact.{format_name}"
        if artifact.get("filename") != expected_filename:
            raise OfficeRevisionIntegrityError("Office revision artifact filename is invalid")
        artifact_path = revision_dir / expected_filename
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise OfficeRevisionIntegrityError("Office revision artifact is missing or unsafe")
        try:
            artifact_bytes = artifact_path.read_bytes()
        except OSError as exc:
            raise OfficeRevisionIntegrityError("Office revision artifact could not be read") from exc
        if artifact.get("size_bytes") != len(artifact_bytes) or artifact.get("sha256") != _sha256(artifact_bytes):
            raise OfficeRevisionIntegrityError("Office revision artifact failed its SHA-256 integrity check")
        sequence = revision.get("sequence")
        quality = revision.get("quality_at_commit")
        validation = quality.get("package_validation") if isinstance(quality, dict) else None
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or not isinstance(revision.get("created_at"), str)
            or not isinstance(validation, dict)
            or validation.get("valid") is not True
            or validation.get("format") != format_name
        ):
            raise OfficeRevisionIntegrityError("Office revision core metadata is invalid")
        kind = revision.get("kind")
        resources = revision.get("resource_versions")
        if not isinstance(resources, dict) or set(resources) != {"template", "brand"} or resources.get("brand") is not None:
            raise OfficeRevisionIntegrityError("Office revision resource versions are invalid")
        try:
            template_resource = _normalize_template_resource(resources.get("template"))
            template_policy = _normalize_template_policy(
                revision.get("template_policy"),
                template_resource=template_resource,
            )
        except OfficeRevisionError as exc:
            raise OfficeRevisionIntegrityError("Office revision template evidence is invalid") from exc
        if kind == "baseline":
            if (
                sequence != 1
                or revision.get("parent_revision_id") is not None
                or revision.get("operation_receipt") is not None
                or revision.get("generation") is not None
                or revision.get("input") is not None
                or revision.get("restored_from_revision_id") is not None
                or revision.get("restore_source") is not None
                or template_policy is not None
                or (template_resource is not None and template_resource["source_sha256"] != artifact.get("sha256"))
            ):
                raise OfficeRevisionIntegrityError("Office baseline revision metadata is invalid")
        elif kind == "generation":
            generation = revision.get("generation")
            provenance = revision.get("provenance")
            if (
                sequence != 1
                or revision.get("parent_revision_id") is not None
                or revision.get("operation_receipt") is not None
                or revision.get("input") is not None
                or revision.get("restored_from_revision_id") is not None
                or revision.get("restore_source") is not None
                or template_resource is not None
                or template_policy is not None
                or not isinstance(generation, dict)
                or set(generation) != {"intent", "receipt", "preflight"}
                or not isinstance(generation.get("intent"), Mapping)
                or not isinstance(generation.get("receipt"), Mapping)
                or not isinstance(generation.get("preflight"), Mapping)
                or not isinstance(provenance, dict)
                or provenance.get("tool") != "office_generate"
                or provenance.get("source_path") is not None
                or quality.get("preflight_status") != "recorded"
            ):
                raise OfficeRevisionIntegrityError("Office generation revision metadata is invalid")
            try:
                validate_generation_evidence(
                    artifact=artifact_bytes,
                    intent=generation["intent"],
                    receipt=generation["receipt"],
                    preflight=generation["preflight"],
                )
            except OfficePackageError as exc:
                raise OfficeRevisionIntegrityError("Office generation evidence failed integrity checks") from exc
        elif kind in {"edit", "restore"}:
            parent_revision_id = revision.get("parent_revision_id")
            receipt = revision.get("operation_receipt")
            input_metadata = revision.get("input")
            if not isinstance(receipt, dict) or not isinstance(input_metadata, dict) or revision.get("generation") is not None:
                raise OfficeRevisionIntegrityError("Office change revision evidence is missing")
            _validate_revision_id(parent_revision_id)
            _verify_receipt_shape(receipt)
            if (
                receipt.get("schema") != RECEIPT_SCHEMA
                or receipt.get("format") != format_name
                or receipt.get("result")
                != {
                    "sha256": artifact.get("sha256"),
                    "size_bytes": artifact.get("size_bytes"),
                }
                or input_metadata.get("revision_id") != parent_revision_id
                or input_metadata.get("sha256") != receipt.get("source", {}).get("sha256")
                or input_metadata.get("size_bytes") != receipt.get("source", {}).get("size_bytes")
            ):
                raise OfficeRevisionIntegrityError("Office change revision receipt is inconsistent")
            if (template_resource is None) != (template_policy is None):
                raise OfficeRevisionIntegrityError("Office template change policy evidence is incomplete")
            provenance = revision.get("provenance")
            expected_tool = "office_edit" if kind == "edit" else "office_restore"
            if not isinstance(provenance, dict) or provenance.get("tool") != expected_tool:
                raise OfficeRevisionIntegrityError("Office change revision provenance is invalid")
            if kind == "restore":
                restored_from_revision_id = revision.get("restored_from_revision_id")
                restore_source = revision.get("restore_source")
                _validate_revision_id(restored_from_revision_id)
                if (
                    not isinstance(restore_source, dict)
                    or restore_source
                    != {
                        "revision_id": restored_from_revision_id,
                        "sha256": artifact.get("sha256"),
                        "size_bytes": artifact.get("size_bytes"),
                    }
                    or receipt.get("operation_count") != 1
                    or receipt.get("operations", [{}])[0].get("type") != "restore_revision"
                ):
                    raise OfficeRevisionIntegrityError("Office restore revision source evidence is invalid")
            elif revision.get("restored_from_revision_id") is not None or revision.get("restore_source") is not None:
                raise OfficeRevisionIntegrityError("Office edit revision restore evidence is invalid")
        else:
            raise OfficeRevisionIntegrityError("Office revision kind is invalid")
        return revision

    def _load_project_snapshot_unlocked(
        self,
        project_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        project = self._load_project_unlocked(project_id)
        current = self._load_revision_unlocked(project_id, project["current_revision_id"])
        project_resources = project.get("resource_versions")
        current_resources = current.get("resource_versions")
        if current.get("sequence") != project["revision_count"] or current.get("artifact", {}).get("sha256") != project["current_artifact_sha256"] or (project_resources is not None and project_resources != current_resources):
            raise OfficeRevisionIntegrityError("Office project current revision pointer is inconsistent")
        final_selection_id = project.get("final_selection_id")
        if final_selection_id is not None:
            chain = self._load_canonical_revision_chain_unlocked(project_id, project)
            selection = self._load_final_selection_unlocked(
                project_id,
                final_selection_id,
                project=project,
                canonical_revisions=chain,
            )
            if selection["revision_id"] != project.get("final_revision_id") or selection["artifact"]["sha256"] != project.get("final_artifact_sha256"):
                raise OfficeRevisionIntegrityError("Office project final selection pointer is inconsistent")
        return project, current

    def load_project_snapshot(
        self,
        project_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Read one project and return its already-verified current revision."""

        return self._load_project_snapshot_unlocked(_validate_project_id(project_id))

    def load_project(self, project_id: str) -> dict[str, Any]:
        """Read one project pointer and verify its selected revision artifact."""

        project, _current = self.load_project_snapshot(project_id)
        return project

    def load_revision(self, project_id: str, revision_id: str) -> dict[str, Any]:
        """Read one immutable revision and verify its artifact bytes."""

        return self._load_revision_unlocked(
            _validate_project_id(project_id),
            _validate_revision_id(revision_id),
        )

    def list_project_snapshots(
        self,
        *,
        limit: int = 100,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """List newest projects with each verified current revision loaded once."""

        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_PROJECT_LIST_LIMIT:
            raise OfficeRevisionError(f"Office project limit must be between 1 and {_MAX_PROJECT_LIST_LIMIT}")
        if not self.projects_dir.exists():
            return []
        if self.projects_dir.is_symlink() or not self.projects_dir.is_dir():
            raise OfficeRevisionIntegrityError("Office project directory is unsafe")

        candidates: list[tuple[str, str]] = []
        scanned = 0
        for entry in self.projects_dir.iterdir():
            if entry.name.startswith("."):
                continue
            scanned += 1
            if scanned > _MAX_PROJECT_RECORDS:
                raise OfficeRevisionIntegrityError("Office project index exceeds the supported limit")
            project_id = _validate_project_id(entry.name)
            if entry.is_symlink() or not entry.is_dir():
                raise OfficeRevisionIntegrityError("Office project entry is unsafe")
            project = self._load_project_unlocked(project_id)
            candidates.append((project["updated_at"], project_id))

        candidates.sort(reverse=True)
        return [self._load_project_snapshot_unlocked(project_id) for _updated_at, project_id in candidates[:limit]]

    def list_projects(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """List newest verified projects in this store's user-scoped root."""

        return [project for project, _current in self.list_project_snapshots(limit=limit)]

    def _load_canonical_revision_chain_unlocked(
        self,
        project_id: str,
        project: dict[str, Any],
    ) -> list[dict[str, Any]]:
        revision_count = project["revision_count"]
        if revision_count > _MAX_REVISION_RECORDS:
            raise OfficeRevisionIntegrityError("Office revision history exceeds the supported limit")

        revisions: list[dict[str, Any]] = []
        seen: set[str] = set()
        revision_id = project["current_revision_id"]
        expected_sequence = revision_count
        while expected_sequence >= 1:
            if revision_id in seen:
                raise OfficeRevisionIntegrityError("Office revision history contains a cycle")
            seen.add(revision_id)
            try:
                revision = self._load_revision_unlocked(project_id, revision_id)
            except OfficeRevisionIntegrityError:
                raise
            except OfficeRevisionError as exc:
                raise OfficeRevisionIntegrityError("Office revision history references a missing parent") from exc
            if revision.get("sequence") != expected_sequence:
                raise OfficeRevisionIntegrityError("Office revision history sequence is inconsistent")
            revisions.append(revision)

            parent_revision_id = revision.get("parent_revision_id")
            if expected_sequence == 1:
                if parent_revision_id is not None:
                    raise OfficeRevisionIntegrityError("Office revision history initial revision is inconsistent")
                break
            if not isinstance(parent_revision_id, str):
                raise OfficeRevisionIntegrityError("Office revision history parent is missing")
            revision_id = parent_revision_id
            expected_sequence -= 1

        if len(revisions) != revision_count:
            raise OfficeRevisionIntegrityError("Office revision history count is inconsistent")
        revisions_by_id = {revision["revision_id"]: revision for revision in revisions}
        for revision in revisions:
            if revision.get("kind") != "restore":
                continue
            restored_from_revision_id = revision["restored_from_revision_id"]
            restored_from = revisions_by_id.get(restored_from_revision_id)
            if restored_from is None or restored_from["sequence"] >= revision["sequence"] or restored_from["artifact"] != revision["artifact"]:
                raise OfficeRevisionIntegrityError("Office restore revision does not reference an older canonical artifact")
        return revisions

    def _load_canonical_revision_chain(self, project_id: str) -> list[dict[str, Any]]:
        project = self.load_project(project_id)
        return self._load_canonical_revision_chain_unlocked(project_id, project)

    def list_revisions(
        self,
        project_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List a project's newest canonical revisions after verifying its parent chain."""

        project_id = _validate_project_id(project_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_REVISION_LIST_LIMIT:
            raise OfficeRevisionError(f"Office revision limit must be between 1 and {_MAX_REVISION_LIST_LIMIT}")
        return self._load_canonical_revision_chain(project_id)[:limit]

    def load_project_revision(
        self,
        project_id: str,
        revision_id: str,
    ) -> dict[str, Any]:
        """Read one verified revision only when it belongs to the canonical project chain."""

        project_id = _validate_project_id(project_id)
        revision_id = _validate_revision_id(revision_id)
        for revision in self._load_canonical_revision_chain(project_id):
            if revision["revision_id"] == revision_id:
                return revision
        raise OfficeRevisionError("Office revision was not found in the project history")

    def read_revision_artifact(
        self,
        project_id: str,
        revision_id: str,
    ) -> tuple[dict[str, Any], bytes]:
        """Read one immutable artifact after rechecking its recorded SHA-256."""

        project_id = _validate_project_id(project_id)
        revision_id = _validate_revision_id(revision_id)
        revision = self.load_project_revision(project_id, revision_id)
        artifact = revision["artifact"]
        artifact_path = self._revision_dir(project_id, revision_id) / artifact["filename"]
        try:
            data = artifact_path.read_bytes()
        except OSError as exc:
            raise OfficeRevisionIntegrityError("Office revision artifact could not be read") from exc
        if artifact.get("size_bytes") != len(data) or artifact.get("sha256") != _sha256(data):
            raise OfficeRevisionIntegrityError("Office revision artifact failed its SHA-256 integrity check")
        return revision, data

    def _verify_revision_source_unlocked(
        self,
        *,
        project_id: str,
        revision_id: str,
        source: bytes,
        format_name: str,
    ) -> dict[str, Any]:
        project = self._load_project_unlocked(project_id)
        if project.get("format") != format_name:
            raise OfficeRevisionConflictError("Office project format does not match the render source")
        revision = next(
            (
                candidate
                for candidate in self._load_canonical_revision_chain_unlocked(
                    project_id,
                    project,
                )
                if candidate["revision_id"] == revision_id
            ),
            None,
        )
        if revision is None:
            raise OfficeRevisionError("Office revision was not found in the project history")
        artifact = revision.get("artifact")
        if revision.get("format") != format_name or not isinstance(artifact, dict) or artifact.get("sha256") != _sha256(source) or artifact.get("size_bytes") != len(source):
            raise OfficeRevisionConflictError("Office render source does not match the selected project revision bytes")
        return revision

    def verify_revision_source(
        self,
        *,
        project_id: str,
        revision_id: str,
        source: bytes,
        suffix: str,
    ) -> dict[str, Any]:
        """Verify an exact revision/source binding before an expensive render."""

        return self._verify_revision_source_unlocked(
            project_id=_validate_project_id(project_id),
            revision_id=_validate_revision_id(revision_id),
            source=source,
            format_name=_normalize_format(suffix),
        )

    @staticmethod
    def _verify_render_manifest(
        manifest: dict[str, Any],
        *,
        project_id: str,
        revision_id: str,
        source: bytes,
        format_name: str,
        pages: Sequence[RenderedOfficePage],
    ) -> None:
        source_sha256 = _sha256(source)
        if (
            manifest.get("schema") != RENDER_MANIFEST_SCHEMA
            or manifest.get("complete") is not True
            or manifest.get("project_id") != project_id
            or manifest.get("revision_id") != revision_id
            or manifest.get("format") != format_name
            or manifest.get("source_sha256") != source_sha256
            or manifest.get("source_size_bytes") != len(source)
        ):
            raise OfficeRevisionIntegrityError("Office render manifest source identity is invalid")
        for field_name in (
            "source_path",
            "output_dir",
            "manifest_path",
            "renderer",
            "renderer_version",
            "pdfium_version",
        ):
            if _bounded_context_text(manifest.get(field_name), field_name=f"render {field_name}") is None:
                raise OfficeRevisionIntegrityError(f"Office render manifest {field_name} is missing")
        if (
            not manifest["source_path"].startswith("/mnt/user-data/")
            or not manifest["output_dir"].startswith(
                (
                    "/mnt/user-data/workspace/",
                    "/mnt/user-data/outputs/",
                )
            )
            or manifest["manifest_path"] != f"{manifest['output_dir']}/render-manifest.json"
        ):
            raise OfficeRevisionIntegrityError("Office render manifest workspace paths are invalid")
        pipeline_fingerprint = manifest.get("pipeline_fingerprint")
        if not isinstance(pipeline_fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", pipeline_fingerprint) is None:
            raise OfficeRevisionIntegrityError("Office render manifest pipeline fingerprint is invalid")
        page_count = manifest.get("page_count")
        start_page = manifest.get("start_page")
        end_page = manifest.get("end_page")
        requested_max_pages = manifest.get("requested_max_pages")
        dpi = manifest.get("dpi")
        if (
            not _nonnegative_int(page_count)
            or page_count < 1
            or page_count > _MAX_RENDER_PAGE_COUNT
            or not _nonnegative_int(start_page)
            or start_page < 1
            or not _nonnegative_int(end_page)
            or end_page < start_page
            or end_page > page_count
            or not _nonnegative_int(requested_max_pages)
            or requested_max_pages < 1
            or requested_max_pages > _MAX_RENDER_PAGES_PER_EVIDENCE
            or not _nonnegative_int(dpi)
            or not 96 <= dpi <= 200
            or not isinstance(manifest.get("has_more"), bool)
            or manifest.get("has_more") != (end_page < page_count)
            or manifest.get("visual_review_status")
            not in {
                "pending",
                "reviewed",
                "external_review_required",
            }
            or manifest.get("gateway_page_access") not in {"available", "unavailable"}
        ):
            raise OfficeRevisionIntegrityError("Office render manifest window metadata is invalid")
        records = manifest.get("pages")
        if not isinstance(records, list) or not pages or len(records) != len(pages) or len(pages) > requested_max_pages:
            raise OfficeRevisionIntegrityError("Office render manifest page evidence is incomplete")
        expected_pages = list(range(start_page, end_page + 1))
        if len(expected_pages) != len(pages) or [page.page for page in pages] != expected_pages:
            raise OfficeRevisionIntegrityError("Office render pages are not a contiguous window")
        seen_filenames: set[str] = set()
        for page, record in zip(pages, records, strict=True):
            if not isinstance(record, dict):
                raise OfficeRevisionIntegrityError("Office render manifest page record is invalid")
            workspace_filename = page.filename
            if (
                not isinstance(workspace_filename, str)
                or not workspace_filename.endswith(".png")
                or PurePosixPath(workspace_filename).name != workspace_filename
                or workspace_filename in seen_filenames
                or not isinstance(page.page, int)
                or isinstance(page.page, bool)
                or not isinstance(page.width, int)
                or isinstance(page.width, bool)
                or not 1 <= page.width <= _MAX_RENDER_DIMENSION
                or not isinstance(page.height, int)
                or isinstance(page.height, bool)
                or not 1 <= page.height <= _MAX_RENDER_DIMENSION
                or not page.data.startswith(_PNG_SIGNATURE)
                or not isinstance(page.sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", page.sha256) is None
                or page.sha256 != _sha256(page.data)
                or record.get("page") != page.page
                or record.get("path") != f"{manifest['output_dir']}/{workspace_filename}"
                or record.get("width") != page.width
                or record.get("height") != page.height
                or record.get("sha256") != page.sha256
            ):
                raise OfficeRevisionIntegrityError("Office render page bytes do not match the manifest")
            if page.source_slide is None:
                if "source_slide" in record:
                    raise OfficeRevisionIntegrityError("Office render source-slide evidence is inconsistent")
            elif not isinstance(page.source_slide, int) or isinstance(page.source_slide, bool) or page.source_slide < 1 or record.get("source_slide") != page.source_slide:
                raise OfficeRevisionIntegrityError("Office render source-slide evidence is inconsistent")
            seen_filenames.add(workspace_filename)
        _json_bytes(manifest)

    def commit_render_evidence(
        self,
        *,
        project_id: str,
        revision_id: str,
        source: bytes,
        suffix: str,
        manifest: dict[str, Any],
        pages: Sequence[RenderedOfficePage],
        thread_id: str | None,
    ) -> OfficeRenderEvidenceCommit:
        """Attach one immutable render-preview record to an exact revision."""

        project_id = _validate_project_id(project_id)
        revision_id = _validate_revision_id(revision_id)
        format_name = _normalize_format(suffix)
        thread_id = _bounded_context_text(thread_id, field_name="thread ID")
        project_dir = self._project_dir(project_id)
        if project_dir.is_symlink() or not project_dir.is_dir():
            raise OfficeRevisionError("Office project was not found")
        with _exclusive_file_lock(project_dir / ".lock"):
            self._verify_revision_source_unlocked(
                project_id=project_id,
                revision_id=revision_id,
                source=source,
                format_name=format_name,
            )
            self._verify_render_manifest(
                manifest,
                project_id=project_id,
                revision_id=revision_id,
                source=source,
                format_name=format_name,
                pages=pages,
            )
            renders_dir = project_dir / "renders"
            renders_dir.mkdir(exist_ok=True)
            evidence_id = self._next_evidence_id(renders_dir)
            staging = renders_dir / f".s-{uuid4().hex[:12]}"
            preview_pages: list[dict[str, Any]] = []
            created_at = self._timestamp()
            try:
                page_dir = staging / "pages"
                page_dir.mkdir(parents=True)
                for page in pages:
                    stored_filename = f"page-{page.page:05d}.png"
                    _write_bytes_exclusive(page_dir / stored_filename, page.data)
                    preview_page = {
                        "page": page.page,
                        "workspace_filename": page.filename,
                        "filename": stored_filename,
                        "width": page.width,
                        "height": page.height,
                        "sha256": page.sha256,
                        "size_bytes": len(page.data),
                    }
                    if page.source_slide is not None:
                        preview_page["source_slide"] = page.source_slide
                    preview_pages.append(preview_page)
                metadata = {
                    "schema": RENDER_EVIDENCE_SCHEMA,
                    "evidence_id": evidence_id,
                    "project_id": project_id,
                    "revision_id": revision_id,
                    "created_at": created_at,
                    "thread_id": thread_id,
                    "format": format_name,
                    "source": {
                        "sha256": _sha256(source),
                        "size_bytes": len(source),
                    },
                    "render_manifest": manifest,
                    "preview_pages": preview_pages,
                    "review_at_commit": {
                        "visual_review_status": manifest["visual_review_status"],
                        "gateway_page_access": manifest["gateway_page_access"],
                    },
                }
                _write_bytes_exclusive(staging / "render.json", _json_bytes(metadata))
                _sync_directory(page_dir)
                _sync_directory(staging)
                os.rename(staging, renders_dir / evidence_id)
                _sync_directory(renders_dir)
            except Exception:
                _safe_cleanup_staging(staging, renders_dir)
                raise

        return OfficeRenderEvidenceCommit(
            project_id=project_id,
            revision_id=revision_id,
            evidence_id=evidence_id,
            source_sha256=_sha256(source),
            page_count=manifest["page_count"],
            rendered_page_count=len(pages),
            start_page=manifest["start_page"],
            end_page=manifest["end_page"],
            has_more=manifest["has_more"],
            visual_review_status=manifest["visual_review_status"],
        )

    def load_render_evidence(
        self,
        project_id: str,
        evidence_id: str,
    ) -> dict[str, Any]:
        """Read render evidence and verify every persisted preview page."""

        project_id = _validate_project_id(project_id)
        evidence_id = _validate_evidence_id(evidence_id)
        evidence_dir = self._render_evidence_dir(project_id, evidence_id)
        if evidence_dir.is_symlink() or not evidence_dir.is_dir():
            raise OfficeRevisionError("Office render evidence was not found")
        metadata = _read_json_object(evidence_dir / "render.json")
        revision_id = metadata.get("revision_id")
        manifest = metadata.get("render_manifest")
        preview_pages = metadata.get("preview_pages")
        review_at_commit = metadata.get("review_at_commit")
        if (
            metadata.get("schema") != RENDER_EVIDENCE_SCHEMA
            or metadata.get("project_id") != project_id
            or metadata.get("evidence_id") != evidence_id
            or not isinstance(metadata.get("created_at"), str)
            or not isinstance(manifest, dict)
            or not isinstance(preview_pages, list)
            or not isinstance(review_at_commit, dict)
        ):
            raise OfficeRevisionIntegrityError("Office render evidence identity is invalid")
        revision_id = _validate_revision_id(revision_id)
        project = self._load_project_unlocked(project_id)
        revision = next(
            (
                candidate
                for candidate in self._load_canonical_revision_chain_unlocked(
                    project_id,
                    project,
                )
                if candidate["revision_id"] == revision_id
            ),
            None,
        )
        if revision is None:
            raise OfficeRevisionError("Office revision was not found in the project history")
        format_name = revision["format"]
        artifact_path = self._revision_dir(project_id, revision_id) / revision["artifact"]["filename"]
        source = artifact_path.read_bytes()
        pages: list[RenderedOfficePage] = []
        for preview in preview_pages:
            if not isinstance(preview, dict) or not _nonnegative_int(preview.get("page")):
                raise OfficeRevisionIntegrityError("Office render preview metadata is invalid")
            expected_filename = f"page-{preview['page']:05d}.png"
            if preview.get("filename") != expected_filename:
                raise OfficeRevisionIntegrityError("Office render preview filename is invalid")
            page_path = evidence_dir / "pages" / expected_filename
            if page_path.is_symlink() or not page_path.is_file():
                raise OfficeRevisionIntegrityError("Office render preview page is missing or unsafe")
            data = page_path.read_bytes()
            if preview.get("size_bytes") != len(data) or preview.get("sha256") != _sha256(data):
                raise OfficeRevisionIntegrityError("Office render preview page failed its SHA-256 integrity check")
            pages.append(
                RenderedOfficePage(
                    page=preview["page"],
                    filename=preview.get("workspace_filename"),
                    width=preview.get("width"),
                    height=preview.get("height"),
                    sha256=preview.get("sha256"),
                    data=data,
                    source_slide=preview.get("source_slide"),
                )
            )
        self._verify_render_manifest(
            manifest,
            project_id=project_id,
            revision_id=revision_id,
            source=source,
            format_name=format_name,
            pages=pages,
        )
        if metadata.get("source") != {"sha256": _sha256(source), "size_bytes": len(source)}:
            raise OfficeRevisionIntegrityError("Office render evidence source identity is invalid")
        if metadata.get("format") != format_name:
            raise OfficeRevisionIntegrityError("Office render evidence format is inconsistent")
        if review_at_commit != {
            "visual_review_status": manifest["visual_review_status"],
            "gateway_page_access": manifest["gateway_page_access"],
        }:
            raise OfficeRevisionIntegrityError("Office render review evidence is inconsistent")
        return metadata

    def read_render_preview_page(
        self,
        project_id: str,
        evidence_id: str,
        page: int,
    ) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        """Read one trusted preview PNG after verifying its full evidence record."""

        project_id = _validate_project_id(project_id)
        evidence_id = _validate_evidence_id(evidence_id)
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= _MAX_RENDER_PAGE_COUNT:
            raise OfficeRevisionError(f"Office render preview page must be between 1 and {_MAX_RENDER_PAGE_COUNT}")
        metadata = self.load_render_evidence(project_id, evidence_id)
        preview = next(
            (record for record in metadata["preview_pages"] if isinstance(record, dict) and record.get("page") == page),
            None,
        )
        if preview is None:
            raise OfficeRevisionError("Office render preview page was not found")
        page_path = self._render_evidence_dir(project_id, evidence_id) / "pages" / preview["filename"]
        try:
            data = page_path.read_bytes()
        except OSError as exc:
            raise OfficeRevisionIntegrityError("Office render preview page could not be read") from exc
        if preview.get("size_bytes") != len(data) or preview.get("sha256") != _sha256(data):
            raise OfficeRevisionIntegrityError("Office render preview page failed its SHA-256 integrity check")
        return metadata, preview, data

    def list_render_evidence(
        self,
        project_id: str,
        *,
        revision_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List newest verified render evidence for a project or one revision."""

        project_id = _validate_project_id(project_id)
        if revision_id is not None:
            revision_id = _validate_revision_id(revision_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_RENDER_EVIDENCE_LIST_LIMIT:
            raise OfficeRevisionError(f"Office render evidence limit must be between 1 and {_MAX_RENDER_EVIDENCE_LIST_LIMIT}")
        canonical_revision_ids = {revision["revision_id"] for revision in self._load_canonical_revision_chain(project_id)}
        if revision_id is not None and revision_id not in canonical_revision_ids:
            raise OfficeRevisionError("Office revision was not found in the project history")
        renders_dir = self._project_dir(project_id) / "renders"
        if not renders_dir.exists():
            return []
        if renders_dir.is_symlink() or not renders_dir.is_dir():
            raise OfficeRevisionIntegrityError("Office render evidence directory is unsafe")
        candidates: list[tuple[str, str]] = []
        scanned = 0
        for entry in renders_dir.iterdir():
            if entry.name.startswith("."):
                continue
            scanned += 1
            if scanned > _MAX_RENDER_EVIDENCE_RECORDS:
                raise OfficeRevisionIntegrityError("Office render evidence index exceeds the supported limit")
            evidence_id = _validate_evidence_id(entry.name)
            if entry.is_symlink() or not entry.is_dir():
                raise OfficeRevisionIntegrityError("Office render evidence entry is unsafe")
            metadata = _read_json_object(entry / "render.json")
            if metadata.get("schema") != RENDER_EVIDENCE_SCHEMA or metadata.get("project_id") != project_id or metadata.get("evidence_id") != evidence_id or not isinstance(metadata.get("created_at"), str):
                raise OfficeRevisionIntegrityError("Office render evidence index entry is invalid")
            evidence_revision_id = metadata.get("revision_id")
            try:
                evidence_revision_id = _validate_revision_id(evidence_revision_id)
            except OfficeRevisionError as exc:
                raise OfficeRevisionIntegrityError("Office render evidence index revision is invalid") from exc
            if evidence_revision_id not in canonical_revision_ids:
                continue
            if revision_id is None or evidence_revision_id == revision_id:
                candidates.append((metadata["created_at"], evidence_id))
        candidates.sort(reverse=True)
        return [self.load_render_evidence(project_id, evidence_id) for _created_at, evidence_id in candidates[:limit]]

    def resolve_latest_render_set(
        self,
        project_id: str,
        revision_id: str,
    ) -> OfficeResolvedRenderEvidenceSet:
        """Resolve the newest coherent evidence set for one canonical revision."""

        project_id = _validate_project_id(project_id)
        revision_id = _validate_revision_id(revision_id)
        revision = self.load_project_revision(project_id, revision_id)
        evidence = self.list_render_evidence(
            project_id,
            revision_id=revision_id,
            limit=_MAX_RENDER_EVIDENCE_LIST_LIMIT,
        )
        return resolve_render_evidence_set(revision, evidence)

    def _verified_render_set(
        self,
        *,
        project_id: str,
        revision: dict[str, Any],
        evidence_ids: Sequence[str],
    ) -> dict[str, Any]:
        if not evidence_ids or len(evidence_ids) > _MAX_REVIEW_EVIDENCE:
            raise OfficeRevisionError(f"Office project review requires between 1 and {_MAX_REVIEW_EVIDENCE} render evidence records")
        normalized_ids = [_validate_evidence_id(evidence_id) for evidence_id in evidence_ids]
        if len(set(normalized_ids)) != len(normalized_ids):
            raise OfficeRevisionError("Office project review evidence IDs must be unique")

        expected_identity: tuple[Any, ...] | None = None
        records: list[tuple[int, int, str, str]] = []
        pages: dict[int, str] = {}
        for evidence_id in normalized_ids:
            evidence = self.load_render_evidence(project_id, evidence_id)
            manifest = evidence["render_manifest"]
            source = evidence["source"]
            if evidence["revision_id"] != revision["revision_id"] or source != {
                "sha256": revision["artifact"]["sha256"],
                "size_bytes": revision["artifact"]["size_bytes"],
            }:
                raise OfficeRevisionConflictError("Office project review evidence does not match the selected revision")
            identity = (
                source["sha256"],
                source["size_bytes"],
                manifest["page_count"],
                manifest["renderer"],
                manifest["renderer_version"],
                manifest["pdfium_version"],
                manifest["pipeline_fingerprint"],
                manifest["dpi"],
            )
            if expected_identity is not None and identity != expected_identity:
                raise OfficeRevisionConflictError("Office project review evidence comes from incompatible render pipelines")
            expected_identity = identity
            records.append(
                (
                    manifest["start_page"],
                    manifest["end_page"],
                    evidence["created_at"],
                    evidence_id,
                )
            )
            for preview in evidence["preview_pages"]:
                page = preview["page"]
                previous_sha256 = pages.get(page)
                if previous_sha256 is not None and previous_sha256 != preview["sha256"]:
                    raise OfficeRevisionConflictError("Office project review evidence conflicts for the same rendered page")
                pages[page] = preview["sha256"]

        if expected_identity is None:
            raise OfficeRevisionError("Office project review evidence is empty")
        page_count = expected_identity[2]
        if sorted(pages) != list(range(1, page_count + 1)):
            raise OfficeRevisionConflictError("Office project review requires complete render evidence for every page")
        records.sort()
        render_set = {
            "source": {
                "sha256": expected_identity[0],
                "size_bytes": expected_identity[1],
            },
            "page_count": page_count,
            "renderer": expected_identity[3],
            "renderer_version": expected_identity[4],
            "pdfium_version": expected_identity[5],
            "pipeline_fingerprint": expected_identity[6],
            "dpi": expected_identity[7],
            "evidence_ids": [record[3] for record in records],
            "pages": [{"page": page, "sha256": pages[page]} for page in range(1, page_count + 1)],
        }
        return {
            **render_set,
            "sha256": _sha256(_json_bytes(render_set)),
        }

    def _load_project_review_unlocked(
        self,
        project_id: str,
        review_id: str,
        *,
        canonical_revisions: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        review_id = _validate_review_id(review_id)
        review_dir = self._review_dir(project_id, review_id)
        if review_dir.is_symlink() or not review_dir.is_dir():
            raise OfficeRevisionError("Office project review was not found")
        review = _read_json_object(review_dir / "review.json")
        revision_id = review.get("revision_id")
        if (
            review.get("schema") != PROJECT_REVIEW_SCHEMA
            or review.get("project_id") != project_id
            or review.get("review_id") != review_id
            or review.get("status") not in {"approved", "changes_requested"}
            or not isinstance(review.get("created_at"), str)
            or not isinstance(review.get("reviewed_by"), str)
            or not isinstance(review.get("render_set"), dict)
        ):
            raise OfficeRevisionIntegrityError("Office project review identity is invalid")
        try:
            revision_id = _validate_revision_id(revision_id)
            _bounded_context_text(review.get("reviewed_by"), field_name="review actor")
            _bounded_context_text(review.get("note"), field_name="review note")
        except OfficeRevisionError as exc:
            raise OfficeRevisionIntegrityError("Office project review metadata is invalid") from exc
        revision = next(
            (candidate for candidate in canonical_revisions if candidate["revision_id"] == revision_id),
            None,
        )
        if revision is None:
            raise OfficeRevisionIntegrityError("Office project review references a non-canonical revision")
        if review.get("artifact") != revision["artifact"]:
            raise OfficeRevisionIntegrityError("Office project review artifact identity is invalid")
        render_set = review["render_set"]
        evidence_ids = render_set.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            raise OfficeRevisionIntegrityError("Office project review render set is invalid")
        try:
            expected_render_set = self._verified_render_set(
                project_id=project_id,
                revision=revision,
                evidence_ids=evidence_ids,
            )
        except OfficeRevisionError as exc:
            raise OfficeRevisionIntegrityError("Office project review render evidence is invalid") from exc
        if render_set != expected_render_set:
            raise OfficeRevisionIntegrityError("Office project review render set failed integrity checks")
        return review

    def commit_project_review(
        self,
        *,
        project_id: str,
        revision_id: str,
        evidence_ids: Sequence[str],
        status: str,
        reviewed_by: str,
        note: str | None = None,
    ) -> OfficeProjectReviewCommit:
        """Commit one immutable visual-review decision for exact page evidence."""

        project_id = _validate_project_id(project_id)
        revision_id = _validate_revision_id(revision_id)
        if status not in {"approved", "changes_requested"}:
            raise OfficeRevisionError("Office project review status is invalid")
        reviewed_by = _bounded_context_text(reviewed_by, field_name="review actor") or ""
        note = _bounded_context_text(note, field_name="review note")
        project_dir = self._project_dir(project_id)
        if project_dir.is_symlink() or not project_dir.is_dir():
            raise OfficeRevisionError("Office project was not found")
        with _exclusive_file_lock(project_dir / ".lock"):
            project = self._load_project_unlocked(project_id)
            canonical = self._load_canonical_revision_chain_unlocked(project_id, project)
            revision = next(
                (candidate for candidate in canonical if candidate["revision_id"] == revision_id),
                None,
            )
            if revision is None:
                raise OfficeRevisionError("Office revision was not found in the project history")
            render_set = self._verified_render_set(
                project_id=project_id,
                revision=revision,
                evidence_ids=evidence_ids,
            )
            latest_render_set = self.resolve_latest_render_set(
                project_id,
                revision_id,
            )
            if not latest_render_set.complete or tuple(render_set["evidence_ids"]) != latest_render_set.evidence_ids:
                raise OfficeRevisionConflictError("Office project review requires the latest complete render evidence")
            reviews_dir = project_dir / "reviews"
            reviews_dir.mkdir(exist_ok=True)
            review_id = self._next_review_id(reviews_dir)
            staging = reviews_dir / f".s-{uuid4().hex[:12]}"
            created_at = self._timestamp()
            review = {
                "schema": PROJECT_REVIEW_SCHEMA,
                "review_id": review_id,
                "project_id": project_id,
                "revision_id": revision_id,
                "created_at": created_at,
                "status": status,
                "reviewed_by": reviewed_by,
                "note": note,
                "artifact": revision["artifact"],
                "render_set": render_set,
            }
            try:
                staging.mkdir()
                _write_bytes_exclusive(staging / "review.json", _json_bytes(review))
                _sync_directory(staging)
                os.rename(staging, reviews_dir / review_id)
                _sync_directory(reviews_dir)
            except Exception:
                _safe_cleanup_staging(staging, reviews_dir)
                raise
        return OfficeProjectReviewCommit(
            project_id=project_id,
            revision_id=revision_id,
            review_id=review_id,
            status=status,
            evidence_ids=tuple(render_set["evidence_ids"]),
            page_count=render_set["page_count"],
        )

    def load_project_review(self, project_id: str, review_id: str) -> dict[str, Any]:
        project_id = _validate_project_id(project_id)
        project = self._load_project_unlocked(project_id)
        canonical = self._load_canonical_revision_chain_unlocked(project_id, project)
        return self._load_project_review_unlocked(
            project_id,
            review_id,
            canonical_revisions=canonical,
        )

    def list_project_reviews(
        self,
        project_id: str,
        *,
        revision_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        project_id = _validate_project_id(project_id)
        if revision_id is not None:
            revision_id = _validate_revision_id(revision_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_REVIEW_LIST_LIMIT:
            raise OfficeRevisionError(f"Office review limit must be between 1 and {_MAX_REVIEW_LIST_LIMIT}")
        project = self._load_project_unlocked(project_id)
        canonical = self._load_canonical_revision_chain_unlocked(project_id, project)
        reviews_dir = self._project_dir(project_id) / "reviews"
        if not reviews_dir.exists():
            return []
        if reviews_dir.is_symlink() or not reviews_dir.is_dir():
            raise OfficeRevisionIntegrityError("Office project review directory is unsafe")
        candidates: list[tuple[str, str]] = []
        scanned = 0
        for entry in reviews_dir.iterdir():
            if entry.name.startswith("."):
                continue
            scanned += 1
            if scanned > _MAX_REVIEW_RECORDS:
                raise OfficeRevisionIntegrityError("Office project review index exceeds the supported limit")
            review_id = _validate_review_id(entry.name)
            if entry.is_symlink() or not entry.is_dir():
                raise OfficeRevisionIntegrityError("Office project review entry is unsafe")
            review = _read_json_object(entry / "review.json")
            if review.get("schema") != PROJECT_REVIEW_SCHEMA or review.get("project_id") != project_id or review.get("review_id") != review_id or not isinstance(review.get("created_at"), str):
                raise OfficeRevisionIntegrityError("Office project review index entry is invalid")
            if revision_id is None or review.get("revision_id") == revision_id:
                candidates.append((review["created_at"], review_id))
        candidates.sort(reverse=True)
        return [
            self._load_project_review_unlocked(
                project_id,
                review_id,
                canonical_revisions=canonical,
            )
            for _created_at, review_id in candidates[:limit]
        ]

    def _load_final_selection_unlocked(
        self,
        project_id: str,
        selection_id: str,
        *,
        project: dict[str, Any],
        canonical_revisions: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        selection_id = _validate_final_selection_id(selection_id)
        selection_dir = self._final_selection_dir(project_id, selection_id)
        if selection_dir.is_symlink() or not selection_dir.is_dir():
            raise OfficeRevisionError("Office final selection was not found")
        selection = _read_json_object(selection_dir / "selection.json")
        if selection.get("schema") != FINAL_SELECTION_SCHEMA or selection.get("selection_id") != selection_id or selection.get("project_id") != project_id or not isinstance(selection.get("created_at"), str):
            raise OfficeRevisionIntegrityError("Office final selection identity is invalid")
        revision_id = _validate_revision_id(selection.get("revision_id"))
        review_id = _validate_review_id(selection.get("review_id"))
        revision = next(
            (candidate for candidate in canonical_revisions if candidate["revision_id"] == revision_id),
            None,
        )
        if revision is None or selection.get("artifact") != revision["artifact"]:
            raise OfficeRevisionIntegrityError("Office final selection artifact is invalid")
        review = self._load_project_review_unlocked(
            project_id,
            review_id,
            canonical_revisions=canonical_revisions,
        )
        if review["revision_id"] != revision_id or review["status"] != "approved":
            raise OfficeRevisionIntegrityError("Office final selection review is invalid")
        if selection.get("review_render_set_sha256") != review["render_set"]["sha256"]:
            raise OfficeRevisionIntegrityError("Office final selection render binding is invalid")
        return selection

    def commit_final_selection(
        self,
        *,
        project_id: str,
        revision_id: str,
        review_id: str,
        expected_current_revision_id: str,
    ) -> OfficeFinalSelectionCommit:
        """Select one approved canonical revision as final without changing current."""

        project_id = _validate_project_id(project_id)
        revision_id = _validate_revision_id(revision_id)
        review_id = _validate_review_id(review_id)
        expected_current_revision_id = _validate_revision_id(expected_current_revision_id)
        project_dir = self._project_dir(project_id)
        if project_dir.is_symlink() or not project_dir.is_dir():
            raise OfficeRevisionError("Office project was not found")
        with _exclusive_file_lock(project_dir / ".lock"):
            project = self._load_project_unlocked(project_id)
            if project["current_revision_id"] != expected_current_revision_id:
                raise OfficeRevisionConflictError("Office project has a newer current revision; reload before selecting a final artifact")
            canonical = self._load_canonical_revision_chain_unlocked(project_id, project)
            revision = next(
                (candidate for candidate in canonical if candidate["revision_id"] == revision_id),
                None,
            )
            if revision is None:
                raise OfficeRevisionError("Office revision was not found in the project history")
            review = self._load_project_review_unlocked(
                project_id,
                review_id,
                canonical_revisions=canonical,
            )
            latest_reviews = self.list_project_reviews(
                project_id,
                revision_id=revision_id,
                limit=1,
            )
            if review["revision_id"] != revision_id or review["status"] != "approved" or not latest_reviews or latest_reviews[0]["review_id"] != review_id:
                raise OfficeRevisionConflictError("Office final selection requires the latest approved review for that revision")
            latest_render_set = self.resolve_latest_render_set(
                project_id,
                revision_id,
            )
            if not latest_render_set.complete or tuple(review["render_set"]["evidence_ids"]) != latest_render_set.evidence_ids:
                raise OfficeRevisionConflictError("Office final selection requires a review of the latest complete render evidence")
            finals_dir = project_dir / "finals"
            finals_dir.mkdir(exist_ok=True)
            selection_id = self._next_final_selection_id(finals_dir)
            staging = finals_dir / f".s-{uuid4().hex[:12]}"
            selection = {
                "schema": FINAL_SELECTION_SCHEMA,
                "selection_id": selection_id,
                "project_id": project_id,
                "revision_id": revision_id,
                "review_id": review_id,
                "created_at": self._timestamp(),
                "artifact": revision["artifact"],
                "review_render_set_sha256": review["render_set"]["sha256"],
            }
            published = False
            try:
                staging.mkdir()
                _write_bytes_exclusive(staging / "selection.json", _json_bytes(selection))
                _sync_directory(staging)
                os.rename(staging, finals_dir / selection_id)
                published = True
                _sync_directory(finals_dir)
                _atomic_replace_json(
                    project_dir / "project.json",
                    {
                        **project,
                        "updated_at": selection["created_at"],
                        "final_selection_id": selection_id,
                        "final_revision_id": revision_id,
                        "final_artifact_sha256": revision["artifact"]["sha256"],
                    },
                )
            except Exception:
                if published:
                    logger.error(
                        "Office final selection %s was published but not selected by the project",
                        selection_id,
                    )
                else:
                    _safe_cleanup_staging(staging, finals_dir)
                raise
        return OfficeFinalSelectionCommit(
            project_id=project_id,
            selection_id=selection_id,
            revision_id=revision_id,
            review_id=review_id,
            artifact_sha256=revision["artifact"]["sha256"],
        )

    def load_final_selection(self, project_id: str) -> dict[str, Any] | None:
        project_id = _validate_project_id(project_id)
        project = self._load_project_unlocked(project_id)
        selection_id = project.get("final_selection_id")
        if selection_id is None:
            return None
        canonical = self._load_canonical_revision_chain_unlocked(project_id, project)
        return self._load_final_selection_unlocked(
            project_id,
            selection_id,
            project=project,
            canonical_revisions=canonical,
        )

    def read_final_artifact(self, project_id: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        selection = self.load_final_selection(project_id)
        if selection is None:
            raise OfficeRevisionError("Office project has no selected final artifact")
        revision, data = self.read_revision_artifact(project_id, selection["revision_id"])
        return selection, revision, data

    def commit_edit(
        self,
        *,
        source: bytes,
        result: bytes,
        suffix: str,
        source_path: str,
        output_path: str,
        thread_id: str | None,
        receipt: dict[str, Any],
        source_validation: dict[str, Any],
        result_validation: dict[str, Any],
        project_id: str | None = None,
        parent_revision_id: str | None = None,
        template_resource: dict[str, Any] | None = None,
        template_policy: dict[str, Any] | None = None,
    ) -> OfficeRevisionCommit:
        """Create a project or append one edit using optimistic parent matching."""

        if (project_id is None) != (parent_revision_id is None):
            raise OfficeRevisionError("project_id and parent_revision_id must be provided together")
        format_name = _normalize_format(suffix)
        source_path = _bounded_context_text(source_path, field_name="source path") or ""
        output_path = _bounded_context_text(output_path, field_name="output path") or ""
        thread_id = _bounded_context_text(thread_id, field_name="thread ID")
        template_resource = _normalize_template_resource(template_resource)
        template_policy = _normalize_template_policy(
            template_policy,
            template_resource=template_resource,
        )
        source_sha256, result_sha256 = self._verify_evidence(
            source=source,
            result=result,
            format_name=format_name,
            receipt=receipt,
            source_validation=source_validation,
            result_validation=result_validation,
        )
        if project_id is None and template_resource is not None:
            if template_policy is None:
                raise OfficeRevisionError("Office template project creation requires policy evidence")
            if template_resource["source_sha256"] != source_sha256:
                raise OfficeRevisionConflictError("Office template project baseline does not match the published source")
        elif project_id is None and template_policy is not None:
            raise OfficeRevisionError("Office template policy requires a template resource")
        if project_id is None:
            return self._create_project(
                source=source,
                result=result,
                format_name=format_name,
                source_sha256=source_sha256,
                result_sha256=result_sha256,
                source_path=source_path,
                output_path=output_path,
                thread_id=thread_id,
                receipt=receipt,
                source_validation=source_validation,
                result_validation=result_validation,
                template_resource=template_resource,
                template_policy=template_policy,
            )
        return self._append_revision(
            kind="edit",
            project_id=_validate_project_id(project_id),
            parent_revision_id=_validate_revision_id(parent_revision_id or ""),
            restored_from_revision_id=None,
            source=source,
            result=result,
            format_name=format_name,
            source_sha256=source_sha256,
            result_sha256=result_sha256,
            source_path=source_path,
            output_path=output_path,
            thread_id=thread_id,
            receipt=receipt,
            result_validation=result_validation,
            template_resource=template_resource,
            template_policy=template_policy,
        )

    def commit_generation(
        self,
        *,
        artifact: bytes,
        output_path: str,
        thread_id: str | None,
        intent: Mapping[str, Any],
        receipt: Mapping[str, Any],
        preflight: Mapping[str, Any],
        validation: dict[str, Any],
    ) -> OfficeRevisionCommit:
        """Publish one native generated PPTX as a new project's initial revision."""

        output_path = _bounded_context_text(output_path, field_name="output path") or ""
        thread_id = _bounded_context_text(thread_id, field_name="thread ID")
        if validation.get("valid") is not True or validation.get("format") != "pptx":
            raise OfficeRevisionIntegrityError("Office generation package validation is incomplete")
        validate_generation_evidence(
            artifact=artifact,
            intent=intent,
            receipt=receipt,
            preflight=preflight,
        )
        _json_bytes(dict(intent))
        _json_bytes(dict(receipt))
        _json_bytes(dict(preflight))
        artifact_sha256 = _sha256(artifact)

        self.projects_dir.mkdir(parents=True, exist_ok=True)
        with _exclusive_file_lock(self.projects_dir / ".create.lock"):
            project_id: str | None = None
            for _ in range(_ID_GENERATION_ATTEMPTS):
                candidate = _validate_project_id(self._project_id_factory())
                if not self._project_dir(candidate).exists():
                    project_id = candidate
                    break
            if project_id is None:
                raise OfficeRevisionError("Could not allocate a unique Office project ID")

            project_dir = self._project_dir(project_id)
            staging = self.projects_dir / f".s-{uuid4().hex[:12]}"
            revisions_dir = staging / "revisions"
            created_at = self._timestamp()
            try:
                revisions_dir.mkdir(parents=True)
                revision_id = self._next_revision_id(revisions_dir)
                metadata = self._generation_metadata(
                    project_id=project_id,
                    revision_id=revision_id,
                    created_at=created_at,
                    artifact=artifact,
                    artifact_sha256=artifact_sha256,
                    output_path=output_path,
                    thread_id=thread_id,
                    intent=intent,
                    receipt=receipt,
                    preflight=preflight,
                    validation=validation,
                )
                self._write_revision(
                    revisions_dir / revision_id,
                    format_name="pptx",
                    artifact=artifact,
                    metadata=metadata,
                )
                project = {
                    "schema": PROJECT_SCHEMA,
                    "project_id": project_id,
                    "format": "pptx",
                    "created_at": created_at,
                    "updated_at": created_at,
                    "primary_thread_id": thread_id,
                    "current_revision_id": revision_id,
                    "current_artifact_sha256": artifact_sha256,
                    "revision_count": 1,
                }
                _write_bytes_exclusive(staging / "project.json", _json_bytes(project))
                _sync_directory(revisions_dir)
                _sync_directory(staging)
                os.rename(staging, project_dir)
                _sync_directory(self.projects_dir)
            except Exception:
                _safe_cleanup_staging(staging, self.projects_dir)
                raise

        return OfficeRevisionCommit(
            project_id=project_id,
            revision_id=revision_id,
            parent_revision_id=None,
            sequence=1,
            project_created=True,
            revision_count=1,
            artifact_sha256=artifact_sha256,
            artifact_size_bytes=len(artifact),
        )

    def commit_restore(
        self,
        *,
        project_id: str,
        parent_revision_id: str,
        restored_from_revision_id: str,
        source: bytes,
        result: bytes,
        suffix: str,
        source_path: str,
        output_path: str,
        thread_id: str | None,
        receipt: dict[str, Any],
        source_validation: dict[str, Any],
        result_validation: dict[str, Any],
        template_resource: dict[str, Any] | None = None,
        template_policy: dict[str, Any] | None = None,
    ) -> OfficeRevisionCommit:
        """Append a new revision whose exact bytes come from an older canonical save point."""

        project_id = _validate_project_id(project_id)
        parent_revision_id = _validate_revision_id(parent_revision_id)
        restored_from_revision_id = _validate_revision_id(restored_from_revision_id)
        if restored_from_revision_id == parent_revision_id:
            raise OfficeRevisionConflictError("Office restore target is already the current revision")
        format_name = _normalize_format(suffix)
        source_path = _bounded_context_text(source_path, field_name="source path") or ""
        output_path = _bounded_context_text(output_path, field_name="output path") or ""
        thread_id = _bounded_context_text(thread_id, field_name="thread ID")
        template_resource = _normalize_template_resource(template_resource)
        template_policy = _normalize_template_policy(
            template_policy,
            template_resource=template_resource,
        )
        source_sha256, result_sha256 = self._verify_evidence(
            source=source,
            result=result,
            format_name=format_name,
            receipt=receipt,
            source_validation=source_validation,
            result_validation=result_validation,
        )
        if source_sha256 == result_sha256:
            raise OfficeRevisionConflictError("Office restore would not change the current artifact")
        return self._append_revision(
            kind="restore",
            project_id=project_id,
            parent_revision_id=parent_revision_id,
            restored_from_revision_id=restored_from_revision_id,
            source=source,
            result=result,
            format_name=format_name,
            source_sha256=source_sha256,
            result_sha256=result_sha256,
            source_path=source_path,
            output_path=output_path,
            thread_id=thread_id,
            receipt=receipt,
            result_validation=result_validation,
            template_resource=template_resource,
            template_policy=template_policy,
        )

    def _create_project(
        self,
        *,
        source: bytes,
        result: bytes,
        format_name: str,
        source_sha256: str,
        result_sha256: str,
        source_path: str,
        output_path: str,
        thread_id: str | None,
        receipt: dict[str, Any],
        source_validation: dict[str, Any],
        result_validation: dict[str, Any],
        template_resource: dict[str, Any] | None,
        template_policy: dict[str, Any] | None,
    ) -> OfficeRevisionCommit:
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        with _exclusive_file_lock(self.projects_dir / ".create.lock"):
            project_id: str | None = None
            for _ in range(_ID_GENERATION_ATTEMPTS):
                candidate = _validate_project_id(self._project_id_factory())
                if not self._project_dir(candidate).exists():
                    project_id = candidate
                    break
            if project_id is None:
                raise OfficeRevisionError("Could not allocate a unique Office project ID")

            project_dir = self._project_dir(project_id)
            staging = self.projects_dir / f".s-{uuid4().hex[:12]}"
            revisions_dir = staging / "revisions"
            created_at = self._timestamp()
            try:
                revisions_dir.mkdir(parents=True)
                baseline_revision_id = self._next_revision_id(revisions_dir)
                revision_id = self._next_revision_id(
                    revisions_dir,
                    reserved={baseline_revision_id},
                )
                baseline_metadata = self._baseline_metadata(
                    project_id=project_id,
                    revision_id=baseline_revision_id,
                    created_at=created_at,
                    format_name=format_name,
                    source=source,
                    source_sha256=source_sha256,
                    source_path=source_path,
                    thread_id=thread_id,
                    source_validation=source_validation,
                    template_resource=template_resource,
                )
                edit_metadata = self._edit_metadata(
                    project_id=project_id,
                    revision_id=revision_id,
                    parent_revision_id=baseline_revision_id,
                    sequence=2,
                    created_at=created_at,
                    format_name=format_name,
                    source=source,
                    result=result,
                    source_sha256=source_sha256,
                    result_sha256=result_sha256,
                    source_path=source_path,
                    output_path=output_path,
                    thread_id=thread_id,
                    receipt=receipt,
                    result_validation=result_validation,
                    template_resource=template_resource,
                    template_policy=template_policy,
                )
                self._write_revision(
                    revisions_dir / baseline_revision_id,
                    format_name=format_name,
                    artifact=source,
                    metadata=baseline_metadata,
                )
                self._write_revision(
                    revisions_dir / revision_id,
                    format_name=format_name,
                    artifact=result,
                    metadata=edit_metadata,
                )
                project = {
                    "schema": PROJECT_SCHEMA,
                    "project_id": project_id,
                    "format": format_name,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "primary_thread_id": thread_id,
                    "current_revision_id": revision_id,
                    "current_artifact_sha256": result_sha256,
                    "revision_count": 2,
                }
                if template_resource is not None:
                    project["resource_versions"] = {
                        "template": template_resource,
                        "brand": None,
                    }
                _write_bytes_exclusive(staging / "project.json", _json_bytes(project))
                _sync_directory(revisions_dir)
                _sync_directory(staging)
                os.rename(staging, project_dir)
                _sync_directory(self.projects_dir)
            except Exception:
                _safe_cleanup_staging(staging, self.projects_dir)
                raise

        return OfficeRevisionCommit(
            project_id=project_id,
            revision_id=revision_id,
            parent_revision_id=baseline_revision_id,
            sequence=2,
            project_created=True,
            revision_count=2,
            artifact_sha256=result_sha256,
            artifact_size_bytes=len(result),
            baseline_revision_id=baseline_revision_id,
        )

    def _append_revision(
        self,
        *,
        kind: str,
        project_id: str,
        parent_revision_id: str,
        restored_from_revision_id: str | None,
        source: bytes,
        result: bytes,
        format_name: str,
        source_sha256: str,
        result_sha256: str,
        source_path: str,
        output_path: str,
        thread_id: str | None,
        receipt: dict[str, Any],
        result_validation: dict[str, Any],
        template_resource: dict[str, Any] | None,
        template_policy: dict[str, Any] | None,
    ) -> OfficeRevisionCommit:
        if kind not in {"edit", "restore"} or (kind == "restore") != (restored_from_revision_id is not None):
            raise OfficeRevisionError("Office revision change kind is invalid")
        project_dir = self._project_dir(project_id)
        if project_dir.is_symlink() or not project_dir.is_dir():
            raise OfficeRevisionError("Office project was not found")
        with _exclusive_file_lock(project_dir / ".lock"):
            project = self._load_project_unlocked(project_id)
            if project.get("format") != format_name:
                raise OfficeRevisionConflictError("Office project format does not match the edit source")
            current_revision_id = project.get("current_revision_id")
            if current_revision_id != parent_revision_id:
                raise OfficeRevisionConflictError("Office project has a newer current revision; inspect it and retry from that exact parent")
            current_revision = self._load_revision_unlocked(project_id, parent_revision_id)
            current_resources = current_revision.get("resource_versions")
            current_template_raw = current_resources.get("template") if isinstance(current_resources, dict) else None
            try:
                current_template = _normalize_template_resource(current_template_raw)
            except OfficeRevisionError as exc:
                raise OfficeRevisionIntegrityError("Current Office revision template resource is invalid") from exc
            if template_resource != current_template:
                raise OfficeRevisionConflictError("Office project template version cannot be attached, removed, or changed")
            if current_template is not None and template_policy is None:
                raise OfficeRevisionConflictError("Office template project edit requires slot policy evidence")
            current_artifact = current_revision.get("artifact")
            if not isinstance(current_artifact, dict):
                raise OfficeRevisionIntegrityError("Current Office revision artifact metadata is invalid")
            if current_artifact.get("sha256") != project.get("current_artifact_sha256"):
                raise OfficeRevisionIntegrityError("Office project current artifact pointer failed integrity checks")
            if current_artifact.get("sha256") != source_sha256 or current_artifact.get("size_bytes") != len(source):
                raise OfficeRevisionConflictError("Office edit source does not match the current project revision bytes")
            revision_count = project.get("revision_count")
            if not isinstance(revision_count, int) or revision_count < 1 or current_revision.get("sequence") != revision_count:
                raise OfficeRevisionIntegrityError("Office project revision sequence is invalid")
            if kind == "restore":
                canonical = self._load_canonical_revision_chain_unlocked(project_id, project)
                restored_from = next(
                    (candidate for candidate in canonical if candidate["revision_id"] == restored_from_revision_id),
                    None,
                )
                if (
                    restored_from is None
                    or restored_from["revision_id"] == parent_revision_id
                    or restored_from["artifact"] != {"filename": f"artifact.{format_name}", "sha256": result_sha256, "size_bytes": len(result)}
                    or restored_from.get("resource_versions") != current_revision.get("resource_versions")
                ):
                    raise OfficeRevisionConflictError("Office restore target is not an older canonical artifact in this project")

            revisions_dir = project_dir / "revisions"
            revision_id = self._next_revision_id(revisions_dir)
            sequence = revision_count + 1
            created_at = self._timestamp()
            metadata = (
                self._edit_metadata(
                    project_id=project_id,
                    revision_id=revision_id,
                    parent_revision_id=parent_revision_id,
                    sequence=sequence,
                    created_at=created_at,
                    format_name=format_name,
                    source=source,
                    result=result,
                    source_sha256=source_sha256,
                    result_sha256=result_sha256,
                    source_path=source_path,
                    output_path=output_path,
                    thread_id=thread_id,
                    receipt=receipt,
                    result_validation=result_validation,
                    template_resource=current_template,
                    template_policy=template_policy,
                )
                if kind == "edit"
                else self._restore_metadata(
                    project_id=project_id,
                    revision_id=revision_id,
                    parent_revision_id=parent_revision_id,
                    restored_from_revision_id=restored_from_revision_id or "",
                    sequence=sequence,
                    created_at=created_at,
                    format_name=format_name,
                    source=source,
                    result=result,
                    source_sha256=source_sha256,
                    result_sha256=result_sha256,
                    source_path=source_path,
                    output_path=output_path,
                    thread_id=thread_id,
                    receipt=receipt,
                    result_validation=result_validation,
                    template_resource=current_template,
                    template_policy=template_policy,
                )
            )
            staging = revisions_dir / f".s-{uuid4().hex[:12]}"
            published = False
            try:
                self._write_revision(
                    staging,
                    format_name=format_name,
                    artifact=result,
                    metadata=metadata,
                )
                os.rename(staging, revisions_dir / revision_id)
                published = True
                _sync_directory(revisions_dir)
                updated_project = {
                    **project,
                    "updated_at": created_at,
                    "current_revision_id": revision_id,
                    "current_artifact_sha256": result_sha256,
                    "revision_count": sequence,
                }
                _atomic_replace_json(project_dir / "project.json", updated_project)
            except Exception:
                if published:
                    logger.error(
                        "Office revision %s was published but not selected as project current",
                        revision_id,
                    )
                else:
                    _safe_cleanup_staging(staging, revisions_dir)
                raise

        return OfficeRevisionCommit(
            project_id=project_id,
            revision_id=revision_id,
            parent_revision_id=parent_revision_id,
            sequence=sequence,
            project_created=False,
            revision_count=sequence,
            artifact_sha256=result_sha256,
            artifact_size_bytes=len(result),
        )
