"""Read-only, source-bound quality evidence for PPTX packages."""

from __future__ import annotations

import hashlib
import io
import math
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .errors import OfficeError, OfficeOperationError
from .pptx import (
    _DRAWING_NAMESPACES,
    _MAX_OBJECTS,
    _MAX_OBJECTS_PER_SLIDE,
    _MAX_PACKAGE_BYTES,
    _MAX_SLIDES,
    _MAX_TEXT_CHARS,
    _MAX_TEXT_NODES,
    _first_child,
    _load_package_info,
    _local_name,
    _object_geometry,
    _object_transform,
    _ObjectRef,
    _PackageInfo,
    _picture_has_alt_text,
    _picture_source_binding,
    _qname,
    _shape_is_title,
    _shape_text,
    _Slide,
    _slide_object_refs,
    _validate_image_asset_for_content_type,
)

_SCHEMA = "vassilflow.office.pptx.quality_preflight.v1"
_EMU_PER_INCH = 914_400
_TINY_DIRECT_TEXT_POINTS = 9.0
_LOW_EFFECTIVE_PPI = 96.0
_MAX_FINDINGS = 200
_MAX_IMAGE_ASSESSMENTS = 200
_MAX_GEOMETRY_ASSESSMENTS = 200
_MAX_CENSUS_VALUES = 64
_MAX_FINDING_TEXT_CHARS = 160
_MAX_GROUP_DEPTH = 64
_MAX_ABS_GEOMETRY_EMU = 1_000_000_000_000
_MAX_ABS_TRANSFORM_VALUE = 1_000_000_000_000_000
_MAX_ABS_PERCENTAGE = 1_000.0
_MATERIAL_CLIP_PERCENT = 5.0

_FONT_ELEMENT_KINDS = {
    "latin": "latin",
    "ea": "east_asia",
    "cs": "complex_script",
    "sym": "symbol",
}
_COLOR_ELEMENT_KINDS = {
    "hslClr": "hsl",
    "prstClr": "preset",
    "schemeClr": "scheme",
    "scrgbClr": "scrgb",
    "srgbClr": "rgb",
    "sysClr": "system",
}
_RUN_PROPERTY_NAMES = frozenset({"defRPr", "endParaRPr", "rPr"})


@dataclass(slots=True)
class _FindingCollector:
    items: list[dict[str, Any]] = field(default_factory=list)
    total_count: int = 0
    by_code: Counter[str] = field(default_factory=Counter)
    by_severity: Counter[str] = field(default_factory=Counter)

    def add(
        self,
        *,
        code: str,
        severity: str,
        slide_index: int,
        path: str,
        message: str,
        evidence: dict[str, Any],
    ) -> None:
        self.total_count += 1
        self.by_code[code] += 1
        self.by_severity[severity] += 1
        if len(self.items) >= _MAX_FINDINGS:
            return
        self.items.append(
            {
                "code": code,
                "severity": severity,
                "slide_index": slide_index,
                "path": path,
                "message": message,
                "evidence": evidence,
            }
        )


@dataclass(slots=True)
class _BoundedCensus:
    values: dict[str, int] = field(default_factory=dict)
    declaration_count: int = 0
    other_declaration_count: int = 0

    def add(self, value: str) -> None:
        self.declaration_count += 1
        if value in self.values:
            self.values[value] += 1
        elif len(self.values) < _MAX_CENSUS_VALUES:
            self.values[value] = 1
        else:
            self.other_declaration_count += 1

    def report(self) -> dict[str, Any]:
        return {
            "declaration_count": self.declaration_count,
            "values_returned": len(self.values),
            "values_truncated": self.other_declaration_count > 0,
            "other_declaration_count": self.other_declaration_count,
            "values": [
                {"value": value, "count": count}
                for value, count in sorted(
                    self.values.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
        }


@dataclass(frozen=True, slots=True)
class _AffineTransform:
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.a * x + self.c * y + self.e,
            self.b * x + self.d * y + self.f,
        )


@dataclass(frozen=True, slots=True)
class _ResolvedFrame:
    corners: tuple[tuple[float, float], ...]
    horizontal_emu: float
    vertical_emu: float
    group_depth: int


def _compose(
    outer: _AffineTransform,
    inner: _AffineTransform,
) -> _AffineTransform | None:
    result = _AffineTransform(
        a=outer.a * inner.a + outer.c * inner.b,
        b=outer.b * inner.a + outer.d * inner.b,
        c=outer.a * inner.c + outer.c * inner.d,
        d=outer.b * inner.c + outer.d * inner.d,
        e=outer.a * inner.e + outer.c * inner.f + outer.e,
        f=outer.b * inner.e + outer.d * inner.f + outer.f,
    )
    values = (result.a, result.b, result.c, result.d, result.e, result.f)
    if any(not math.isfinite(value) or abs(value) > _MAX_ABS_TRANSFORM_VALUE for value in values):
        return None
    return result


def _translation(x: float, y: float) -> _AffineTransform:
    return _AffineTransform(e=x, f=y)


def _scale(x: float, y: float) -> _AffineTransform:
    return _AffineTransform(a=x, d=y)


def _rotation(degrees: float) -> _AffineTransform:
    radians = math.radians(degrees % 360)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return _AffineTransform(
        a=cosine,
        b=sine,
        c=-sine,
        d=cosine,
    )


def _required_geometry(
    geometry: dict[str, Any],
    keys: tuple[str, ...],
    *,
    positive: frozenset[str] = frozenset(),
) -> tuple[float, ...] | None:
    values: list[float] = []
    for key in keys:
        value = geometry.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or abs(value) > _MAX_ABS_GEOMETRY_EMU or (key in positive and value <= 0):
            return None
        values.append(float(value))
    return tuple(values)


def _safe_object_geometry(ref: _ObjectRef) -> dict[str, Any] | None:
    try:
        return _object_geometry(ref)
    except (OfficeError, OverflowError):
        return None


def _transform_flags(ref: _ObjectRef) -> tuple[float, bool, bool] | None:
    transform = _object_transform(ref)
    if transform is None:
        return None

    flags: list[bool] = []
    for attribute in ("flipH", "flipV"):
        raw_value = transform.get(attribute)
        if raw_value is None:
            flags.append(False)
        elif raw_value.lower() in {"1", "on", "true"}:
            flags.append(True)
        elif raw_value.lower() in {"0", "off", "false"}:
            flags.append(False)
        else:
            return None
    geometry = _safe_object_geometry(ref)
    if geometry is None:
        return None
    rotation = geometry.get("rotation_degrees", 0.0)
    if isinstance(rotation, bool) or not isinstance(rotation, (int, float)):
        return None
    rotation_value = float(rotation)
    if not math.isfinite(rotation_value):
        return None
    return rotation_value, flags[0], flags[1]


def _oriented_transform(
    width: float,
    height: float,
    *,
    rotation: float,
    flip_horizontal: bool,
    flip_vertical: bool,
) -> _AffineTransform | None:
    flip = _scale(
        -1.0 if flip_horizontal else 1.0,
        -1.0 if flip_vertical else 1.0,
    )
    rotate_after_flip = _compose(_rotation(rotation), flip)
    if rotate_after_flip is None:
        return None
    centered = _compose(
        _translation(width / 2, height / 2),
        rotate_after_flip,
    )
    if centered is None:
        return None
    return _compose(centered, _translation(-width / 2, -height / 2))


def _object_frame_transform(
    ref: _ObjectRef,
) -> tuple[_AffineTransform, float, float] | None:
    geometry = _safe_object_geometry(ref)
    if geometry is None:
        return None
    values = _required_geometry(
        geometry,
        ("x_emu", "y_emu", "width_emu", "height_emu"),
        positive=frozenset({"width_emu", "height_emu"}),
    )
    flags = _transform_flags(ref)
    if values is None or flags is None:
        return None
    x, y, width, height = values
    orientation = _oriented_transform(
        width,
        height,
        rotation=flags[0],
        flip_horizontal=flags[1],
        flip_vertical=flags[2],
    )
    if orientation is None:
        return None
    matrix = _compose(_translation(x, y), orientation)
    return None if matrix is None else (matrix, width, height)


def _group_child_transform(ref: _ObjectRef) -> _AffineTransform | None:
    if ref.kind != "group":
        return None
    geometry = _safe_object_geometry(ref)
    if geometry is None:
        return None
    values = _required_geometry(
        geometry,
        (
            "x_emu",
            "y_emu",
            "width_emu",
            "height_emu",
            "child_x_emu",
            "child_y_emu",
            "child_width_emu",
            "child_height_emu",
        ),
        positive=frozenset(
            {
                "width_emu",
                "height_emu",
                "child_width_emu",
                "child_height_emu",
            }
        ),
    )
    flags = _transform_flags(ref)
    if values is None or flags is None:
        return None
    x, y, width, height, child_x, child_y, child_width, child_height = values
    orientation = _oriented_transform(
        width,
        height,
        rotation=flags[0],
        flip_horizontal=flags[1],
        flip_vertical=flags[2],
    )
    if orientation is None:
        return None
    scaled = _compose(
        _scale(width / child_width, height / child_height),
        _translation(-child_x, -child_y),
    )
    if scaled is None:
        return None
    oriented = _compose(orientation, scaled)
    if oriented is None:
        return None
    return _compose(_translation(x, y), oriented)


class _GeometryResolver:
    def __init__(self, refs: list[_ObjectRef], *, slide_index: int) -> None:
        self._slide_path = f"/slide[{slide_index}]"
        self._refs = {ref.path: ref for ref in refs}
        self._parent_cache: dict[
            str,
            tuple[_AffineTransform | None, int, str | None],
        ] = {
            self._slide_path: (_AffineTransform(), 0, None),
        }

    def _parent_to_slide(
        self,
        parent_path: str,
        *,
        visiting: frozenset[str] = frozenset(),
    ) -> tuple[_AffineTransform | None, int, str | None]:
        cached = self._parent_cache.get(parent_path)
        if cached is not None:
            return cached
        if parent_path in visiting:
            return None, 0, "group_transform_cycle"
        group = self._refs.get(parent_path)
        if group is None or group.kind != "group":
            return None, 0, "group_parent_unavailable"
        parent_matrix, depth, reason = self._parent_to_slide(
            group.parent_path,
            visiting=visiting | {parent_path},
        )
        if parent_matrix is None:
            result = (None, depth, reason or "ancestor_group_transform_unavailable")
        elif depth >= _MAX_GROUP_DEPTH:
            result = (None, depth, "group_transform_depth_exceeded")
        else:
            child_transform = _group_child_transform(group)
            combined = None if child_transform is None else _compose(parent_matrix, child_transform)
            result = (
                combined,
                depth + 1,
                None if combined is not None else "group_transform_unavailable",
            )
        self._parent_cache[parent_path] = result
        return result

    def resolve(
        self,
        ref: _ObjectRef,
    ) -> tuple[_ResolvedFrame | None, str | None]:
        local = _object_frame_transform(ref)
        if local is None:
            return None, "object_transform_unavailable"
        local_matrix, width, height = local
        parent_matrix, depth, reason = self._parent_to_slide(ref.parent_path)
        if parent_matrix is None:
            return None, reason or "ancestor_group_transform_unavailable"
        matrix = _compose(parent_matrix, local_matrix)
        if matrix is None:
            return None, "resolved_transform_out_of_range"
        corners = tuple(
            matrix.apply(x, y)
            for x, y in (
                (0.0, 0.0),
                (width, 0.0),
                (width, height),
                (0.0, height),
            )
        )
        if any(not math.isfinite(value) or abs(value) > _MAX_ABS_TRANSFORM_VALUE for point in corners for value in point):
            return None, "resolved_transform_out_of_range"
        horizontal = math.dist(corners[0], corners[1])
        vertical = math.dist(corners[0], corners[3])
        if horizontal <= 0 or vertical <= 0:
            return None, "resolved_frame_has_no_area"
        return (
            _ResolvedFrame(
                corners=corners,
                horizontal_emu=horizontal,
                vertical_emu=vertical,
                group_depth=depth,
            ),
            None,
        )


def _polygon_area(points: tuple[tuple[float, float], ...]) -> float:
    if len(points) < 3:
        return 0.0
    return (
        abs(
            sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(
                    points,
                    (*points[1:], points[0]),
                    strict=True,
                )
            )
        )
        / 2
    )


def _clip_polygon(
    points: tuple[tuple[float, float], ...],
    *,
    axis: int,
    boundary: float,
    keep_greater: bool,
) -> tuple[tuple[float, float], ...]:
    if not points:
        return ()

    def inside(point: tuple[float, float]) -> bool:
        return point[axis] >= boundary if keep_greater else point[axis] <= boundary

    output: list[tuple[float, float]] = []
    previous = points[-1]
    previous_inside = inside(previous)
    for current in points:
        current_inside = inside(current)
        if current_inside != previous_inside:
            denominator = current[axis] - previous[axis]
            if denominator != 0:
                fraction = (boundary - previous[axis]) / denominator
                output.append(
                    (
                        previous[0] + fraction * (current[0] - previous[0]),
                        previous[1] + fraction * (current[1] - previous[1]),
                    )
                )
        if current_inside:
            output.append(current)
        previous = current
        previous_inside = current_inside
    return tuple(output)


def _slide_intersection(
    corners: tuple[tuple[float, float], ...],
    *,
    slide_width: int,
    slide_height: int,
) -> tuple[float, float, tuple[tuple[float, float], ...]]:
    clipped = corners
    for axis, boundary, keep_greater in (
        (0, 0.0, True),
        (0, float(slide_width), False),
        (1, 0.0, True),
        (1, float(slide_height), False),
    ):
        clipped = _clip_polygon(
            clipped,
            axis=axis,
            boundary=boundary,
            keep_greater=keep_greater,
        )
    return _polygon_area(corners), _polygon_area(clipped), clipped


def _rounded_polygon(
    points: tuple[tuple[float, float], ...],
) -> list[dict[str, float]]:
    return [
        {
            "x": round(x, 3),
            "y": round(y, 3),
        }
        for x, y in points
    ]


def _geometry_assessment(
    ref: _ObjectRef,
    *,
    slide_index: int,
    slide_width: int,
    slide_height: int,
    resolver: _GeometryResolver,
    findings: _FindingCollector,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "slide_index": slide_index,
        "path": ref.path,
        "object_kind": ref.kind,
    }
    frame, reason = resolver.resolve(ref)
    if frame is None:
        record.update(
            {
                "status": "unknown",
                "reason": reason or "resolved_frame_unavailable",
            }
        )
        return record

    frame_area, visible_area, clipped_polygon = _slide_intersection(
        frame.corners,
        slide_width=slide_width,
        slide_height=slide_height,
    )
    if frame_area <= 0 or not math.isfinite(frame_area + visible_area):
        record.update(
            {
                "status": "unknown",
                "reason": "resolved_frame_has_no_area",
            }
        )
        return record
    visible_percent = min(100.0, max(0.0, visible_area / frame_area * 100))
    outside_percent = 100.0 - visible_percent
    left = min(point[0] for point in frame.corners)
    top = min(point[1] for point in frame.corners)
    right = max(point[0] for point in frame.corners)
    bottom = max(point[1] for point in frame.corners)
    record.update(
        {
            "status": "measured",
            "group_depth": frame.group_depth,
            "bounds_emu": {
                "left": round(left, 3),
                "top": round(top, 3),
                "right": round(right, 3),
                "bottom": round(bottom, 3),
            },
            "display_axes_emu": {
                "horizontal": round(frame.horizontal_emu, 3),
                "vertical": round(frame.vertical_emu, 3),
            },
            "slide_intersection": {
                "visible_frame_percent": round(visible_percent, 6),
                "outside_frame_percent": round(outside_percent, 6),
            },
            "intersection_evidence": {
                "frame_polygon_emu": _rounded_polygon(frame.corners),
                "slide_bounds_emu": {
                    "left": 0,
                    "top": 0,
                    "right": slide_width,
                    "bottom": slide_height,
                },
                "clipped_polygon_emu": _rounded_polygon(clipped_polygon),
                "frame_area_square_emu": round(frame_area, 3),
                "intersection_area_square_emu": round(visible_area, 3),
            },
        }
    )

    effectively_outside = visible_area == 0.0
    if ref.kind != "group" and effectively_outside:
        findings.add(
            code="object_frame_outside_slide",
            severity="warning",
            slide_index=slide_index,
            path=ref.path,
            message="This object frame is fully outside the slide bounds.",
            evidence={
                "object_kind": ref.kind,
                "group_depth": frame.group_depth,
                "outside_frame_percent": 100.0,
                "bounds_emu": record["bounds_emu"],
            },
        )
    elif ref.kind == "picture" and outside_percent >= _MATERIAL_CLIP_PERCENT:
        findings.add(
            code="picture_frame_materially_clipped",
            severity="info",
            slide_index=slide_index,
            path=ref.path,
            message=("This picture frame extends materially outside the slide; review whether the clipping is intentional."),
            evidence={
                "group_depth": frame.group_depth,
                "outside_frame_percent": round(outside_percent, 6),
                "threshold_percent": _MATERIAL_CLIP_PERCENT,
                "bounds_emu": record["bounds_emu"],
            },
        )
    return record


def _bounded_text(value: str) -> tuple[str, bool]:
    bounded = value[:_MAX_FINDING_TEXT_CHARS]
    return bounded, len(bounded) < len(value)


def _direct_text_runs(
    ref: _ObjectRef,
) -> Iterator[tuple[str, str, Any | None]]:
    text_body = _first_child(ref.element, "txBody")
    if text_body is None:
        return
    paragraph_index = 0
    for paragraph in text_body:
        if not isinstance(paragraph.tag, str) or _local_name(paragraph) != "p":
            continue
        paragraph_index += 1
        counters: dict[str, int] = {}
        for child in paragraph:
            if not isinstance(child.tag, str):
                continue
            source_kind = _local_name(child)
            if source_kind not in {"fld", "r"}:
                continue
            path_kind = "field" if source_kind == "fld" else "run"
            segment_index = counters.get(path_kind, 0) + 1
            counters[path_kind] = segment_index
            text_element = _first_child(child, "t")
            text = "" if text_element is None else text_element.text or ""
            path = f"{ref.path}/paragraph[{paragraph_index}]/{path_kind}[{segment_index}]"
            yield path, text, _first_child(child, "rPr")


def _collect_direct_formatting_census(
    package: _PackageInfo,
) -> dict[str, Any]:
    fonts = _BoundedCensus()
    colors = _BoundedCensus()
    sizes = _BoundedCensus()
    invalid_font_size_declaration_count = 0

    for slide in package.slides:
        for element in slide.root.iter():
            if not isinstance(element.tag, str):
                continue
            name = _qname(element)
            if name.namespace not in _DRAWING_NAMESPACES:
                continue
            font_kind = _FONT_ELEMENT_KINDS.get(name.localname)
            if font_kind is not None:
                typeface = (element.get("typeface") or "").strip()
                if typeface:
                    fonts.add(f"{font_kind}:{typeface[:100]}")
            color_kind = _COLOR_ELEMENT_KINDS.get(name.localname)
            if color_kind is not None:
                value = (element.get("val") or "").strip()
                if value:
                    normalized = f"#{value.upper()}" if color_kind == "rgb" else value
                    colors.add(f"{color_kind}:{normalized[:100]}")
            if name.localname not in _RUN_PROPERTY_NAMES:
                continue
            raw_size = element.get("sz")
            if raw_size is None:
                continue
            try:
                size = int(raw_size)
            except (OverflowError, ValueError):
                invalid_font_size_declaration_count += 1
                continue
            if not 0 <= size <= 400_000:
                invalid_font_size_declaration_count += 1
                continue
            sizes.add(f"{size / 100:g}pt")

    return {
        "scope": ("Direct authored font, text-size, and color tokens in slide XML only; theme and inherited formatting are not resolved."),
        "value_limit_per_census": _MAX_CENSUS_VALUES,
        "font_faces": fonts.report(),
        "font_sizes": sizes.report(),
        "colors": colors.report(),
        "invalid_font_size_declaration_count": (invalid_font_size_declaration_count),
    }


def _collect_tiny_direct_text_findings(
    ref: _ObjectRef,
    *,
    slide_index: int,
    findings: _FindingCollector,
) -> None:
    if ref.path_kind != "shape":
        return
    for path, text, run_properties in _direct_text_runs(ref):
        if not text.strip() or run_properties is None:
            continue
        raw_size = run_properties.get("sz")
        if raw_size is None:
            continue
        try:
            size_points = int(raw_size) / 100
        except (OverflowError, ValueError):
            continue
        if not 0 <= size_points < _TINY_DIRECT_TEXT_POINTS:
            continue
        evidence_text, text_truncated = _bounded_text(text)
        evidence: dict[str, Any] = {
            "direct_font_size_points": round(size_points, 6),
            "threshold_points": _TINY_DIRECT_TEXT_POINTS,
            "text": evidence_text,
        }
        if text_truncated:
            evidence["text_truncated"] = True
        findings.add(
            code="tiny_direct_text",
            severity="warning",
            slide_index=slide_index,
            path=path,
            message=("This text run declares a font size below the static preflight threshold."),
            evidence=evidence,
        )


def _rectangle_percentages(element: Any | None) -> dict[str, float]:
    percentages: dict[str, float] = {}
    if element is None:
        return percentages
    for attribute, key in (
        ("l", "left_percent"),
        ("t", "top_percent"),
        ("r", "right_percent"),
        ("b", "bottom_percent"),
    ):
        raw_value = element.get(attribute)
        if raw_value is None:
            continue
        try:
            units = int(raw_value)
            percentages[key] = units / 1_000 if abs(units) <= _MAX_ABS_PERCENTAGE * 1_000 else float("nan")
        except (OverflowError, ValueError):
            percentages[key] = float("nan")
    return percentages


def _crop_percentages(ref: _ObjectRef) -> dict[str, float]:
    blip_fill = _first_child(ref.element, "blipFill")
    return _rectangle_percentages(_first_child(blip_fill, "srcRect"))


def _unknown_image_assessment(
    record: dict[str, Any],
    *,
    reason: str,
    detail: str,
) -> dict[str, Any]:
    record.update(
        {
            "status": "unknown",
            "reason": reason,
            "detail": detail,
        }
    )
    return record


def _assess_picture(
    ref: _ObjectRef,
    *,
    slide: _Slide,
    slide_index: int,
    package: _PackageInfo,
    archive: zipfile.ZipFile,
    asset_cache: dict[tuple[str, str], tuple[Any | None, str | None]],
    geometry_resolver: _GeometryResolver,
    findings: _FindingCollector,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "slide_index": slide_index,
        "path": ref.path,
        "object_kind": ref.kind,
    }
    if ref.kind != "picture":
        return _unknown_image_assessment(
            record,
            reason="non_static_picture_object",
            detail="Effective PPI is evaluated only for static picture objects.",
        )
    try:
        binding = _picture_source_binding(
            ref.element,
            slide=slide,
            package=package,
            label=ref.path,
            require_supported_content_type=False,
        )
    except OfficeOperationError as exc:
        return _unknown_image_assessment(
            record,
            reason="embedded_source_unavailable",
            detail=str(exc),
        )

    record["source"] = {
        "relationship_id": binding.relationship_id,
        "part_name": binding.part_name,
        "content_type": binding.content_type,
        "sha256": binding.sha256,
        "size_bytes": package.part_sizes.get(binding.part_name),
    }
    frame, geometry_reason = geometry_resolver.resolve(ref)
    if frame is None:
        return _unknown_image_assessment(
            record,
            reason="display_geometry_unavailable",
            detail=(f"Positive picture geometry and a complete bounded ancestor-group transform chain are required ({geometry_reason or 'unknown reason'})."),
        )

    blip_fill = _first_child(ref.element, "blipFill")
    stretch = None if blip_fill is None else _first_child(blip_fill, "stretch")
    if blip_fill is None or _first_child(blip_fill, "tile") is not None or stretch is None:
        return _unknown_image_assessment(
            record,
            reason="unsupported_picture_framing",
            detail=("Effective PPI requires an explicitly stretched picture fill; tile, center, and unspecified framing are not measured."),
        )

    crop = _crop_percentages(ref)
    crop_values = {
        "left_percent": crop.get("left_percent", 0.0),
        "top_percent": crop.get("top_percent", 0.0),
        "right_percent": crop.get("right_percent", 0.0),
        "bottom_percent": crop.get("bottom_percent", 0.0),
    }
    horizontal_crop = crop_values["left_percent"] + crop_values["right_percent"]
    vertical_crop = crop_values["top_percent"] + crop_values["bottom_percent"]
    if any(not 0 <= value < 100 for value in crop_values.values()) or horizontal_crop >= 100 or vertical_crop >= 100:
        return _unknown_image_assessment(
            record,
            reason="unsupported_crop_geometry",
            detail=("Effective PPI requires finite, non-negative crop percentages with visible width and height."),
        )

    fill_rectangle = _rectangle_percentages(_first_child(stretch, "fillRect"))
    fill_values = {
        "left_percent": fill_rectangle.get("left_percent", 0.0),
        "top_percent": fill_rectangle.get("top_percent", 0.0),
        "right_percent": fill_rectangle.get("right_percent", 0.0),
        "bottom_percent": fill_rectangle.get("bottom_percent", 0.0),
    }
    horizontal_fill_scale = 1 - (fill_values["left_percent"] + fill_values["right_percent"]) / 100
    vertical_fill_scale = 1 - (fill_values["top_percent"] + fill_values["bottom_percent"]) / 100
    if any(not math.isfinite(value) or abs(value) > _MAX_ABS_PERCENTAGE for value in fill_values.values()) or horizontal_fill_scale <= 0 or vertical_fill_scale <= 0:
        return _unknown_image_assessment(
            record,
            reason="unsupported_fill_geometry",
            detail=("Effective PPI requires a finite, bounded destination fill rectangle with positive width and height."),
        )

    cache_key = (binding.part_name, binding.content_type)
    if cache_key not in asset_cache:
        try:
            asset_cache[cache_key] = (
                _validate_image_asset_for_content_type(
                    archive.read(binding.part_name),
                    content_type=binding.content_type,
                    label=binding.part_name,
                ),
                None,
            )
        except (KeyError, OfficeOperationError) as exc:
            asset_cache[cache_key] = (None, str(exc))
    asset, asset_error = asset_cache[cache_key]
    if asset is None:
        return _unknown_image_assessment(
            record,
            reason="unsupported_or_invalid_image_encoding",
            detail=(asset_error or "The embedded image could not be measured by this preflight."),
        )

    frame_width_inches = frame.horizontal_emu / _EMU_PER_INCH
    frame_height_inches = frame.vertical_emu / _EMU_PER_INCH
    display_width_inches = frame_width_inches * horizontal_fill_scale
    display_height_inches = frame_height_inches * vertical_fill_scale
    visible_pixel_width = asset.width * (1 - horizontal_crop / 100)
    visible_pixel_height = asset.height * (1 - vertical_crop / 100)
    effective_ppi_x = visible_pixel_width / display_width_inches
    effective_ppi_y = visible_pixel_height / display_height_inches
    minimum_effective_ppi = min(effective_ppi_x, effective_ppi_y)
    record.update(
        {
            "status": "measured",
            "group_depth": frame.group_depth,
            "source_pixels": {
                "width": asset.width,
                "height": asset.height,
            },
            "frame_inches": {
                "width": round(frame_width_inches, 6),
                "height": round(frame_height_inches, 6),
            },
            "display_inches": {
                "width": round(display_width_inches, 6),
                "height": round(display_height_inches, 6),
            },
            "crop": {key: round(value, 6) for key, value in crop_values.items()},
            "fill_rectangle": {key: round(value, 6) for key, value in fill_values.items()},
            "effective_ppi": {
                "horizontal": round(effective_ppi_x, 6),
                "vertical": round(effective_ppi_y, 6),
                "minimum": round(minimum_effective_ppi, 6),
            },
            "threshold_ppi": _LOW_EFFECTIVE_PPI,
        }
    )
    if minimum_effective_ppi < _LOW_EFFECTIVE_PPI:
        findings.add(
            code="low_effective_ppi",
            severity="warning",
            slide_index=slide_index,
            path=ref.path,
            message=("This picture measures below the effective PPI threshold after crop and cumulative group transforms."),
            evidence={
                "minimum_effective_ppi": round(minimum_effective_ppi, 6),
                "threshold_ppi": _LOW_EFFECTIVE_PPI,
                "source_sha256": binding.sha256,
            },
        )
    return record


def _check_record(
    *,
    check_id: str,
    status: str,
    scope: str,
    finding_codes: tuple[str, ...],
    findings: _FindingCollector,
    limitation: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": check_id,
        "status": status,
        "scope": scope,
        "finding_count": sum(findings.by_code[code] for code in finding_codes),
    }
    if limitation is not None:
        record["limitation"] = limitation
    return record


def preflight_pptx(data: bytes) -> dict[str, Any]:
    """Return bounded static quality evidence without mutating the package."""

    package = _load_package_info(data)
    source_sha256 = hashlib.sha256(data).hexdigest()
    findings = _FindingCollector()
    object_count = 0
    picture_count = 0
    image_assessments: list[dict[str, Any]] = []
    image_statuses: Counter[str] = Counter()
    geometry_assessments: list[dict[str, Any]] = []
    geometry_statuses: Counter[str] = Counter()
    asset_cache: dict[tuple[str, str], tuple[Any | None, str | None]] = {}

    with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
        for slide_index, slide in enumerate(package.slides, start=1):
            refs = _slide_object_refs(slide.root, slide_index=slide_index)
            geometry_resolver = _GeometryResolver(
                refs,
                slide_index=slide_index,
            )
            object_count += len(refs)
            title_refs = [ref for ref in refs if ref.path_kind == "shape" and _shape_is_title(ref.element)]
            if not title_refs:
                findings.add(
                    code="missing_slide_title_evidence",
                    severity="info",
                    slide_index=slide_index,
                    path=f"/slide[{slide_index}]",
                    message=("No title placeholder was found; this does not prove that the slide lacks a visually authored title."),
                    evidence={"title_placeholder_count": 0},
                )
            for title_ref in title_refs:
                if _shape_text(title_ref.element).strip():
                    continue
                findings.add(
                    code="empty_title_placeholder",
                    severity="warning",
                    slide_index=slide_index,
                    path=title_ref.path,
                    message="This authored title placeholder contains no text.",
                    evidence={"title_placeholder": True},
                )

            for ref in refs:
                geometry_assessment = _geometry_assessment(
                    ref,
                    slide_index=slide_index,
                    slide_width=package.width_emu,
                    slide_height=package.height_emu,
                    resolver=geometry_resolver,
                    findings=findings,
                )
                geometry_statuses[geometry_assessment["status"]] += 1
                if len(geometry_assessments) < _MAX_GEOMETRY_ASSESSMENTS:
                    geometry_assessments.append(geometry_assessment)
                _collect_tiny_direct_text_findings(
                    ref,
                    slide_index=slide_index,
                    findings=findings,
                )
                if ref.path_kind != "picture":
                    continue
                picture_count += 1
                assessment = _assess_picture(
                    ref,
                    slide=slide,
                    slide_index=slide_index,
                    package=package,
                    archive=archive,
                    asset_cache=asset_cache,
                    geometry_resolver=geometry_resolver,
                    findings=findings,
                )
                if not _picture_has_alt_text(ref.element):
                    evidence: dict[str, Any] = {
                        "object_kind": ref.kind,
                        "decorative_status": "not_evaluated",
                    }
                    source = assessment.get("source")
                    if isinstance(source, dict):
                        evidence["relationship"] = {
                            "relationship_id": source["relationship_id"],
                            "target_part_name": source["part_name"],
                            "content_type": source["content_type"],
                            "source_sha256": source["sha256"],
                        }
                    else:
                        evidence["relationship_status"] = "unavailable"
                    findings.add(
                        code="missing_picture_alt_text",
                        severity="warning",
                        slide_index=slide_index,
                        path=ref.path,
                        message=("This picture has no authored description; decorative intent is not inferred."),
                        evidence=evidence,
                    )
                image_statuses[assessment["status"]] += 1
                if len(image_assessments) < _MAX_IMAGE_ASSESSMENTS:
                    image_assessments.append(assessment)

    census = _collect_direct_formatting_census(package)
    findings_returned = len(findings.items)
    image_assessments_returned = len(image_assessments)
    geometry_assessments_returned = len(geometry_assessments)
    checks = [
        _check_record(
            check_id="picture_alt_text",
            status="complete",
            scope="Authored descriptions on presentation picture objects.",
            finding_codes=("missing_picture_alt_text",),
            findings=findings,
            limitation="Decorative intent is not inferred from OOXML.",
        ),
        _check_record(
            check_id="slide_title_placeholder_evidence",
            status="complete",
            scope="Authored title and centered-title placeholders on every slide.",
            finding_codes=(
                "empty_title_placeholder",
                "missing_slide_title_evidence",
            ),
            findings=findings,
            limitation=("Regular text boxes, diagrams, and rendered visual hierarchy are not classified as titles."),
        ),
        _check_record(
            check_id="direct_text_size",
            status="partial",
            scope=("Text-bearing shape runs and fields with an explicit direct font size."),
            finding_codes=("tiny_direct_text",),
            findings=findings,
            limitation=("Inherited, theme, layout, table-cell, and rendered fit sizes are not resolved."),
        ),
        _check_record(
            check_id="picture_effective_ppi",
            status="partial",
            scope=("Static PNG and baseline JPEG pictures with resolvable cumulative geometry, supported source crop, and bounded destination fill rectangles."),
            finding_codes=("low_effective_ppi",),
            findings=findings,
            limitation=("Linked images, incomplete or excessive group transforms, unsupported encodings, source crop, and destination fill geometry remain unknown."),
        ),
        _check_record(
            check_id="geometry_bounds_and_overlap",
            status="partial",
            scope=("Affine rectangular object frames resolved through bounded nested groups and intersected with slide bounds."),
            finding_codes=(
                "object_frame_outside_slide",
                "picture_frame_materially_clipped",
            ),
            findings=findings,
            limitation=("Overlap, rendered text bounds, custom-geometry occupancy, strokes, effects, charts, and SmartArt are not evaluated."),
        ),
        _check_record(
            check_id="contrast",
            status="unknown",
            scope="Rendered foreground and background contrast.",
            finding_codes=(),
            findings=findings,
            limitation=("Theme resolution, transparency compositing, effects, images, and rendered stacking are not evaluated."),
        ),
    ]
    return {
        "format": "pptx",
        "analysis": "quality_preflight",
        "schema": _SCHEMA,
        "mode": "read_only",
        "mutated": False,
        "source_sha256": source_sha256,
        "source_size_bytes": len(data),
        "visual_review_status": "not_performed",
        "visual_review": {
            "status": "not_performed",
            "detail": ("This is static package evidence, not rendered visual QA. Render and inspect every page before making a visual-quality claim."),
        },
        "limits": {
            "package_bytes": _MAX_PACKAGE_BYTES,
            "slides": _MAX_SLIDES,
            "objects": _MAX_OBJECTS,
            "objects_per_slide": _MAX_OBJECTS_PER_SLIDE,
            "text_nodes": _MAX_TEXT_NODES,
            "text_characters": _MAX_TEXT_CHARS,
            "findings": _MAX_FINDINGS,
            "image_assessments": _MAX_IMAGE_ASSESSMENTS,
            "geometry_assessments": _MAX_GEOMETRY_ASSESSMENTS,
            "census_values_per_kind": _MAX_CENSUS_VALUES,
            "group_depth": _MAX_GROUP_DEPTH,
            "absolute_geometry_emu": _MAX_ABS_GEOMETRY_EMU,
            "absolute_transform_value": _MAX_ABS_TRANSFORM_VALUE,
            "absolute_percentage": _MAX_ABS_PERCENTAGE,
        },
        "summary": {
            "slide_count": len(package.slides),
            "object_count": object_count,
            "picture_count": picture_count,
            "finding_count": findings.total_count,
            "findings_returned": findings_returned,
            "findings_truncated": findings_returned < findings.total_count,
            "findings_by_severity": dict(sorted(findings.by_severity.items())),
            "findings_by_code": dict(sorted(findings.by_code.items())),
        },
        "checks": checks,
        "findings": findings.items,
        "image_quality": {
            "assessment_count": picture_count,
            "assessments_returned": image_assessments_returned,
            "assessments_truncated": (image_assessments_returned < picture_count),
            "status_counts": dict(sorted(image_statuses.items())),
            "assessments": image_assessments,
        },
        "geometry_quality": {
            "assessment_count": object_count,
            "assessments_returned": geometry_assessments_returned,
            "assessments_truncated": (geometry_assessments_returned < object_count),
            "status_counts": dict(sorted(geometry_statuses.items())),
            "material_clip_threshold_percent": _MATERIAL_CLIP_PERCENT,
            "assessments": geometry_assessments,
        },
        "direct_formatting_census": census,
    }
