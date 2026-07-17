"""Read-only, hash-bound selection surfaces for Office project previews."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from typing import Any

from .engine import office_engine
from .errors import OfficeOperationError, OfficePackageError
from .models import PptxObjectSelector

PPTX_SELECTION_SCHEMA = "vassilflow.office.pptx_object_selection.v1"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MAX_TEXT_PREVIEW_CHARS = 320
_MAX_RESOLVED_CONTEXT_CHARS = 48_000
_RESOLVED_OBJECT_FIELDS = {
    "path",
    "parent_path",
    "kind",
    "name",
    "geometry",
    "style",
    "text_body",
    "source",
}

_TEXT_OBJECT_KINDS = {"shape", "title", "placeholder", "text_box"}
_SHAPE_OBJECT_KINDS = {"shape", "title", "placeholder", "text_box"}
_OPERATION_ORDER = (
    "replace_pptx_text",
    "format_pptx_runs",
    "format_pptx_paragraphs",
    "format_pptx_shapes",
    "format_pptx_lines",
    "replace_pptx_picture_sources",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256(payload)


def _is_authored_id_path(path: str, identity_source: object) -> bool:
    if identity_source != "cNvPr.id":
        return False
    segments = path.split("/")[2:]
    return bool(segments) and all("[@id=" in segment for segment in segments)


def _object_text(
    path: str,
    text_items: list[dict[str, Any]],
) -> tuple[str, bool]:
    values: list[str] = []
    truncated = False
    prefix = f"{path}/"
    for item in text_items:
        item_path = item.get("path")
        text = item.get("text")
        if not isinstance(item_path, str) or not isinstance(text, str):
            continue
        if item_path != path and not item_path.startswith(prefix):
            continue
        values.append(text)
        truncated = truncated or item.get("truncated") is True
    combined = "\n".join(value for value in values if value)
    return combined[:_MAX_TEXT_PREVIEW_CHARS], truncated or len(combined) > _MAX_TEXT_PREVIEW_CHARS


def _allowed_operations(kind: str, *, has_text: bool) -> list[str]:
    allowed: set[str] = set()
    if kind in _SHAPE_OBJECT_KINDS:
        allowed.update({"format_pptx_shapes", "format_pptx_lines"})
    if kind in _TEXT_OBJECT_KINDS and has_text:
        allowed.update(
            {
                "replace_pptx_text",
                "format_pptx_runs",
                "format_pptx_paragraphs",
            }
        )
    if kind == "connector":
        allowed.add("format_pptx_lines")
    if kind == "picture":
        allowed.add("replace_pptx_picture_sources")
    return [operation for operation in _OPERATION_ORDER if operation in allowed]


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _visible_overlay(
    geometry: dict[str, Any],
    *,
    parent_path: str,
    slide_path: str,
    slide_width: int,
    slide_height: int,
) -> dict[str, float] | None:
    if parent_path != slide_path or slide_width <= 0 or slide_height <= 0:
        return None
    x = _finite_number(geometry.get("x_emu"))
    y = _finite_number(geometry.get("y_emu"))
    width = _finite_number(geometry.get("width_emu"))
    height = _finite_number(geometry.get("height_emu"))
    if x is None or y is None or width is None or height is None or width <= 0 or height <= 0:
        return None

    left = max(0.0, x)
    top = max(0.0, y)
    right = min(float(slide_width), x + width)
    bottom = min(float(slide_height), y + height)
    if right <= left or bottom <= top:
        return None
    overlay = {
        "left_percent": round(left / slide_width * 100, 6),
        "top_percent": round(top / slide_height * 100, 6),
        "width_percent": round((right - left) / slide_width * 100, 6),
        "height_percent": round((bottom - top) / slide_height * 100, 6),
    }
    rotation = _finite_number(geometry.get("rotation_degrees"))
    if rotation is not None:
        overlay["rotation_degrees"] = round(rotation, 6)
    return overlay


def _selection_record(
    item: dict[str, Any],
    *,
    text_items: list[dict[str, Any]],
    source_sha256: str,
    slide_index: int,
    slide_path: str,
    slide_width: int,
    slide_height: int,
) -> dict[str, Any]:
    path = item.get("path")
    parent_path = item.get("parent_path")
    kind = item.get("kind")
    if not isinstance(path, str) or not isinstance(parent_path, str) or not isinstance(kind, str):
        raise OfficePackageError("PPTX inspection returned an invalid object identity")

    text_preview, text_truncated = _object_text(path, text_items)
    geometry = item.get("geometry")
    if not isinstance(geometry, dict):
        geometry = {}
    stable = _is_authored_id_path(path, item.get("identity_source"))
    allowed_operations = _allowed_operations(kind, has_text=bool(text_preview.strip())) if stable else []
    selection_status = "selectable" if allowed_operations else ("unsupported_kind" if stable else "unstable_identity")
    fingerprint_payload = {
        "schema": PPTX_SELECTION_SCHEMA,
        "source_sha256": source_sha256,
        "slide_index": slide_index,
        "path": path,
        "parent_path": parent_path,
        "kind": kind,
        "name": item.get("name"),
        "z_order": item.get("z_order"),
        "geometry": geometry,
        "text_sha256": _sha256(text_preview.encode("utf-8")),
        "text_truncated": text_truncated,
    }
    return {
        "path": path,
        "parent_path": parent_path,
        "kind": kind,
        "name": item.get("name"),
        "z_order": item.get("z_order"),
        "identity_source": item.get("identity_source"),
        "selection_status": selection_status,
        "allowed_operations": allowed_operations,
        "geometry": geometry,
        "overlay": _visible_overlay(
            geometry,
            parent_path=parent_path,
            slide_path=slide_path,
            slide_width=slide_width,
            slide_height=slide_height,
        ),
        "text_preview": text_preview,
        "text_truncated": text_truncated,
        "object_fingerprint": _canonical_sha256(fingerprint_payload),
    }


def build_pptx_selection_surface(
    document: bytes,
    *,
    slide_index: int,
) -> dict[str, Any]:
    """Build a bounded preview-selection surface from exact PPTX bytes."""

    if not isinstance(slide_index, int) or isinstance(slide_index, bool) or slide_index < 1:
        raise OfficeOperationError("PPTX selection slide_index must be at least 1")
    source_sha256 = _sha256(document)
    inspection = office_engine.inspect(
        document,
        suffix=".pptx",
        start_slide=slide_index,
        max_slides=1,
    )
    slides = inspection.get("slides")
    if not isinstance(slides, list) or len(slides) != 1:
        raise OfficeOperationError("PPTX selection slide was not found")
    slide = slides[0]
    slide_size = inspection.get("slide_size")
    if not isinstance(slide_size, dict):
        raise OfficePackageError("PPTX selection could not resolve slide dimensions")
    width = slide_size.get("width_emu")
    height = slide_size.get("height_emu")
    if not isinstance(width, int) or isinstance(width, bool) or width <= 0 or not isinstance(height, int) or isinstance(height, bool) or height <= 0:
        raise OfficePackageError("PPTX selection requires positive slide dimensions")
    slide_path = slide.get("path")
    objects = slide.get("objects")
    text_items = slide.get("text")
    if not isinstance(slide_path, str) or not isinstance(objects, list) or not isinstance(text_items, list):
        raise OfficePackageError("PPTX selection inspection is incomplete")

    records = [
        _selection_record(
            item,
            text_items=text_items,
            source_sha256=source_sha256,
            slide_index=slide_index,
            slide_path=slide_path,
            slide_width=width,
            slide_height=height,
        )
        for item in objects
        if isinstance(item, dict)
    ]
    return {
        "schema": PPTX_SELECTION_SCHEMA,
        "format": "pptx",
        "source_sha256": source_sha256,
        "slide": {
            "index": slide_index,
            "path": slide_path,
            "title": slide.get("title"),
            "width_emu": width,
            "height_emu": height,
        },
        "object_count": slide.get("object_count", len(records)),
        "objects_returned": len(records),
        "objects_truncated": slide.get("objects_truncated") is True,
        "objects": records,
    }


def resolve_pptx_selection(
    document: bytes,
    *,
    slide_index: int,
    source_sha256: str,
    object_path: str,
    object_fingerprint: str,
) -> dict[str, Any]:
    """Resolve one selectable object and reject any stale or spoofed identity."""

    if _SHA256_RE.fullmatch(source_sha256) is None or _SHA256_RE.fullmatch(object_fingerprint) is None:
        raise OfficeOperationError("Office selection identity is invalid")
    actual_sha256 = _sha256(document)
    if not hmac.compare_digest(actual_sha256, source_sha256):
        raise OfficeOperationError("Office selection source is stale")
    surface = build_pptx_selection_surface(document, slide_index=slide_index)
    selected = next(
        (item for item in surface["objects"] if item["path"] == object_path and hmac.compare_digest(item["object_fingerprint"], object_fingerprint)),
        None,
    )
    if selected is None:
        raise OfficeOperationError("Office selection does not match the selected revision")
    if selected["selection_status"] != "selectable" or not selected["allowed_operations"]:
        raise OfficeOperationError("The selected PPTX object does not support typed edits")

    inspection = office_engine.inspect(
        document,
        suffix=".pptx",
        start_slide=slide_index,
        max_slides=1,
        include_pptx_formatting=True,
        pptx_selector=PptxObjectSelector(paths=[object_path]),
    )
    if inspection.get("selected_matched_object_count") != 1 or inspection.get("selected_objects_returned") != 1 or inspection.get("selected_objects_truncated") is True or inspection.get("selected_formatting_truncated") is True:
        raise OfficeOperationError("Office selection details exceed the supported context limits")
    [slide] = inspection["slides"]
    [object_detail] = slide["objects"]
    bounded_object = {key: value for key, value in object_detail.items() if key in _RESOLVED_OBJECT_FIELDS}
    resolved = {
        "schema": PPTX_SELECTION_SCHEMA,
        "format": "pptx",
        "source_sha256": actual_sha256,
        "slide_index": slide_index,
        "slide_path": surface["slide"]["path"],
        "slide_title": surface["slide"]["title"],
        "object_path": selected["path"],
        "object_fingerprint": selected["object_fingerprint"],
        "kind": selected["kind"],
        "name": selected["name"],
        "text_preview": selected["text_preview"],
        "text_truncated": selected["text_truncated"],
        "allowed_operations": selected["allowed_operations"],
        "geometry": selected["geometry"],
        "object": bounded_object,
    }
    if len(json.dumps(resolved, ensure_ascii=False, separators=(",", ":"))) > _MAX_RESOLVED_CONTEXT_CHARS:
        raise OfficeOperationError("Office selection details exceed the supported context limits")
    return resolved
