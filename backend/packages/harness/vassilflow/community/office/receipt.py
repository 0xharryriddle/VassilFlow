"""Deterministic semantic and package receipts for Office edit transactions."""

from __future__ import annotations

import hashlib
import io
import json
import math
import posixpath
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from lxml import etree
from pydantic import BaseModel

from .errors import OfficePackageError
from .models import OfficeEditOperation

_SCHEMA = "vassilflow.office.semantic_change_receipt.v1"
_RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAX_OPERATION_RECORDS = 200
_MAX_TARGETS_PER_OPERATION = 200
_MAX_TOTAL_TARGET_EVIDENCE = 1_000
_MAX_CHANGED_TARGET_PATHS = 500
_MAX_SEMANTIC_DELTAS = 1_000
_MAX_PART_CHANGES = 200
_MAX_RELATIONSHIP_CHANGES = 200
_MAX_TEXT_VALUE_CHARS = 1_000
_MAX_STRUCTURED_VALUE_CHARS = 4_000
_MAX_PACKAGE_TEXT_CHARS = 1_024

_DOCX_PARAGRAPH_PATH = re.compile(r"^/document/paragraph\[(\d+)]$")
_DOCX_RUN_PATH = re.compile(r"^/document/paragraph\[(\d+)]/run\[(\d+)]$")
_MISSING = object()


@dataclass(frozen=True, slots=True)
class SemanticTarget:
    """One stable semantic target selected by a committed operation."""

    path: str
    kind: str
    locator: tuple[str, ...] = ()


@dataclass(slots=True)
class _OperationTrace:
    position: int
    operation_type: str
    match_count: int = 0
    target_path_count: int = 0
    targets: list[SemanticTarget] = field(default_factory=list)
    targets_truncated: bool = False


class OfficeEditTrace:
    """Bounded internal evidence captured while format engines mutate targets."""

    def __init__(self) -> None:
        self._operations: dict[int, _OperationTrace] = {}
        self._semantic_targets: set[SemanticTarget] = set()
        self._semantic_targets_truncated = False

    def start_operation(self, position: int, operation_type: str) -> None:
        if position in self._operations:
            raise RuntimeError(f"Office receipt trace duplicated operation {position}")
        self._operations[position] = _OperationTrace(
            position=position,
            operation_type=operation_type,
        )

    def add_target(
        self,
        position: int,
        *,
        path: str,
        kind: str,
        locator: tuple[str, ...] = (),
    ) -> None:
        operation = self._operations[position]
        target = SemanticTarget(path=path, kind=kind, locator=locator)
        operation.target_path_count += 1
        if len(operation.targets) < _MAX_TARGETS_PER_OPERATION:
            operation.targets.append(target)
        else:
            operation.targets_truncated = True
        if target in self._semantic_targets:
            return
        if len(self._semantic_targets) < _MAX_TOTAL_TARGET_EVIDENCE:
            self._semantic_targets.add(target)
        else:
            self._semantic_targets_truncated = True

    def finish_operation(self, position: int, *, match_count: int) -> None:
        self._operations[position].match_count = match_count

    def operation(self, position: int) -> _OperationTrace | None:
        return self._operations.get(position)

    def semantic_targets(self) -> tuple[SemanticTarget, ...]:
        return tuple(
            sorted(
                self._semantic_targets,
                key=lambda target: (target.path, target.kind, target.locator),
            )
        )

    @property
    def semantic_evidence_truncated(self) -> bool:
        return self._semantic_targets_truncated


class OfficeRestoreReceiptOperation(BaseModel):
    """Deterministic synthetic operation used only for project restoration evidence."""

    type: Literal["restore_revision"] = "restore_revision"
    target_revision_id: str


def xlsx_cell_path(sheet_name: str, coordinate: str) -> str:
    """Return an exact, escaped workbook path for a worksheet cell."""

    encoded_name = json.dumps(sheet_name, ensure_ascii=True)
    return f"/workbook/sheet[@name={encoded_name}]/cell[{coordinate.upper()}]"


def operation_receipt_id(operation: BaseModel, position: int) -> str:
    """Build a deterministic operation ID without exposing operation payloads."""

    canonical = json.dumps(
        operation.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()[:12]
    return f"op-{position:04d}-{digest}"


def _set_bounded_text_field(
    record: dict[str, Any],
    field_name: str,
    value: str,
) -> None:
    record[field_name] = value[:_MAX_PACKAGE_TEXT_CHARS]
    if len(value) <= _MAX_PACKAGE_TEXT_CHARS:
        return
    record[f"{field_name}_truncated"] = True
    record[f"{field_name}_character_count"] = len(value)
    record[f"{field_name}_sha256"] = hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_relationship_record(
    relationship: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if relationship is None:
        return None
    record: dict[str, Any] = {"external": relationship["external"]}
    for field_name in (
        "source_part",
        "relationship_id",
        "type",
        "target",
    ):
        _set_bounded_text_field(
            record,
            field_name,
            str(relationship[field_name]),
        )
    return record


def _relationship_source_part(part_name: str) -> str:
    if part_name == "_rels/.rels":
        return "/"
    parent, filename = posixpath.split(part_name)
    if posixpath.basename(parent) != "_rels" or not filename.endswith(".rels"):
        return part_name
    source_directory = posixpath.dirname(parent)
    source_filename = filename[: -len(".rels")]
    return posixpath.join(source_directory, source_filename)


def _relationship_records(
    part_payloads: dict[str, bytes],
) -> dict[tuple[str, str], dict[str, Any]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    for part_name in sorted(name for name in part_payloads if name.endswith(".rels")):
        try:
            root = etree.fromstring(part_payloads[part_name], parser=parser)
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise OfficePackageError(f"Office receipt could not parse relationship part {part_name}") from exc
        source_part = _relationship_source_part(part_name)
        for element in root:
            if not isinstance(element.tag, str):
                continue
            name = etree.QName(element)
            if name.namespace != _RELATIONSHIPS_NAMESPACE or name.localname != "Relationship":
                continue
            relationship_id = element.get("Id") or ""
            key = (source_part, relationship_id)
            records[key] = {
                "source_part": source_part,
                "relationship_id": relationship_id,
                "type": element.get("Type") or "",
                "target": element.get("Target") or "",
                "external": (element.get("TargetMode") or "").lower() == "external",
            }
    return records


def _package_snapshot(
    data: bytes,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            payloads = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    except (KeyError, zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise OfficePackageError(f"Office receipt could not inspect package: {exc}") from exc
    parts = {
        name: {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
        for name, payload in payloads.items()
    }
    return parts, _relationship_records(payloads)


def _part_changes(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, Counter[str]]:
    changes: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    total = 0
    for part_name in sorted(set(before) | set(after)):
        previous = before.get(part_name)
        current = after.get(part_name)
        if previous == current:
            continue
        if previous is None:
            status = "added"
        elif current is None:
            status = "removed"
        else:
            status = "changed"
        total += 1
        counts[status] += 1
        if len(changes) >= _MAX_PART_CHANGES:
            continue
        record: dict[str, Any] = {
            "status": status,
            "before": previous,
            "after": current,
        }
        _set_bounded_text_field(record, "part_name", part_name)
        changes.append(record)
    return changes, total, counts


def _relationship_changes(
    before: dict[tuple[str, str], dict[str, Any]],
    after: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, Counter[str]]:
    changes: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    total = 0
    for key in sorted(set(before) | set(after)):
        previous = before.get(key)
        current = after.get(key)
        if previous == current:
            continue
        if previous is None:
            status = "added"
        elif current is None:
            status = "removed"
        else:
            status = "changed"
        total += 1
        counts[status] += 1
        if len(changes) >= _MAX_RELATIONSHIP_CHANGES:
            continue
        changes.append(
            {
                "status": status,
                "before": _bounded_relationship_record(previous),
                "after": _bounded_relationship_record(current),
            }
        )
    return changes, total, counts


def _docx_semantic_snapshots(
    data: bytes,
    targets: tuple[SemanticTarget, ...],
) -> dict[SemanticTarget, Any]:
    from .docx import (
        _body_paragraphs,
        _load_package,
        _paragraph_format_snapshot,
        _paragraph_text,
        _run_format_snapshot,
        _text_runs,
    )

    package = _load_package(data)
    paragraphs = _body_paragraphs(package.document)
    snapshots: dict[SemanticTarget, Any] = {}
    for target in targets:
        if target.kind in {"docx_paragraph_format", "docx_paragraph_text"}:
            matched = _DOCX_PARAGRAPH_PATH.fullmatch(target.path)
            if matched is None:
                continue
            paragraph_index = int(matched.group(1))
            if not 1 <= paragraph_index <= len(paragraphs):
                continue
            paragraph = paragraphs[paragraph_index - 1]
            if target.kind == "docx_paragraph_text":
                snapshots[target] = {"text": _paragraph_text(paragraph)}
            else:
                snapshots[target] = {"formatting": _paragraph_format_snapshot(paragraph)}
            continue
        if target.kind != "docx_run_format":
            continue
        matched = _DOCX_RUN_PATH.fullmatch(target.path)
        if matched is None:
            continue
        paragraph_index = int(matched.group(1))
        run_index = int(matched.group(2))
        if not 1 <= paragraph_index <= len(paragraphs):
            continue
        runs = _text_runs(paragraphs[paragraph_index - 1])
        if not 1 <= run_index <= len(runs):
            continue
        snapshots[target] = {"formatting": _run_format_snapshot(runs[run_index - 1])}
    return snapshots


def _xlsx_semantic_snapshots(
    data: bytes,
    targets: tuple[SemanticTarget, ...],
) -> dict[SemanticTarget, Any]:
    from .xlsx import _find_sheet, _open_workbook, _style_snapshot

    workbook = _open_workbook(data)
    snapshots: dict[SemanticTarget, Any] = {}
    try:
        for target in targets:
            if target.kind != "xlsx_cell_format" or len(target.locator) != 2:
                continue
            sheet_name, coordinate = target.locator
            worksheet = _find_sheet(workbook, sheet_name)
            formatting, _ = _style_snapshot(
                worksheet[coordinate],
                budget={"characters": 0},
            )
            snapshots[target] = {"formatting": formatting}
    finally:
        workbook.close()
    return snapshots


def _pptx_semantic_snapshots(
    data: bytes,
    targets: tuple[SemanticTarget, ...],
) -> dict[SemanticTarget, Any]:
    from .pptx import (
        _first_child,
        _load_package_info,
        _paragraph_formatting,
        _picture_source_record,
        _pptx_formatting_target_maps,
        _pptx_line_target_map,
        _pptx_picture_target_map,
        _pptx_shape_target_map,
        _pptx_slide_target_map,
        _run_formatting,
        _shape_style,
        _shape_text,
        _slide_background,
    )

    package = _load_package_info(data)
    slide_targets = _pptx_slide_target_map(package)
    shape_targets = _pptx_shape_target_map(package)
    line_targets = _pptx_line_target_map(package)
    picture_targets = _pptx_picture_target_map(package)
    paragraph_targets, run_targets = _pptx_formatting_target_maps(package)
    snapshots: dict[SemanticTarget, Any] = {}
    for target in targets:
        if target.kind == "pptx_shape_text":
            resolved = shape_targets.get(target.path)
            if resolved is not None:
                snapshots[target] = {"text": _shape_text(resolved.element)}
        elif target.kind == "pptx_run_format":
            resolved = run_targets.get(target.path)
            if resolved is not None:
                snapshots[target] = {
                    "formatting": _run_formatting(
                        _first_child(resolved.element, "rPr"),
                        path=target.path,
                    )
                }
        elif target.kind == "pptx_paragraph_format":
            resolved = paragraph_targets.get(target.path)
            if resolved is not None:
                snapshots[target] = {
                    "formatting": _paragraph_formatting(
                        _first_child(resolved.element, "pPr"),
                        path=target.path,
                    )
                }
        elif target.kind == "pptx_shape_style":
            resolved = shape_targets.get(target.path)
            if resolved is not None:
                snapshots[target] = {"style": _shape_style(resolved.ref)}
        elif target.kind == "pptx_line_style":
            resolved = line_targets.get(target.path)
            if resolved is not None:
                style = _shape_style(resolved.ref) or {}
                snapshots[target] = {"line": style.get("line")}
        elif target.kind == "pptx_slide_background":
            resolved = slide_targets.get(target.path)
            if resolved is not None:
                snapshots[target] = {
                    "background": _slide_background(
                        resolved.slide,
                        path=target.path,
                    )
                }
        elif target.kind == "pptx_picture_source":
            resolved = picture_targets.get(target.path)
            if resolved is not None:
                snapshots[target] = {
                    "source": _picture_source_record(
                        resolved.element,
                        slide=resolved.slide,
                        package=package,
                    )
                }
    return snapshots


def _semantic_snapshots(
    data: bytes,
    *,
    suffix: str,
    targets: tuple[SemanticTarget, ...],
) -> dict[SemanticTarget, Any]:
    normalized_suffix = suffix.lower()
    if normalized_suffix == ".docx":
        return _docx_semantic_snapshots(data, targets)
    if normalized_suffix == ".xlsx":
        return _xlsx_semantic_snapshots(data, targets)
    if normalized_suffix == ".pptx":
        return _pptx_semantic_snapshots(data, targets)
    return {}


def _bounded_value(value: Any) -> Any:
    if value is _MISSING:
        return {"state": "absent"}
    if isinstance(value, str):
        if len(value) <= _MAX_TEXT_VALUE_CHARS:
            return value
        return {
            "value": value[:_MAX_TEXT_VALUE_CHARS],
            "truncated": True,
            "character_count": len(value),
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (dict, list, tuple)):
        normalized = list(value) if isinstance(value, tuple) else value
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        if len(payload) <= _MAX_STRUCTURED_VALUE_CHARS:
            return normalized
        return {
            "truncated": True,
            "item_count": len(normalized),
            "value_type": ("object" if isinstance(normalized, dict) else "array"),
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }
    return value


def _flatten_semantic_delta(
    before: Any,
    after: Any,
    *,
    prefix: str = "",
) -> list[tuple[str, Any, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[tuple[str, Any, Any]] = []
        for key in sorted(set(before) | set(after)):
            child_prefix = f"{prefix}.{key}" if prefix else key
            changes.extend(
                _flatten_semantic_delta(
                    before.get(key, _MISSING),
                    after.get(key, _MISSING),
                    prefix=child_prefix,
                )
            )
        return changes
    if before is _MISSING or after is _MISSING or before != after:
        return [(prefix or "$target", before, after)]
    return []


def _semantic_changes(
    before_data: bytes,
    after_data: bytes,
    *,
    suffix: str,
    trace: OfficeEditTrace,
) -> dict[str, Any]:
    targets = trace.semantic_targets()
    before = _semantic_snapshots(
        before_data,
        suffix=suffix,
        targets=targets,
    )
    after = _semantic_snapshots(
        after_data,
        suffix=suffix,
        targets=targets,
    )
    if any(target not in before or target not in after for target in targets):
        raise OfficePackageError("Office receipt could not resolve all captured semantic targets")
    changed_paths: set[str] = set()
    deltas: list[dict[str, Any]] = []
    delta_count = 0
    for target in targets:
        for property_path, previous, current in _flatten_semantic_delta(
            before.get(target, _MISSING),
            after.get(target, _MISSING),
        ):
            changed_paths.add(target.path)
            delta_count += 1
            if len(deltas) >= _MAX_SEMANTIC_DELTAS:
                continue
            deltas.append(
                {
                    "path": target.path,
                    "semantic_kind": target.kind,
                    "property": property_path,
                    "before": _bounded_value(previous),
                    "after": _bounded_value(current),
                }
            )
    ordered_paths = sorted(changed_paths)
    returned_paths = ordered_paths[:_MAX_CHANGED_TARGET_PATHS]
    return {
        "coverage": ("partial" if trace.semantic_evidence_truncated else "complete"),
        "evaluated_target_count": len(targets),
        "changed_target_count": len(ordered_paths),
        "changed_target_paths_returned": len(returned_paths),
        "changed_target_paths_truncated": len(returned_paths) < len(ordered_paths),
        "changed_target_paths": returned_paths,
        "semantic_delta_count": delta_count,
        "semantic_deltas_returned": len(deltas),
        "semantic_deltas_truncated": len(deltas) < delta_count,
        "semantic_deltas": deltas,
    }


def _receipt_limits() -> dict[str, int]:
    return {
        "operations": _MAX_OPERATION_RECORDS,
        "targets_per_operation": _MAX_TARGETS_PER_OPERATION,
        "total_target_evidence": _MAX_TOTAL_TARGET_EVIDENCE,
        "changed_target_paths": _MAX_CHANGED_TARGET_PATHS,
        "semantic_deltas": _MAX_SEMANTIC_DELTAS,
        "part_changes": _MAX_PART_CHANGES,
        "relationship_changes": _MAX_RELATIONSHIP_CHANGES,
        "text_value_characters": _MAX_TEXT_VALUE_CHARS,
        "structured_value_characters": _MAX_STRUCTURED_VALUE_CHARS,
        "package_text_characters": _MAX_PACKAGE_TEXT_CHARS,
    }


def build_restore_change_receipt(
    before_data: bytes,
    after_data: bytes,
    *,
    suffix: str,
    target_revision_id: str,
    semantic_targets: tuple[SemanticTarget, ...] = (),
) -> dict[str, Any]:
    """Build a full package receipt and honest semantic evidence for a restore."""

    normalized_suffix = suffix.lower()
    before_parts, before_relationships = _package_snapshot(before_data)
    after_parts, after_relationships = _package_snapshot(after_data)
    parts, part_change_count, part_status_counts = _part_changes(
        before_parts,
        after_parts,
    )
    relationships, relationship_change_count, relationship_status_counts = _relationship_changes(
        before_relationships,
        after_relationships,
    )
    operation = OfficeRestoreReceiptOperation(target_revision_id=target_revision_id)
    operation_id = operation_receipt_id(operation, 1)
    before_sha256 = hashlib.sha256(before_data).hexdigest()
    after_sha256 = hashlib.sha256(after_data).hexdigest()

    if semantic_targets:
        trace = OfficeEditTrace()
        trace.start_operation(1, operation.type)
        for target in semantic_targets:
            trace.add_target(
                1,
                path=target.path,
                kind=target.kind,
                locator=target.locator,
            )
        trace.finish_operation(1, match_count=len(semantic_targets))
        semantic = _semantic_changes(
            before_data,
            after_data,
            suffix=normalized_suffix,
            trace=trace,
        )
        target_paths = [target.path for target in semantic_targets][:_MAX_TARGETS_PER_OPERATION]
        target_count = len(semantic_targets)
    else:
        project_path = f"/project/revision[@id={json.dumps(target_revision_id, ensure_ascii=True)}]"
        changed = before_sha256 != after_sha256
        target_paths = [project_path]
        target_count = 1
        semantic = {
            "coverage": "partial",
            "evaluated_target_count": 1,
            "changed_target_count": 1 if changed else 0,
            "changed_target_paths_returned": 1 if changed else 0,
            "changed_target_paths_truncated": False,
            "changed_target_paths": [project_path] if changed else [],
            "semantic_delta_count": 1 if changed else 0,
            "semantic_deltas_returned": 1 if changed else 0,
            "semantic_deltas_truncated": False,
            "semantic_deltas": (
                [
                    {
                        "path": project_path,
                        "semantic_kind": "office_revision_restore",
                        "property": "artifact.sha256",
                        "before": before_sha256,
                        "after": after_sha256,
                    }
                ]
                if changed
                else []
            ),
        }

    return {
        "schema": _SCHEMA,
        "format": normalized_suffix.lstrip("."),
        "status": "changed" if before_sha256 != after_sha256 else "unchanged",
        "source": {"sha256": before_sha256, "size_bytes": len(before_data)},
        "result": {"sha256": after_sha256, "size_bytes": len(after_data)},
        "operation_count": 1,
        "operation_ids_returned": 1,
        "operation_ids_truncated": False,
        "applied_operation_ids": [operation_id],
        "operations_returned": 1,
        "operations_truncated": False,
        "operations": [
            {
                "operation_id": operation_id,
                "position": 1,
                "type": operation.type,
                "match_count": target_count,
                "target_path_count": target_count,
                "target_paths_returned": len(target_paths),
                "target_paths_truncated": len(target_paths) < target_count,
                "target_paths": target_paths,
            }
        ],
        "semantic_changes": semantic,
        "package_changes": {
            "part_change_count": part_change_count,
            "parts_returned": len(parts),
            "parts_truncated": len(parts) < part_change_count,
            "part_status_counts": dict(sorted(part_status_counts.items())),
            "parts": parts,
            "relationship_change_count": relationship_change_count,
            "relationships_returned": len(relationships),
            "relationships_truncated": len(relationships) < relationship_change_count,
            "relationship_status_counts": dict(sorted(relationship_status_counts.items())),
            "relationships": relationships,
        },
        "limits": _receipt_limits(),
    }


def build_semantic_change_receipt(
    before_data: bytes,
    after_data: bytes,
    *,
    suffix: str,
    operations: list[OfficeEditOperation],
    reports: list[dict[str, Any]],
    trace: OfficeEditTrace,
) -> dict[str, Any]:
    """Build a bounded receipt from committed semantic and package evidence."""

    normalized_suffix = suffix.lower()
    before_parts, before_relationships = _package_snapshot(before_data)
    after_parts, after_relationships = _package_snapshot(after_data)
    parts, part_change_count, part_status_counts = _part_changes(
        before_parts,
        after_parts,
    )
    relationships, relationship_change_count, relationship_status_counts = _relationship_changes(
        before_relationships,
        after_relationships,
    )
    reports_by_position = {int(report["operation"]): report for report in reports}
    expected_positions = set(range(1, len(operations) + 1))
    if len(reports_by_position) != len(reports) or set(reports_by_position) != expected_positions:
        raise OfficePackageError("Office receipt operation reports are incomplete or duplicated")
    operation_records: list[dict[str, Any]] = []
    operation_ids: list[str] = []
    for position, operation in enumerate(operations, start=1):
        operation_id = operation_receipt_id(operation, position)
        operation_trace = trace.operation(position)
        report = reports_by_position[position]
        if (
            operation_trace is None
            or operation_trace.operation_type != operation.type
            or report.get("type") != operation.type
            or report.get("operation_id") != operation_id
            or operation_trace.match_count != int(report.get("match_count", -1))
        ):
            raise OfficePackageError("Office receipt operation trace does not match the edit report")
        if len(operation_ids) < _MAX_OPERATION_RECORDS:
            operation_ids.append(operation_id)
        if len(operation_records) >= _MAX_OPERATION_RECORDS:
            continue
        target_paths = [target.path for target in operation_trace.targets]
        operation_records.append(
            {
                "operation_id": operation_id,
                "position": position,
                "type": operation.type,
                "match_count": int(report.get("match_count", 0)),
                "target_path_count": operation_trace.target_path_count,
                "target_paths_returned": len(target_paths),
                "target_paths_truncated": operation_trace.targets_truncated,
                "target_paths": target_paths,
            }
        )

    before_sha256 = hashlib.sha256(before_data).hexdigest()
    after_sha256 = hashlib.sha256(after_data).hexdigest()
    return {
        "schema": _SCHEMA,
        "format": normalized_suffix.lstrip("."),
        "status": ("changed" if before_sha256 != after_sha256 else "unchanged"),
        "source": {
            "sha256": before_sha256,
            "size_bytes": len(before_data),
        },
        "result": {
            "sha256": after_sha256,
            "size_bytes": len(after_data),
        },
        "operation_count": len(operations),
        "operation_ids_returned": len(operation_ids),
        "operation_ids_truncated": len(operation_ids) < len(operations),
        "applied_operation_ids": operation_ids,
        "operations_returned": len(operation_records),
        "operations_truncated": len(operation_records) < len(operations),
        "operations": operation_records,
        "semantic_changes": _semantic_changes(
            before_data,
            after_data,
            suffix=normalized_suffix,
            trace=trace,
        ),
        "package_changes": {
            "part_change_count": part_change_count,
            "parts_returned": len(parts),
            "parts_truncated": len(parts) < part_change_count,
            "part_status_counts": dict(sorted(part_status_counts.items())),
            "parts": parts,
            "relationship_change_count": relationship_change_count,
            "relationships_returned": len(relationships),
            "relationships_truncated": (len(relationships) < relationship_change_count),
            "relationship_status_counts": dict(sorted(relationship_status_counts.items())),
            "relationships": relationships,
        },
        "limits": _receipt_limits(),
    }
