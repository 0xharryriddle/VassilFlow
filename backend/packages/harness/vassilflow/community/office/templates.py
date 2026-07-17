"""Trusted personal template storage for fixed-structure PPTX workflows."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import struct
import threading
import weakref
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Literal
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows-only branch
    fcntl = None  # type: ignore[assignment]
    import msvcrt

from .engine import office_engine
from .errors import (
    OfficeTemplateConflictError,
    OfficeTemplateError,
    OfficeTemplateIntegrityError,
)
from .models import (
    OfficeEditOperation,
    PptxPictureSourceReplacementOperation,
    PptxPictureTarget,
    PptxTextReplacement,
)
from .pptx import validate_pptx_renderable
from .receipt import SemanticTarget
from .render import OfficeRenderResult

TEMPLATE_SCHEMA = "vassilflow.office.template.v1"
TEMPLATE_VERSION_SCHEMA = "vassilflow.office.template_version.v1"
TEMPLATE_INSPECTION_SCHEMA = "vassilflow.office.template_inspection.v1"
TEMPLATE_PREFLIGHT_SCHEMA = "vassilflow.office.template_preflight.v1"
TEMPLATE_RENDER_EVIDENCE_SCHEMA = "vassilflow.office.template_render_evidence.v1"

_TEMPLATE_ID_RE = re.compile(r"^oft_[0-9a-f]{32}$")
_TEMPLATE_RENDER_ID_RE = re.compile(r"^otr_[0-9a-f]{32}$")
_SLOT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TEMPLATE_STATUSES = frozenset({"draft", "published"})
_MAX_SOURCE_BYTES = 50 * 1024 * 1024
_MAX_METADATA_BYTES = 16 * 1024 * 1024
_MAX_TITLE_CHARS = 200
_MAX_FILENAME_CHARS = 255
_MAX_LABEL_CHARS = 120
_MAX_TEXT_SLOT_CHARS = 4_000
_MAX_SLOTS = 100
_MAX_TEMPLATE_RECORDS = 10_000
_MAX_TEMPLATE_LIST_LIMIT = 500
_MAX_VERSION = 999_999
_MAX_RENDER_BATCH_PAGES = 12
_MAX_RENDER_TOTAL_BYTES = 150 * 1024 * 1024
_MAX_RENDER_PAGE_BYTES = 12 * 1024 * 1024
_ID_GENERATION_ATTEMPTS = 16
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

logger = logging.getLogger(__name__)

_LOCKS: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
_LOCKS_GUARD = threading.Lock()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _new_template_id() -> str:
    return f"oft_{uuid4().hex}"


def _new_template_render_id() -> str:
    return f"otr_{uuid4().hex}"


def _validate_template_id(template_id: str) -> str:
    if not isinstance(template_id, str) or _TEMPLATE_ID_RE.fullmatch(template_id) is None:
        raise OfficeTemplateError("Invalid Office template ID")
    return template_id


def _validate_version(version: int) -> int:
    if not isinstance(version, int) or isinstance(version, bool) or not 1 <= version <= _MAX_VERSION:
        raise OfficeTemplateError("Invalid Office template version")
    return version


def _validate_template_render_id(evidence_id: str) -> str:
    if not isinstance(evidence_id, str) or _TEMPLATE_RENDER_ID_RE.fullmatch(evidence_id) is None:
        raise OfficeTemplateError("Invalid Office template render evidence ID")
    return evidence_id


def _version_directory_name(version: int) -> str:
    return f"v{_validate_version(version):06d}"


def _bounded_text(value: str, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise OfficeTemplateError(f"Office template {field_name} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise OfficeTemplateError(f"Office template {field_name} is invalid")
    if any(ord(character) < 32 for character in normalized):
        raise OfficeTemplateError(f"Office template {field_name} contains control characters")
    return normalized


def _display_filename(filename: str) -> str:
    normalized = _bounded_text(
        filename.replace("\\", "/"),
        field_name="filename",
        maximum=_MAX_FILENAME_CHARS,
    )
    display = PurePosixPath(normalized).name
    if display != normalized or PurePosixPath(display).suffix.lower() != ".pptx":
        raise OfficeTemplateError("Office Template V1 accepts a native .pptx filename only")
    return display


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
        raise OfficeTemplateError("Office template metadata is not valid JSON") from exc
    if len(data) > _MAX_METADATA_BYTES:
        raise OfficeTemplateError("Office template metadata exceeds the storage limit")
    return data


def _canonical_digest(payload: Any) -> str:
    try:
        data = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OfficeTemplateError("Office template evidence is not canonical JSON") from exc
    return _sha256(data)


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or not payload.startswith(_PNG_SIGNATURE) or payload[12:16] != b"IHDR":
        raise OfficeTemplateIntegrityError("Office template render preview is not a valid PNG")
    width, height = struct.unpack(">II", payload[16:24])
    if not 1 <= width <= 10_000 or not 1 <= height <= 10_000:
        raise OfficeTemplateIntegrityError("Office template render preview dimensions are invalid")
    return width, height


def _read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise OfficeTemplateIntegrityError("Office template metadata is missing or unsafe")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise OfficeTemplateIntegrityError("Office template metadata could not be read") from exc
    if len(data) > _MAX_METADATA_BYTES:
        raise OfficeTemplateIntegrityError("Office template metadata exceeds the storage limit")
    try:
        payload = json.loads(
            data,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise OfficeTemplateIntegrityError("Office template metadata is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise OfficeTemplateIntegrityError("Office template metadata must be a JSON object")
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
        raise OfficeTemplateIntegrityError("Office template attempted to replace immutable data") from exc


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
            logger.warning("Could not remove staged Office template metadata", exc_info=True)


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
            logger.error("Refused to clean unexpected Office template staging path")
            return
        if path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.exists():
            shutil.rmtree(path)
    except OSError:
        logger.warning("Could not remove staged Office template data", exc_info=True)


def _new_staging_path(parent: Path) -> Path:
    for _ in range(_ID_GENERATION_ATTEMPTS):
        candidate = parent / f".s-{uuid4().hex[:12]}"
        if not candidate.exists():
            return candidate
    raise OfficeTemplateError("Could not allocate Office template staging storage")


def _structure_descriptor(inspection: dict[str, Any]) -> dict[str, Any]:
    slides = inspection.get("slides")
    if not isinstance(slides, list):
        raise OfficeTemplateError("Office template inspection has no slide inventory")
    slide_records: list[dict[str, Any]] = []
    for slide in slides:
        if not isinstance(slide, dict) or not isinstance(slide.get("objects"), list):
            raise OfficeTemplateError("Office template inspection has an invalid object inventory")
        objects: list[dict[str, Any]] = []
        for item in slide["objects"]:
            if not isinstance(item, dict):
                raise OfficeTemplateError("Office template inspection contains invalid object metadata")
            objects.append(
                {
                    "path": item.get("path"),
                    "parent_path": item.get("parent_path"),
                    "kind": item.get("kind"),
                    "id": item.get("id"),
                    "identity_source": item.get("identity_source"),
                    "name": item.get("name"),
                    "z_order": item.get("z_order"),
                    "geometry": item.get("geometry"),
                }
            )
        slide_records.append(
            {
                "index": slide.get("index"),
                "path": slide.get("path"),
                "part_name": slide.get("part_name"),
                "hidden": slide.get("hidden"),
                "objects": objects,
            }
        )
    return {
        "slide_count": inspection.get("slide_count"),
        "slide_size": inspection.get("slide_size"),
        "slides": slide_records,
    }


def _candidate_record(record: dict[str, Any]) -> dict[str, Any]:
    fingerprint = _canonical_digest(record)
    return {
        "candidate_id": f"otc_{fingerprint[:32]}",
        "source_fingerprint": fingerprint,
        **record,
    }


def _build_slot_candidates(inspection: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for slide in inspection.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_index = slide.get("index")
        objects = {item.get("path"): item for item in slide.get("objects", []) if isinstance(item, dict) and isinstance(item.get("path"), str)}
        for text_item in slide.get("text", []):
            if not isinstance(text_item, dict) or text_item.get("type") not in {"title", "text_box"}:
                continue
            path = text_item.get("path")
            text = text_item.get("text")
            item = objects.get(path)
            if (
                not isinstance(path, str)
                or not isinstance(text, str)
                or not text
                or len(text) > _MAX_TEXT_SLOT_CHARS
                or any(character in text for character in ("\r", "\n", "\t"))
                or text_item.get("truncated") is True
                or not isinstance(item, dict)
                or item.get("identity_source") != "cNvPr.id"
            ):
                continue
            try:
                PptxTextReplacement(paths=[path], find=text, replace=text)
            except ValueError:
                continue
            name = item.get("name") if isinstance(item.get("name"), str) else None
            candidates.append(
                _candidate_record(
                    {
                        "type": "text",
                        "path": path,
                        "slide_index": slide_index,
                        "default_label": name or f"Slide {slide_index} text",
                        "selector": {"path": path, "expected_text": text},
                        "source": {
                            "name": name,
                            "text": text,
                            "text_sha256": _sha256(text.encode("utf-8")),
                        },
                    }
                )
            )
        for item in objects.values():
            if item.get("kind") != "picture" or item.get("identity_source") != "cNvPr.id":
                continue
            path = item.get("path")
            source = item.get("source")
            if not isinstance(path, str) or not isinstance(source, dict):
                continue
            source_sha256 = source.get("sha256")
            name = item.get("name") if isinstance(item.get("name"), str) else None
            if not isinstance(source_sha256, str):
                continue
            try:
                target = PptxPictureTarget(
                    path=path,
                    expected_name=name,
                    expected_source_sha256=source_sha256,
                )
            except ValueError:
                continue
            candidates.append(
                _candidate_record(
                    {
                        "type": "picture",
                        "path": path,
                        "slide_index": slide_index,
                        "default_label": name or f"Slide {slide_index} picture",
                        "selector": target.model_dump(mode="json"),
                        "source": {
                            "name": name,
                            "sha256": source_sha256,
                            "content_type": source.get("content_type"),
                            "geometry": item.get("geometry"),
                        },
                    }
                )
            )
    type_order = {"text": 0, "picture": 1}
    candidates.sort(
        key=lambda item: (
            int(item["slide_index"]),
            type_order[str(item["type"])],
            str(item["path"]),
        )
    )
    return candidates


def _validate_complete_inspection(inspection: dict[str, Any]) -> None:
    slide_count = inspection.get("slide_count")
    if not isinstance(slide_count, int) or isinstance(slide_count, bool) or not 1 <= slide_count <= 50:
        raise OfficeTemplateError("Office Template V1 requires between 1 and 50 slides")
    if inspection.get("has_more") is not False or inspection.get("returned") != slide_count:
        raise OfficeTemplateError("Office Template V1 requires a complete slide inspection")
    if inspection.get("selected_objects_truncated") is True:
        raise OfficeTemplateError("Office template object inventory exceeds the mapping limit")
    for slide in inspection.get("slides", []):
        if not isinstance(slide, dict) or slide.get("objects_truncated") is True:
            raise OfficeTemplateError("Office template object inventory is incomplete")


@dataclass(frozen=True, slots=True)
class OfficeTemplateSlotDraft:
    """One owner-selected variable region resolved against trusted candidates."""

    key: str
    label: str
    type: Literal["text", "picture"]
    candidate_id: str
    required: bool = True
    max_length: int | None = None


@dataclass(frozen=True, slots=True)
class OfficeTemplateImportCommit:
    """Public identifiers for one imported personal template draft."""

    template_id: str
    version: int
    source_sha256: str
    source_size_bytes: int
    slot_candidate_count: int
    structure_fingerprint: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "version": self.version,
            "status": "draft",
            "source": {
                "sha256": self.source_sha256,
                "size_bytes": self.source_size_bytes,
            },
            "slot_candidate_count": self.slot_candidate_count,
            "structure_fingerprint": self.structure_fingerprint,
            "storage_scope": "trusted_user",
        }


@dataclass(frozen=True, slots=True)
class OfficeTemplateRenderCommit:
    """Public identity for one full-deck immutable template render."""

    template_id: str
    version: int
    evidence_id: str
    source_sha256: str
    page_count: int
    rendered_page_count: int
    pipeline_fingerprint: str
    visual_review_status: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "version": self.version,
            "render_evidence": {
                "schema": TEMPLATE_RENDER_EVIDENCE_SCHEMA,
                "evidence_id": self.evidence_id,
                "source_sha256": self.source_sha256,
                "page_count": self.page_count,
                "rendered_page_count": self.rendered_page_count,
                "pipeline_fingerprint": self.pipeline_fingerprint,
                "visual_review_status": self.visual_review_status,
            },
            "storage_scope": "trusted_user",
        }


class OfficeTemplateStore:
    """User-scoped template store with immutable source and source-derived evidence."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        template_id_factory: Callable[[], str] | None = None,
        render_id_factory: Callable[[], str] | None = None,
        renderer: Callable[..., OfficeRenderResult] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.templates_dir = self.root / "templates"
        self._clock = clock or (lambda: datetime.now(UTC))
        self._template_id_factory = template_id_factory or _new_template_id
        self._render_id_factory = render_id_factory or _new_template_render_id
        self._renderer = renderer or office_engine.render

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            raise OfficeTemplateError("Office template clock must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def _template_dir(self, template_id: str) -> Path:
        return self.templates_dir / _validate_template_id(template_id)

    def _draft_version_dir(self, template_id: str, version: int) -> Path:
        return self._template_dir(template_id) / "drafts" / _version_directory_name(version)

    def _published_version_dir(self, template_id: str, version: int) -> Path:
        return self._template_dir(template_id) / "versions" / _version_directory_name(version)

    def _selected_version_dir(
        self,
        template: dict[str, Any],
        version: int,
    ) -> Path:
        version = _validate_version(version)
        template_id = str(template["template_id"])
        if version in template["published_versions"]:
            return self._published_version_dir(template_id, version)
        if template["draft_version"] == version:
            return self._draft_version_dir(template_id, version)
        raise OfficeTemplateError("Office template version was not found")

    def _next_template_id(self) -> str:
        for _ in range(_ID_GENERATION_ATTEMPTS):
            template_id = _validate_template_id(self._template_id_factory())
            if not (self.templates_dir / template_id).exists():
                return template_id
        raise OfficeTemplateError("Could not allocate a unique Office template ID")

    def _next_render_id(self, renders_dir: Path) -> str:
        for _ in range(_ID_GENERATION_ATTEMPTS):
            evidence_id = _validate_template_render_id(self._render_id_factory())
            if not (renders_dir / evidence_id).exists():
                return evidence_id
        raise OfficeTemplateError("Could not allocate a unique Office template render evidence ID")

    @staticmethod
    def _require_safe_directory(path: Path, *, label: str) -> None:
        if path.is_symlink() or not path.is_dir():
            raise OfficeTemplateIntegrityError(f"Office template {label} is missing or unsafe")

    def _require_existing_template_dir(self, template_id: str) -> Path:
        template_dir = self._template_dir(template_id)
        if not template_dir.exists():
            raise OfficeTemplateError("Office template was not found")
        self._require_safe_directory(template_dir, label="directory")
        return template_dir

    def _load_template_unlocked(self, template_id: str) -> dict[str, Any]:
        template_id = _validate_template_id(template_id)
        template_dir = self._template_dir(template_id)
        self._require_safe_directory(template_dir, label="directory")
        payload = _read_json_object(template_dir / "template.json")
        if (
            payload.get("schema") != TEMPLATE_SCHEMA
            or payload.get("template_id") != template_id
            or payload.get("format") != "pptx"
            or payload.get("owner_scope") != "user"
            or not isinstance(payload.get("title"), str)
            or not isinstance(payload.get("created_at"), str)
            or not isinstance(payload.get("updated_at"), str)
            or not isinstance(payload.get("latest_version"), int)
            or (payload.get("draft_version") is not None and not isinstance(payload.get("draft_version"), int))
            or not isinstance(payload.get("published_versions"), list)
            or not isinstance(payload.get("archived"), bool)
        ):
            raise OfficeTemplateIntegrityError("Office template metadata is inconsistent")
        published_versions = payload["published_versions"]
        if (
            any(not isinstance(version, int) or isinstance(version, bool) or not 1 <= version <= payload["latest_version"] for version in published_versions)
            or len(set(published_versions)) != len(published_versions)
            or published_versions != sorted(published_versions)
        ):
            raise OfficeTemplateIntegrityError("Office template version index is invalid")
        return payload

    def _verify_render_evidence(
        self,
        *,
        version_dir: Path,
        template_id: str,
        version: int,
        source: dict[str, Any],
        evidence_id: str,
    ) -> dict[str, Any]:
        evidence_id = _validate_template_render_id(evidence_id)
        evidence_dir = version_dir / "renders" / evidence_id
        self._require_safe_directory(evidence_dir, label="render evidence directory")
        evidence = _read_json_object(evidence_dir / "render.json")
        pages = evidence.get("pages")
        if (
            evidence.get("schema") != TEMPLATE_RENDER_EVIDENCE_SCHEMA
            or evidence.get("template_id") != template_id
            or evidence.get("version") != version
            or evidence.get("evidence_id") != evidence_id
            or evidence.get("format") != "pptx"
            or evidence.get("source") != source
            or not isinstance(evidence.get("created_at"), str)
            or not isinstance(evidence.get("renderer"), str)
            or not isinstance(evidence.get("renderer_version"), str)
            or not isinstance(evidence.get("pdfium_version"), str)
            or re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("pipeline_fingerprint"))) is None
            or evidence.get("visual_review_status_at_capture") != "pending"
            or not isinstance(pages, list)
            or evidence.get("page_count") != len(pages)
            or evidence.get("rendered_page_count") != len(pages)
            or not 1 <= len(pages) <= 50
        ):
            raise OfficeTemplateIntegrityError("Office template render evidence is inconsistent")
        total_bytes = 0
        for expected_page, page in enumerate(pages, start=1):
            if not isinstance(page, dict):
                raise OfficeTemplateIntegrityError("Office template render page metadata is invalid")
            filename = f"page-{expected_page:05d}.png"
            if (
                page.get("page") != expected_page
                or page.get("source_slide") != expected_page
                or page.get("filename") != filename
                or not isinstance(page.get("width"), int)
                or not isinstance(page.get("height"), int)
                or not isinstance(page.get("size_bytes"), int)
                or re.fullmatch(r"[0-9a-f]{64}", str(page.get("sha256"))) is None
            ):
                raise OfficeTemplateIntegrityError("Office template render page metadata is invalid")
            page_path = evidence_dir / "pages" / filename
            if page_path.is_symlink() or not page_path.is_file():
                raise OfficeTemplateIntegrityError("Office template render preview is missing or unsafe")
            try:
                page_data = page_path.read_bytes()
            except OSError as exc:
                raise OfficeTemplateIntegrityError("Office template render preview could not be read") from exc
            total_bytes += len(page_data)
            if (
                not page_data
                or len(page_data) > _MAX_RENDER_PAGE_BYTES
                or total_bytes > _MAX_RENDER_TOTAL_BYTES
                or page.get("size_bytes") != len(page_data)
                or page.get("sha256") != _sha256(page_data)
                or (page.get("width"), page.get("height")) != _png_dimensions(page_data)
            ):
                raise OfficeTemplateIntegrityError("Office template render preview failed integrity checks")
        return evidence

    def _verify_render_pointer(
        self,
        *,
        version_dir: Path,
        payload: dict[str, Any],
    ) -> None:
        render = payload.get("render")
        if not isinstance(render, dict):
            raise OfficeTemplateIntegrityError("Office template render state is invalid")
        if render.get("status") == "not_recorded":
            if render != {
                "status": "not_recorded",
                "visual_review_status": "not_performed",
            }:
                raise OfficeTemplateIntegrityError("Office template empty render state is invalid")
            return
        if render.get("status") != "available":
            raise OfficeTemplateIntegrityError("Office template render state is invalid")
        evidence_id = render.get("evidence_id")
        if not isinstance(evidence_id, str):
            raise OfficeTemplateIntegrityError("Office template render evidence identity is invalid")
        evidence = self._verify_render_evidence(
            version_dir=version_dir,
            template_id=str(payload["template_id"]),
            version=int(payload["version"]),
            source=payload["source"],
            evidence_id=evidence_id,
        )
        review_status = render.get("visual_review_status")
        if review_status not in {"pending", "reviewed", "external_review_required"}:
            raise OfficeTemplateIntegrityError("Office template visual review state is invalid")
        if review_status == "pending":
            expected_review = {
                "reviewed_at": None,
                "reviewed_by": None,
                "review_note": None,
            }
        else:
            expected_review = {
                "reviewed_at": render.get("reviewed_at"),
                "reviewed_by": render.get("reviewed_by"),
                "review_note": render.get("review_note"),
            }
            if not isinstance(expected_review["reviewed_at"], str) or not isinstance(expected_review["reviewed_by"], str):
                raise OfficeTemplateIntegrityError("Office template visual review evidence is invalid")
        if (
            render.get("source_sha256") != payload["source"]["sha256"]
            or render.get("page_count") != evidence["page_count"]
            or render.get("rendered_page_count") != evidence["rendered_page_count"]
            or render.get("pipeline_fingerprint") != evidence["pipeline_fingerprint"]
            or render.get("created_at") != evidence["created_at"]
            or any(render.get(key) != value for key, value in expected_review.items())
        ):
            raise OfficeTemplateIntegrityError("Office template render pointer is inconsistent")

    def _load_version_unlocked(
        self,
        template: dict[str, Any],
        version: int,
    ) -> dict[str, Any]:
        version = _validate_version(version)
        template_id = str(template["template_id"])
        version_dir = self._selected_version_dir(template, version)
        self._require_safe_directory(version_dir, label="version directory")
        payload = _read_json_object(version_dir / "version.json")
        if (
            payload.get("schema") != TEMPLATE_VERSION_SCHEMA
            or payload.get("template_id") != template_id
            or payload.get("version") != version
            or payload.get("status") not in _TEMPLATE_STATUSES
            or payload.get("format") != "pptx"
            or not isinstance(payload.get("source"), dict)
            or not isinstance(payload.get("inspection"), dict)
            or not isinstance(payload.get("preflight"), dict)
            or not isinstance(payload.get("slot_candidates"), list)
            or not isinstance(payload.get("slots"), list)
            or not isinstance(payload.get("locked_policy"), dict)
        ):
            raise OfficeTemplateIntegrityError("Office template version metadata is inconsistent")

        source_path = version_dir / "source.pptx"
        if source_path.is_symlink() or not source_path.is_file():
            raise OfficeTemplateIntegrityError("Office template source is missing or unsafe")
        try:
            source = source_path.read_bytes()
        except OSError as exc:
            raise OfficeTemplateIntegrityError("Office template source could not be read") from exc
        source_record = payload["source"]
        if source_record.get("size_bytes") != len(source) or source_record.get("sha256") != _sha256(source):
            raise OfficeTemplateIntegrityError("Office template source failed its SHA-256 integrity check")

        inspection_path = version_dir / "inspection.json"
        preflight_path = version_dir / "preflight.json"
        inspection_bytes = inspection_path.read_bytes() if inspection_path.is_file() and not inspection_path.is_symlink() else b""
        preflight_bytes = preflight_path.read_bytes() if preflight_path.is_file() and not preflight_path.is_symlink() else b""
        if payload["inspection"].get("sha256") != _sha256(inspection_bytes) or payload["preflight"].get("sha256") != _sha256(preflight_bytes):
            raise OfficeTemplateIntegrityError("Office template evidence failed its SHA-256 integrity check")
        inspection_record = _read_json_object(inspection_path)
        preflight_record = _read_json_object(preflight_path)
        if (
            inspection_record.get("schema") != TEMPLATE_INSPECTION_SCHEMA
            or inspection_record.get("source_sha256") != source_record.get("sha256")
            or not isinstance(inspection_record.get("inspection"), dict)
            or preflight_record.get("schema") != TEMPLATE_PREFLIGHT_SCHEMA
            or preflight_record.get("source_sha256") != source_record.get("sha256")
            or not isinstance(preflight_record.get("preflight"), dict)
        ):
            raise OfficeTemplateIntegrityError("Office template evidence does not match its source")
        structure_fingerprint = _canonical_digest(_structure_descriptor(inspection_record["inspection"]))
        candidates = _build_slot_candidates(inspection_record["inspection"])
        if payload["locked_policy"].get("structure_fingerprint") != structure_fingerprint or payload["slot_candidates"] != candidates:
            raise OfficeTemplateIntegrityError("Office template mapping evidence is inconsistent")
        try:
            persisted_mappings = [
                OfficeTemplateSlotDraft(
                    key=slot["key"],
                    label=slot["label"],
                    type=slot["type"],
                    candidate_id=slot["candidate_id"],
                    required=slot["required"],
                    max_length=(slot["constraints"].get("max_length") if slot["type"] == "text" else None),
                )
                for slot in payload["slots"]
                if isinstance(slot, dict) and isinstance(slot.get("constraints"), dict)
            ]
            expected_slots = self._slot_records(persisted_mappings, candidates)
        except (KeyError, TypeError, OfficeTemplateError) as exc:
            raise OfficeTemplateIntegrityError("Office template slot mapping is invalid") from exc
        if len(persisted_mappings) != len(payload["slots"]) or expected_slots != payload["slots"]:
            raise OfficeTemplateIntegrityError("Office template slot mapping is inconsistent")
        self._verify_render_pointer(version_dir=version_dir, payload=payload)
        return payload

    def import_pptx(
        self,
        source: bytes,
        *,
        filename: str,
        title: str | None = None,
    ) -> OfficeTemplateImportCommit:
        """Validate and import one immutable PPTX source as version-one draft."""

        if not isinstance(source, bytes) or not source or len(source) > _MAX_SOURCE_BYTES:
            raise OfficeTemplateError("Office template source exceeds the supported size limit")
        display_filename = _display_filename(filename)
        display_title = _bounded_text(
            title if title is not None else PurePosixPath(display_filename).stem,
            field_name="title",
            maximum=_MAX_TITLE_CHARS,
        )
        validation = validate_pptx_renderable(source)
        inspection = office_engine.inspect(
            source,
            suffix=".pptx",
            start_slide=1,
            max_slides=50,
        )
        _validate_complete_inspection(inspection)
        preflight = office_engine.preflight(source, suffix=".pptx")
        source_sha256 = _sha256(source)
        if preflight.get("source_sha256") != source_sha256:
            raise OfficeTemplateIntegrityError("Office template preflight does not match its source")
        candidates = _build_slot_candidates(inspection)
        structure_fingerprint = _canonical_digest(_structure_descriptor(inspection))
        inspection_record = {
            "schema": TEMPLATE_INSPECTION_SCHEMA,
            "source_sha256": source_sha256,
            "inspection": inspection,
        }
        preflight_record = {
            "schema": TEMPLATE_PREFLIGHT_SCHEMA,
            "source_sha256": source_sha256,
            "preflight": preflight,
        }
        inspection_bytes = _json_bytes(inspection_record)
        preflight_bytes = _json_bytes(preflight_record)
        created_at = self._timestamp()

        with _exclusive_file_lock(self.templates_dir / ".templates.lock"):
            if self.templates_dir.is_symlink():
                raise OfficeTemplateIntegrityError("Office template root is unsafe")
            self.templates_dir.mkdir(parents=True, exist_ok=True)
            template_id = self._next_template_id()
            template_dir = self._template_dir(template_id)
            staging = _new_staging_path(self.templates_dir)
            version = 1
            version_dir = staging / "drafts" / _version_directory_name(version)
            try:
                _write_bytes_exclusive(version_dir / "source.pptx", source)
                _write_bytes_exclusive(version_dir / "inspection.json", inspection_bytes)
                _write_bytes_exclusive(version_dir / "preflight.json", preflight_bytes)
                version_payload = {
                    "schema": TEMPLATE_VERSION_SCHEMA,
                    "template_id": template_id,
                    "version": version,
                    "status": "draft",
                    "format": "pptx",
                    "filename": display_filename,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "published_at": None,
                    "source": {
                        "sha256": source_sha256,
                        "size_bytes": len(source),
                    },
                    "validation": validation,
                    "inspection": {
                        "sha256": _sha256(inspection_bytes),
                        "slide_count": inspection["slide_count"],
                        "object_count": inspection["selected_object_count"],
                    },
                    "preflight": {
                        "sha256": _sha256(preflight_bytes),
                        "finding_count": preflight["summary"]["finding_count"],
                        "findings_by_severity": preflight["summary"]["findings_by_severity"],
                    },
                    "render": {
                        "status": "not_recorded",
                        "visual_review_status": "not_performed",
                    },
                    "slot_candidates": candidates,
                    "slots": [],
                    "locked_policy": {
                        "mode": "all_except_slots",
                        "fixed_slide_count": inspection["slide_count"],
                        "fixed_object_structure": True,
                        "structure_fingerprint": structure_fingerprint,
                        "allowed_slot_types": ["text", "picture"],
                    },
                }
                template_payload = {
                    "schema": TEMPLATE_SCHEMA,
                    "template_id": template_id,
                    "title": display_title,
                    "format": "pptx",
                    "owner_scope": "user",
                    "created_at": created_at,
                    "updated_at": created_at,
                    "latest_version": version,
                    "draft_version": version,
                    "published_versions": [],
                    "archived": False,
                }
                _write_bytes_exclusive(version_dir / "version.json", _json_bytes(version_payload))
                _write_bytes_exclusive(staging / "template.json", _json_bytes(template_payload))
                os.replace(staging, template_dir)
                _sync_directory(self.templates_dir)
            finally:
                _safe_cleanup_staging(staging, self.templates_dir)

        return OfficeTemplateImportCommit(
            template_id=template_id,
            version=version,
            source_sha256=source_sha256,
            source_size_bytes=len(source),
            slot_candidate_count=len(candidates),
            structure_fingerprint=structure_fingerprint,
        )

    def load_template(self, template_id: str) -> dict[str, Any]:
        """Read one verified personal template record."""

        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            return self._load_template_unlocked(template_id)

    def load_version(self, template_id: str, version: int) -> dict[str, Any]:
        """Read one verified template version and its source-bound mapping evidence."""

        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            return self._load_version_unlocked(template, version)

    def list_versions(self, template_id: str) -> list[dict[str, Any]]:
        """List canonical draft and published versions, newest number first."""

        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            versions = set(template["published_versions"])
            if template["draft_version"] is not None:
                versions.add(template["draft_version"])
            return [self._load_version_unlocked(template, version) for version in sorted(versions, reverse=True)]

    def load_version_detail(
        self,
        template_id: str,
        version: int,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Read a version and its selected render metadata after one integrity pass."""

        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            payload = self._load_version_unlocked(template, version)
            render = payload["render"]
            if render["status"] != "available":
                return payload, None
            evidence = _read_json_object(self._selected_version_dir(template, version) / "renders" / render["evidence_id"] / "render.json")
            return payload, evidence

    def read_source(self, template_id: str, version: int) -> tuple[dict[str, Any], bytes]:
        """Read immutable template bytes after verifying version metadata and SHA-256."""

        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            version_payload = self._load_version_unlocked(template, version)
            source_path = self._selected_version_dir(template, version) / "source.pptx"
            data = source_path.read_bytes()
            return version_payload, data

    def read_inspection(self, template_id: str, version: int) -> dict[str, Any]:
        """Read source-bound full inspection evidence for mapping and detail UI."""

        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            self._load_version_unlocked(template, version)
            return _read_json_object(self._selected_version_dir(template, version) / "inspection.json")

    def list_templates(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """List verified personal templates, newest update first."""

        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_TEMPLATE_LIST_LIMIT:
            raise OfficeTemplateError(f"Office template limit must be between 1 and {_MAX_TEMPLATE_LIST_LIMIT}")
        if not self.templates_dir.exists():
            return []
        if self.templates_dir.is_symlink() or not self.templates_dir.is_dir():
            raise OfficeTemplateIntegrityError("Office template root is unsafe")
        entries = [item.name for item in self.templates_dir.iterdir() if item.is_dir() and not item.is_symlink() and _TEMPLATE_ID_RE.fullmatch(item.name)]
        if len(entries) > _MAX_TEMPLATE_RECORDS:
            raise OfficeTemplateIntegrityError("Office template store exceeds the supported record limit")
        templates = [self.load_template(template_id) for template_id in entries]
        templates.sort(
            key=lambda item: (str(item["updated_at"]), str(item["template_id"])),
            reverse=True,
        )
        return templates[:limit]

    @staticmethod
    def _slot_records(
        mappings: Sequence[OfficeTemplateSlotDraft],
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if len(mappings) > _MAX_SLOTS:
            raise OfficeTemplateError(f"Office Template V1 supports at most {_MAX_SLOTS} slots")
        by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
        records: list[dict[str, Any]] = []
        keys: set[str] = set()
        candidate_ids: set[str] = set()
        for mapping in mappings:
            if not isinstance(mapping, OfficeTemplateSlotDraft):
                raise OfficeTemplateError("Office template slot mapping has an invalid type")
            if _SLOT_KEY_RE.fullmatch(mapping.key) is None:
                raise OfficeTemplateError("Office template slot key must use lowercase snake_case")
            if mapping.key in keys:
                raise OfficeTemplateError("Office template slot keys must be unique")
            if mapping.candidate_id in candidate_ids:
                raise OfficeTemplateError("An Office template candidate may be mapped only once")
            candidate = by_id.get(mapping.candidate_id)
            if candidate is None:
                raise OfficeTemplateConflictError("Office template slot candidate is stale or missing")
            if mapping.type != candidate["type"]:
                raise OfficeTemplateConflictError("Office template slot type does not match its candidate")
            label = _bounded_text(
                mapping.label,
                field_name="slot label",
                maximum=_MAX_LABEL_CHARS,
            )
            if not isinstance(mapping.required, bool):
                raise OfficeTemplateError("Office template slot required flag must be boolean")
            if mapping.type == "text":
                max_length = mapping.max_length if mapping.max_length is not None else _MAX_TEXT_SLOT_CHARS
                if not isinstance(max_length, int) or isinstance(max_length, bool) or not 1 <= max_length <= _MAX_TEXT_SLOT_CHARS:
                    raise OfficeTemplateError(f"Office template text max_length must be between 1 and {_MAX_TEXT_SLOT_CHARS}")
                constraints: dict[str, Any] = {"max_length": max_length}
                allowed_operations = ["replace_pptx_text"]
            else:
                if mapping.max_length is not None:
                    raise OfficeTemplateError("Office template picture slots do not accept max_length")
                constraints = {
                    "accepted_media_types": ["image/png", "image/jpeg"],
                    "preserve_geometry": True,
                }
                allowed_operations = ["replace_pptx_picture_sources"]
            records.append(
                {
                    "key": mapping.key,
                    "label": label,
                    "type": mapping.type,
                    "required": mapping.required,
                    "candidate_id": mapping.candidate_id,
                    "source_fingerprint": candidate["source_fingerprint"],
                    "selector": candidate["selector"],
                    "constraints": constraints,
                    "allowed_operations": allowed_operations,
                }
            )
            keys.add(mapping.key)
            candidate_ids.add(mapping.candidate_id)
        return records

    def update_draft_slots(
        self,
        template_id: str,
        version: int,
        mappings: Sequence[OfficeTemplateSlotDraft],
    ) -> dict[str, Any]:
        """Replace a draft mapping using only source-derived server candidates."""

        template_id = _validate_template_id(template_id)
        version = _validate_version(version)
        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            payload = self._load_version_unlocked(template, version)
            if template["draft_version"] != version or payload["status"] != "draft":
                raise OfficeTemplateConflictError("Office template version is not an editable draft")
            slots = self._slot_records(mappings, payload["slot_candidates"])
            updated_at = self._timestamp()
            updated_version = {**payload, "slots": slots, "updated_at": updated_at}
            updated_template = {**template, "updated_at": updated_at}
            _atomic_replace_json(
                self._draft_version_dir(template_id, version) / "version.json",
                updated_version,
            )
            _atomic_replace_json(template_dir / "template.json", updated_template)
            return updated_version

    def render_draft(
        self,
        template_id: str,
        version: int,
        *,
        dpi: int = 120,
    ) -> OfficeTemplateRenderCommit:
        """Render every slide of a draft and select one immutable evidence run."""

        if not isinstance(dpi, int) or isinstance(dpi, bool) or not 72 <= dpi <= 240:
            raise OfficeTemplateError("Office template render DPI must be between 72 and 240")
        version_payload, source = self.read_source(template_id, version)
        if version_payload["status"] != "draft":
            raise OfficeTemplateConflictError("Published Office template versions cannot be rendered again")
        page_count = version_payload["locked_policy"]["fixed_slide_count"]
        source_sha256 = version_payload["source"]["sha256"]
        pages = []
        render_identity: tuple[str, str, str, str] | None = None
        total_bytes = 0
        start_page = 1
        while start_page <= page_count:
            max_pages = min(_MAX_RENDER_BATCH_PAGES, page_count - start_page + 1)
            rendered = self._renderer(
                source,
                suffix=".pptx",
                start_page=start_page,
                max_pages=max_pages,
                dpi=dpi,
            )
            expected_count = min(max_pages, page_count - start_page + 1)
            if rendered.format != "pptx" or rendered.source_sha256 != source_sha256 or rendered.page_count != page_count or rendered.start_page != start_page or rendered.dpi != dpi or len(rendered.pages) != expected_count:
                raise OfficeTemplateIntegrityError("Office template renderer returned inconsistent full-deck evidence")
            current_identity = (
                rendered.renderer,
                rendered.renderer_version,
                rendered.pdfium_version,
                rendered.pipeline_fingerprint,
            )
            if render_identity is None:
                render_identity = current_identity
            elif render_identity != current_identity:
                raise OfficeTemplateIntegrityError("Office template render windows used different pipelines")
            for offset, page in enumerate(rendered.pages):
                expected_page = start_page + offset
                if page.page != expected_page or page.source_slide != expected_page:
                    raise OfficeTemplateIntegrityError("Office template renderer lost PPTX slide identity")
                total_bytes += len(page.data)
                if not page.data or len(page.data) > _MAX_RENDER_PAGE_BYTES or total_bytes > _MAX_RENDER_TOTAL_BYTES or page.sha256 != _sha256(page.data) or (page.width, page.height) != _png_dimensions(page.data):
                    raise OfficeTemplateIntegrityError("Office template renderer returned invalid page bytes")
                pages.append(page)
            start_page += len(rendered.pages)
        if render_identity is None or len(pages) != page_count:
            raise OfficeTemplateIntegrityError("Office template renderer did not return every slide")

        template_id = _validate_template_id(template_id)
        version = _validate_version(version)
        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            current = self._load_version_unlocked(template, version)
            if template["draft_version"] != version or current["status"] != "draft" or current["source"] != version_payload["source"]:
                raise OfficeTemplateConflictError("Office template draft changed while it was rendering")
            version_dir = self._draft_version_dir(template_id, version)
            renders_dir = version_dir / "renders"
            evidence_id = self._next_render_id(renders_dir)
            created_at = self._timestamp()
            renderer_name, renderer_version, pdfium_version, pipeline_fingerprint = render_identity
            page_records = [
                {
                    "page": page.page,
                    "source_slide": page.source_slide,
                    "filename": f"page-{page.page:05d}.png",
                    "width": page.width,
                    "height": page.height,
                    "sha256": page.sha256,
                    "size_bytes": len(page.data),
                }
                for page in pages
            ]
            evidence = {
                "schema": TEMPLATE_RENDER_EVIDENCE_SCHEMA,
                "template_id": template_id,
                "version": version,
                "evidence_id": evidence_id,
                "created_at": created_at,
                "format": "pptx",
                "source": current["source"],
                "renderer": renderer_name,
                "renderer_version": renderer_version,
                "pdfium_version": pdfium_version,
                "pipeline_fingerprint": pipeline_fingerprint,
                "dpi": dpi,
                "page_count": page_count,
                "rendered_page_count": len(page_records),
                "visual_review_status_at_capture": "pending",
                "pages": page_records,
            }
            staging = _new_staging_path(renders_dir)
            evidence_dir = renders_dir / evidence_id
            try:
                for page, record in zip(pages, page_records, strict=True):
                    _write_bytes_exclusive(staging / "pages" / record["filename"], page.data)
                _write_bytes_exclusive(staging / "render.json", _json_bytes(evidence))
                os.replace(staging, evidence_dir)
                _sync_directory(renders_dir)
            finally:
                _safe_cleanup_staging(staging, renders_dir)

            render_pointer = {
                "status": "available",
                "evidence_id": evidence_id,
                "source_sha256": source_sha256,
                "page_count": page_count,
                "rendered_page_count": len(page_records),
                "pipeline_fingerprint": pipeline_fingerprint,
                "created_at": created_at,
                "visual_review_status": "pending",
                "reviewed_at": None,
                "reviewed_by": None,
                "review_note": None,
            }
            updated_version = {
                **current,
                "render": render_pointer,
                "updated_at": created_at,
            }
            updated_template = {**template, "updated_at": created_at}
            _atomic_replace_json(version_dir / "version.json", updated_version)
            _atomic_replace_json(template_dir / "template.json", updated_template)

        return OfficeTemplateRenderCommit(
            template_id=template_id,
            version=version,
            evidence_id=evidence_id,
            source_sha256=source_sha256,
            page_count=page_count,
            rendered_page_count=len(page_records),
            pipeline_fingerprint=pipeline_fingerprint,
            visual_review_status="pending",
        )

    def load_render_evidence(
        self,
        template_id: str,
        version: int,
        evidence_id: str,
    ) -> dict[str, Any]:
        """Read one verified render generation belonging to a selected template version."""

        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            payload = self._load_version_unlocked(template, version)
            version_dir = self._selected_version_dir(template, version)
            return self._verify_render_evidence(
                version_dir=version_dir,
                template_id=template_id,
                version=version,
                source=payload["source"],
                evidence_id=evidence_id,
            )

    def read_render_preview_page(
        self,
        template_id: str,
        version: int,
        evidence_id: str,
        page: int,
    ) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        """Read one source-bound template preview after verifying the full evidence run."""

        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= 50:
            raise OfficeTemplateError("Office template preview page must be between 1 and 50")
        evidence = self.load_render_evidence(template_id, version, evidence_id)
        preview = next(
            (item for item in evidence["pages"] if item.get("page") == page),
            None,
        )
        if preview is None:
            raise OfficeTemplateError("Office template preview page was not found")
        template = self.load_template(template_id)
        version_dir = self._selected_version_dir(template, version)
        page_path = version_dir / "renders" / evidence_id / "pages" / preview["filename"]
        data = page_path.read_bytes()
        if preview["size_bytes"] != len(data) or preview["sha256"] != _sha256(data):
            raise OfficeTemplateIntegrityError("Office template preview failed its SHA-256 integrity check")
        return evidence, preview, data

    def review_draft_render(
        self,
        template_id: str,
        version: int,
        evidence_id: str,
        *,
        status: Literal["reviewed", "external_review_required"],
        reviewer: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Record an explicit owner review against the currently selected draft render."""

        if status not in {"reviewed", "external_review_required"}:
            raise OfficeTemplateError("Office template visual review status is invalid")
        reviewer = _bounded_text(reviewer, field_name="reviewer", maximum=200)
        review_note = None if note is None else _bounded_text(note, field_name="review note", maximum=1_000)
        evidence_id = _validate_template_render_id(evidence_id)
        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            payload = self._load_version_unlocked(template, version)
            render = payload["render"]
            if template["draft_version"] != version or payload["status"] != "draft" or render.get("status") != "available" or render.get("evidence_id") != evidence_id:
                raise OfficeTemplateConflictError("Office template render is not the current editable draft evidence")
            reviewed_at = self._timestamp()
            updated_render = {
                **render,
                "visual_review_status": status,
                "reviewed_at": reviewed_at,
                "reviewed_by": reviewer,
                "review_note": review_note,
            }
            updated_version = {
                **payload,
                "render": updated_render,
                "updated_at": reviewed_at,
            }
            _atomic_replace_json(
                self._draft_version_dir(template_id, version) / "version.json",
                updated_version,
            )
            _atomic_replace_json(
                template_dir / "template.json",
                {**template, "updated_at": reviewed_at},
            )
            return updated_version

    @staticmethod
    def _publication_matches_draft(
        published: dict[str, Any],
        draft: dict[str, Any],
    ) -> bool:
        stable_fields = (
            "schema",
            "template_id",
            "version",
            "format",
            "filename",
            "created_at",
            "source",
            "validation",
            "inspection",
            "preflight",
            "render",
            "slot_candidates",
            "slots",
            "locked_policy",
        )
        return published.get("status") == "published" and all(published.get(field) == draft.get(field) for field in stable_fields)

    def publish_draft(
        self,
        template_id: str,
        version: int,
    ) -> dict[str, Any]:
        """Publish one immutable version snapshot after mapping, render, and review gates."""

        template_id = _validate_template_id(template_id)
        version = _validate_version(version)
        template_dir = self._require_existing_template_dir(template_id)
        with _exclusive_file_lock(template_dir / ".lock"):
            template = self._load_template_unlocked(template_id)
            if version in template["published_versions"]:
                return self._load_version_unlocked(template, version)
            draft = self._load_version_unlocked(template, version)
            if template["draft_version"] != version or draft["status"] != "draft":
                raise OfficeTemplateConflictError("Office template version is not an editable draft")
            if not draft["slots"]:
                raise OfficeTemplateConflictError("Office template draft must map at least one slot before publication")
            if draft["render"].get("status") != "available" or draft["render"].get("page_count") != draft["locked_policy"]["fixed_slide_count"] or draft["render"].get("rendered_page_count") != draft["locked_policy"]["fixed_slide_count"]:
                raise OfficeTemplateConflictError("Office template draft requires complete render evidence")
            if draft["render"].get("visual_review_status") != "reviewed":
                raise OfficeTemplateConflictError("Office template draft requires completed visual review")

            draft_dir = self._draft_version_dir(template_id, version)
            versions_dir = template_dir / "versions"
            published_dir = self._published_version_dir(template_id, version)
            published_payload: dict[str, Any]
            if published_dir.exists():
                synthetic_template = {
                    **template,
                    "published_versions": sorted({*template["published_versions"], version}),
                }
                published_payload = self._load_version_unlocked(
                    synthetic_template,
                    version,
                )
                if not self._publication_matches_draft(published_payload, draft):
                    raise OfficeTemplateIntegrityError("Office template publication snapshot conflicts with its draft")
            else:
                published_at = self._timestamp()
                published_payload = {
                    **draft,
                    "status": "published",
                    "updated_at": published_at,
                    "published_at": published_at,
                }
                evidence_id = draft["render"]["evidence_id"]
                evidence = self._verify_render_evidence(
                    version_dir=draft_dir,
                    template_id=template_id,
                    version=version,
                    source=draft["source"],
                    evidence_id=evidence_id,
                )
                staging = _new_staging_path(versions_dir)
                try:
                    for filename in ("source.pptx", "inspection.json", "preflight.json"):
                        _write_bytes_exclusive(
                            staging / filename,
                            (draft_dir / filename).read_bytes(),
                        )
                    source_evidence_dir = draft_dir / "renders" / evidence_id
                    for page in evidence["pages"]:
                        _write_bytes_exclusive(
                            staging / "renders" / evidence_id / "pages" / page["filename"],
                            (source_evidence_dir / "pages" / page["filename"]).read_bytes(),
                        )
                    _write_bytes_exclusive(
                        staging / "renders" / evidence_id / "render.json",
                        (source_evidence_dir / "render.json").read_bytes(),
                    )
                    _write_bytes_exclusive(
                        staging / "version.json",
                        _json_bytes(published_payload),
                    )
                    os.replace(staging, published_dir)
                    _sync_directory(versions_dir)
                finally:
                    _safe_cleanup_staging(staging, versions_dir)

            published_versions = sorted({*template["published_versions"], version})
            updated_template = {
                **template,
                "updated_at": published_payload["published_at"],
                "draft_version": None,
                "published_versions": published_versions,
            }
            _atomic_replace_json(template_dir / "template.json", updated_template)
            return published_payload

    def enforce_published_edit_policy(
        self,
        template_id: str,
        version: int,
        *,
        source: bytes,
        result: bytes,
        operations: Sequence[OfficeEditOperation],
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        """Prove that one edit stayed inside a published fixed-structure slot map."""

        payload, _evidence = self.load_version_detail(template_id, version)
        if payload["status"] != "published":
            raise OfficeTemplateConflictError("Office template project edits require a published template version")
        slots = payload["slots"]
        text_paths = {str(slot["selector"]["path"]) for slot in slots if slot.get("type") == "text" and isinstance(slot.get("selector"), dict)}
        picture_paths = {str(slot["selector"]["path"]) for slot in slots if slot.get("type") == "picture" and isinstance(slot.get("selector"), dict)}
        allowed_paths = text_paths | picture_paths

        requested_paths: set[str] = set()
        for operation in operations:
            if isinstance(operation, PptxTextReplacement):
                operation_paths = set(operation.paths)
                if not operation_paths or not operation_paths <= text_paths:
                    raise OfficeTemplateConflictError("Office template text edit targets an unmapped or non-text slot")
            elif isinstance(operation, PptxPictureSourceReplacementOperation):
                operation_paths = {target.path for target in operation.pictures.targets}
                if not operation_paths or not operation_paths <= picture_paths:
                    raise OfficeTemplateConflictError("Office template picture edit targets an unmapped or non-picture slot")
            else:
                raise OfficeTemplateConflictError("Office Template V1 permits only text and picture source replacement")
            requested_paths.update(operation_paths)

        receipt_operations = receipt.get("operations")
        semantic = receipt.get("semantic_changes")
        if not isinstance(receipt_operations, list) or not isinstance(semantic, dict) or semantic.get("coverage") != "complete":
            raise OfficeTemplateIntegrityError("Office template edit has incomplete semantic policy evidence")
        receipt_paths = {path for operation in receipt_operations if isinstance(operation, dict) for path in operation.get("target_paths", []) if isinstance(path, str)}
        changed_paths = {path for path in semantic.get("changed_target_paths", []) if isinstance(path, str)}
        if not receipt_paths <= requested_paths or not changed_paths <= allowed_paths:
            raise OfficeTemplateIntegrityError("Office template edit receipt escaped the published slot allowlist")

        expected_structure = payload["locked_policy"]["structure_fingerprint"]
        fingerprints: list[str] = []
        for document in (source, result):
            inspection = office_engine.inspect(
                document,
                suffix=".pptx",
                start_slide=1,
                max_slides=50,
            )
            _validate_complete_inspection(inspection)
            fingerprints.append(_canonical_digest(_structure_descriptor(inspection)))
        if any(fingerprint != expected_structure for fingerprint in fingerprints):
            raise OfficeTemplateConflictError("Office template edit changed or no longer matches the fixed object structure")

        return {
            "template_id": template_id,
            "version": version,
            "source_sha256": payload["source"]["sha256"],
            "structure_fingerprint": expected_structure,
            "allowed_target_paths": sorted(allowed_paths),
            "requested_target_paths": sorted(requested_paths),
            "changed_target_paths": sorted(changed_paths),
        }

    def published_restore_targets(
        self,
        template_id: str,
        version: int,
    ) -> tuple[SemanticTarget, ...]:
        """Return the complete typed slot surface for a published restore receipt."""

        payload, _evidence = self.load_version_detail(template_id, version)
        if payload["status"] != "published":
            raise OfficeTemplateConflictError("Office template project restore requires a published template version")
        targets: list[SemanticTarget] = []
        for slot in payload["slots"]:
            selector = slot.get("selector")
            path = selector.get("path") if isinstance(selector, dict) else None
            if not isinstance(path, str):
                raise OfficeTemplateIntegrityError("Office template restore slot path is invalid")
            if slot.get("type") == "text":
                kind = "pptx_shape_text"
            elif slot.get("type") == "picture":
                kind = "pptx_picture_source"
            else:
                raise OfficeTemplateIntegrityError("Office template restore slot type is invalid")
            targets.append(SemanticTarget(path=path, kind=kind))
        if not targets or len({target.path for target in targets}) != len(targets):
            raise OfficeTemplateIntegrityError("Office template restore slot map is empty or duplicated")
        return tuple(sorted(targets, key=lambda target: target.path))

    def enforce_published_restore_policy(
        self,
        template_id: str,
        version: int,
        *,
        source: bytes,
        result: bytes,
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        """Prove that a canonical restore changes only published template slots."""

        payload, _evidence = self.load_version_detail(template_id, version)
        if payload["status"] != "published":
            raise OfficeTemplateConflictError("Office template project restore requires a published template version")
        targets = self.published_restore_targets(template_id, version)
        allowed_paths = {target.path for target in targets}
        operations = receipt.get("operations")
        semantic = receipt.get("semantic_changes")
        if (
            not isinstance(operations, list)
            or len(operations) != 1
            or not isinstance(operations[0], dict)
            or operations[0].get("type") != "restore_revision"
            or not isinstance(semantic, dict)
            or semantic.get("coverage") != "complete"
        ):
            raise OfficeTemplateIntegrityError("Office template restore has incomplete semantic policy evidence")
        requested_paths = {
            path
            for path in operations[0].get("target_paths", [])
            if isinstance(path, str)
        }
        changed_paths = {
            path
            for path in semantic.get("changed_target_paths", [])
            if isinstance(path, str)
        }
        if requested_paths != allowed_paths or not changed_paths <= allowed_paths:
            raise OfficeTemplateIntegrityError("Office template restore receipt escaped the published slot allowlist")

        expected_structure = payload["locked_policy"]["structure_fingerprint"]
        fingerprints: list[str] = []
        for document in (source, result):
            inspection = office_engine.inspect(
                document,
                suffix=".pptx",
                start_slide=1,
                max_slides=50,
            )
            _validate_complete_inspection(inspection)
            fingerprints.append(_canonical_digest(_structure_descriptor(inspection)))
        if any(fingerprint != expected_structure for fingerprint in fingerprints):
            raise OfficeTemplateConflictError("Office template restore changed or no longer matches the fixed object structure")

        return {
            "template_id": template_id,
            "version": version,
            "source_sha256": payload["source"]["sha256"],
            "structure_fingerprint": expected_structure,
            "allowed_target_paths": sorted(allowed_paths),
            "requested_target_paths": sorted(requested_paths),
            "changed_target_paths": sorted(changed_paths),
        }
