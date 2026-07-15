# SPDX-License-Identifier: Apache-2.0
# The slide-order, grouped-shape, table-text, and inventory rules are adapted
# from OfficeCLI's PowerPoint handler. See LICENSE.officecli and NOTICE.officecli.
"""Bounded PPTX validation, inspection, and narrow direct editing."""

from __future__ import annotations

import copy
import hashlib
import io
import posixpath
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, get_args
from urllib.parse import quote, urlsplit

from lxml import etree

from .errors import OfficeOperationError, OfficePackageError
from .models import (
    PptxEditOperation,
    PptxLinearGradientFormatting,
    PptxLineEndFormatting,
    PptxLineFormatOperation,
    PptxLineFormatting,
    PptxLineTarget,
    PptxObjectSelector,
    PptxParagraphFormatOperation,
    PptxParagraphFormatting,
    PptxParagraphTarget,
    PptxPathGradientFormatting,
    PptxPictureSourceReplacementOperation,
    PptxPictureTarget,
    PptxPresetGeometryFormatting,
    PptxPresetPattern,
    PptxRunFormatOperation,
    PptxRunFormatting,
    PptxRunTarget,
    PptxShapeFillFormatting,
    PptxShapeFormatOperation,
    PptxShapeFormatting,
    PptxShapeLineFormatting,
    PptxShapeTarget,
    PptxSlideBackgroundFormatOperation,
    PptxSlideBackgroundFormatting,
    PptxSlideTarget,
    PptxTextReplacement,
)
from .opc import enforce_package_preservation

_CONTENT_TYPES_XML = "[Content_Types].xml"
_ROOT_RELATIONSHIPS_XML = "_rels/.rels"
_PRESENTATION_XML = "ppt/presentation.xml"
_PRESENTATION_RELATIONSHIPS_XML = "ppt/_rels/presentation.xml.rels"
_REQUIRED_ENTRIES = frozenset(
    {
        _CONTENT_TYPES_XML,
        _ROOT_RELATIONSHIPS_XML,
        _PRESENTATION_XML,
        _PRESENTATION_RELATIONSHIPS_XML,
    }
)

_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_PACKAGE_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_TRANSITIONAL_PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_STRICT_PRESENTATION_NS = "http://purl.oclc.org/ooxml/presentationml/main"
_TRANSITIONAL_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_STRICT_DRAWING_NS = "http://purl.oclc.org/ooxml/drawingml/main"
_PRESENTATION_NAMESPACES = frozenset(
    {
        _TRANSITIONAL_PRESENTATION_NS,
        _STRICT_PRESENTATION_NS,
    }
)
_DRAWING_NAMESPACES = frozenset(
    {
        _TRANSITIONAL_DRAWING_NS,
        _STRICT_DRAWING_NS,
    }
)
_DRAWING_NAMESPACE_BY_PRESENTATION = {
    _TRANSITIONAL_PRESENTATION_NS: _TRANSITIONAL_DRAWING_NS,
    _STRICT_PRESENTATION_NS: _STRICT_DRAWING_NS,
}
_MODEL3D_NAMESPACES = frozenset({"http://schemas.microsoft.com/office/drawing/2017/model3d"})
_DOCUMENT_RELATIONSHIPS_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    }
)
_DOCUMENT_RELATIONSHIP_NAMESPACE_BY_PRESENTATION = {
    _TRANSITIONAL_PRESENTATION_NS: "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    _STRICT_PRESENTATION_NS: "http://purl.oclc.org/ooxml/officeDocument/relationships",
}
_MARKUP_COMPATIBILITY_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_POWERPOINT_2010_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
_POWERPOINT_2012_NS = "http://schemas.microsoft.com/office/powerpoint/2012/main"
_POWERPOINT_2015_NS = "http://schemas.microsoft.com/office/powerpoint/2015/09/main"
_POWERPOINT_COMMENTS_NS = "http://schemas.microsoft.com/office/powerpoint/2018/8/main"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_SUPPORTED_TRANSITION_MC_NAMESPACES = _PRESENTATION_NAMESPACES | frozenset(
    {
        _POWERPOINT_2010_NS,
        _POWERPOINT_2012_NS,
        _POWERPOINT_2015_NS,
    }
)
_OFFICE_DOCUMENT_RELATIONSHIP_TYPES = frozenset(f"{namespace}/officeDocument" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
_SLIDE_RELATIONSHIP_TYPES = frozenset(f"{namespace}/slide" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
_SLIDE_LAYOUT_RELATIONSHIP_TYPES = frozenset(f"{namespace}/slideLayout" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
_NOTES_RELATIONSHIP_TYPES = frozenset(f"{namespace}/notesSlide" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
_LEGACY_COMMENTS_RELATIONSHIP_TYPES = frozenset(f"{namespace}/comments" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
_LEGACY_COMMENT_AUTHORS_RELATIONSHIP_TYPES = frozenset(f"{namespace}/commentAuthors" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
_MODERN_COMMENTS_RELATIONSHIP_TYPES = frozenset({"http://schemas.microsoft.com/office/2018/10/relationships/comments"})
_MODERN_COMMENT_AUTHORS_RELATIONSHIP_TYPES = frozenset({"http://schemas.microsoft.com/office/2018/10/relationships/authors"})
_HYPERLINK_RELATIONSHIP_TYPES = frozenset(f"{namespace}/hyperlink" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
_IMAGE_RELATIONSHIP_TYPES = frozenset(f"{namespace}/image" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
_EXTERNAL_HYPERLINK_SCHEMES = frozenset({"ftp", "ftps", "http", "https", "mailto", "news", "sftp", "sms", "tel"})
_NETWORK_HYPERLINK_SCHEMES = frozenset({"ftp", "ftps", "http", "https", "sftp"})
_SLIDE_JUMP_ACTION = "ppaction://hlinksldjump"
_RELATIONSHIP_FREE_ACTIONS = frozenset(
    {
        "ppaction://hlinkshowjump?jump=endshow",
        "ppaction://hlinkshowjump?jump=firstslide",
        "ppaction://hlinkshowjump?jump=lastslide",
        "ppaction://hlinkshowjump?jump=nextslide",
        "ppaction://hlinkshowjump?jump=previousslide",
        "ppaction://media",
    }
)
_MAIN_PRESENTATION_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
_SLIDE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
_SLIDE_LAYOUT_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
_SLIDE_MASTER_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"
_NOTES_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
_LEGACY_COMMENTS_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.comments+xml"
_LEGACY_COMMENT_AUTHORS_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml"
_MODERN_COMMENTS_CONTENT_TYPE = "application/vnd.ms-powerpoint.comments+xml"
_MODERN_COMMENT_AUTHORS_CONTENT_TYPE = "application/vnd.ms-powerpoint.authors+xml"
_PNG_CONTENT_TYPE = "image/png"
_JPEG_CONTENT_TYPE = "image/jpeg"
_RELATIONSHIPS_CONTENT_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
_SUPPORTED_IMAGE_CONTENT_TYPES = {
    _PNG_CONTENT_TYPE: ".png",
    _JPEG_CONTENT_TYPE: ".jpg",
}

_MAX_PACKAGE_BYTES = 50 * 1024 * 1024
_MAX_ENTRY_COUNT = 5_000
_MAX_ENTRY_BYTES = 50 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 250
_MAX_CONTROL_XML_BYTES = 2 * 1024 * 1024
_MAX_PRESENTATION_XML_BYTES = 4 * 1024 * 1024
_MAX_SLIDE_XML_BYTES = 20 * 1024 * 1024
_MAX_SLIDES = 1_000
_MAX_OBJECTS_PER_SLIDE = 5_000
_MAX_OBJECTS = 100_000
_MAX_TEXT_NODES = 100_000
_MAX_TEXT_CHARS = 5_000_000
_MAX_INSPECT_TEXT_ITEMS = 2_000
_MAX_INSPECT_TEXT_CHARS = 200_000
_MAX_TEXT_ITEM_CHARS = 4_000
_MAX_INSPECT_OBJECTS = 1_000
_MAX_INSPECT_RESOURCES = 1_000
_MAX_INSPECT_IMAGE_ASSETS = 1_000
_MAX_MEDIA_GC_RELATIONSHIPS = 20_000
_MAX_MEDIA_GC_SOURCE_XML_BYTES = 20 * 1024 * 1024
_MAX_MEDIA_GC_TOTAL_XML_BYTES = 50 * 1024 * 1024
_MAX_MEDIA_GC_RELATIONSHIP_CANDIDATES = 500
_MAX_MEDIA_GC_PART_CANDIDATES = 500
_MAX_MEDIA_GC_PROTECTED_PARTS = 100
_MAX_MEDIA_GC_UNREACHABLE_IMAGE_PARTS = 100
_MAX_MEDIA_GC_UNREACHABLE_RELATIONSHIPS_PER_PART = 50
_MAX_MEDIA_GC_BLOCKERS = 200
_MAX_INSPECT_INTERACTIONS = 2_000
_MAX_INTERACTIONS_PER_OBJECT = 100
_MAX_INSPECT_FORMATTED_CELLS = 2_000
_MAX_INSPECT_FORMATTED_PARAGRAPHS = 2_000
_MAX_INSPECT_FORMATTED_SEGMENTS = 10_000
_MAX_INSPECT_FORMATTING_TEXT_CHARS = 200_000
_MAX_INSPECT_FORMATTING_ITEM_CHARS = 4_000
_MAX_ANNOTATION_XML_BYTES = 8 * 1024 * 1024
_MAX_INSPECT_ANNOTATIONS = 1_000
_MAX_ANNOTATION_SCAN_ITEMS = 20_000
_MAX_ANNOTATION_AUTHORS = 5_000
_MAX_INSPECT_ANNOTATION_CHARS = 200_000
_MAX_INSPECT_NOTE_CHARS = 20_000
_MAX_INSPECT_COMMENT_CHARS = 4_000
_MAX_ANIMATION_TARGETS_PER_SLIDE = 5_000
_MAX_INSPECT_ANIMATIONS = 2_000
_MAX_EDIT_TEXT_REPLACEMENTS = 10_000
_MAX_EDIT_FORMATTING_TARGETS = 1_000
_MAX_FORMATTING_EXPECTED_TEXT_CHARS = 4_000
_MAX_MOTION_PATH_CHARS = 4_000
_MAX_GRADIENT_STOPS = 32
_MAX_IMAGE_ASSET_BYTES = 10 * 1024 * 1024
_MAX_TOTAL_IMAGE_ASSET_BYTES = 20 * 1024 * 1024
_MAX_IMAGE_DIMENSION = 8_192
_MAX_IMAGE_PIXELS = 16_000_000
_PPTX_PATTERN_PRESETS = frozenset(get_args(PptxPresetPattern))
_PPTX_TILE_ALIGNMENT_TO_XML = {
    "top_left": "tl",
    "top": "t",
    "top_right": "tr",
    "left": "l",
    "center": "ctr",
    "right": "r",
    "bottom_left": "bl",
    "bottom": "b",
    "bottom_right": "br",
}
_PPTX_TILE_ALIGNMENT_FROM_XML = {value: key for key, value in _PPTX_TILE_ALIGNMENT_TO_XML.items()}
_PPTX_TILE_FLIP_TO_XML = {
    "none": "none",
    "horizontal": "x",
    "vertical": "y",
    "both": "xy",
}
_PPTX_TILE_FLIP_FROM_XML = {value: key for key, value in _PPTX_TILE_FLIP_TO_XML.items()}
_MAX_COLOR_TRANSFORMS = 32
_MAX_RESOURCE_GRAPH_EDGES_PER_SLIDE = 5_000
_MAX_RESOURCE_OWNERS = 50
_MAX_OBJECT_NAME_CHARS = 256
_MAX_ALT_TEXT_CHARS = 1_000
_MAX_INTERACTION_ACTION_CHARS = 512
_MAX_INTERACTION_TOOLTIP_CHARS = 1_000
_MAX_RELATIONSHIP_ID_CHARS = 256
_MAX_RELATIONSHIP_IDS_PER_OBJECT = 100
_MAX_RESOURCE_TARGET_CHARS = 1_000
_DEFAULT_SLIDE_WIDTH_EMU = 12_192_000
_DEFAULT_SLIDE_HEIGHT_EMU = 6_858_000
_MAX_TEXT_INSET_EMU = 51_206_400

_RUN_PROPERTY_CHILD_RANK = {
    "ln": 1,
    "noFill": 2,
    "solidFill": 2,
    "gradFill": 2,
    "blipFill": 2,
    "pattFill": 2,
    "grpFill": 2,
    "effectLst": 3,
    "effectDag": 3,
    "highlight": 4,
    "uLnTx": 5,
    "uLn": 5,
    "uFillTx": 6,
    "uFill": 6,
    "latin": 7,
    "ea": 8,
    "cs": 9,
    "sym": 10,
    "hlinkClick": 11,
    "hlinkMouseOver": 12,
    "rtl": 13,
    "extLst": 14,
}
_PARAGRAPH_PROPERTY_CHILD_RANK = {
    "lnSpc": 1,
    "spcBef": 2,
    "spcAft": 3,
    "buClr": 4,
    "buClrTx": 4,
    "buSzPct": 5,
    "buSzPts": 5,
    "buSzTx": 5,
    "buFont": 6,
    "buFontTx": 6,
    "buNone": 7,
    "buAutoNum": 7,
    "buChar": 7,
    "buBlip": 7,
    "tabLst": 8,
    "defRPr": 9,
    "extLst": 10,
}
_SHAPE_PROPERTY_CHILD_RANK = {
    "xfrm": 1,
    "prstGeom": 2,
    "custGeom": 2,
    "noFill": 3,
    "solidFill": 3,
    "gradFill": 3,
    "blipFill": 3,
    "pattFill": 3,
    "grpFill": 3,
    "ln": 4,
    "effectLst": 5,
    "effectDag": 5,
    "scene3d": 6,
    "sp3d": 7,
    "extLst": 8,
}
_LINE_PROPERTY_CHILD_RANK = {
    "noFill": 1,
    "solidFill": 1,
    "gradFill": 1,
    "pattFill": 1,
    "prstDash": 2,
    "custDash": 2,
    "round": 3,
    "bevel": 3,
    "miter": 3,
    "headEnd": 4,
    "tailEnd": 5,
    "extLst": 6,
}
_SHAPE_FILL_CHILDREN = frozenset({"noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill"})
_LINE_FILL_CHILDREN = frozenset({"noFill", "solidFill", "gradFill", "pattFill"})
_LINE_DASH_CHILDREN = frozenset({"prstDash", "custDash"})
_LINE_JOIN_CHILDREN = frozenset({"round", "bevel", "miter"})
_LINE_END_CHILDREN = frozenset({"headEnd", "tailEnd"})
_RUN_FILL_CHILDREN = frozenset({"noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill"})
_RUN_COLOR_CHILDREN = frozenset({"scrgbClr", "srgbClr", "hslClr", "sysClr", "schemeClr", "prstClr"})
_RUN_UNDERLINE_CHILDREN = frozenset({"uLnTx", "uLn", "uFillTx", "uFill"})
_COLOR_TRANSFORM_SPECS = {
    "lumMod": ("luminance_modulation", "percent", 1_000),
    "lumOff": ("luminance_offset", "percent", 1_000),
    "shade": ("shade", "percent", 1_000),
    "tint": ("tint", "percent", 1_000),
    "satMod": ("saturation_modulation", "percent", 1_000),
    "satOff": ("saturation_offset", "percent", 1_000),
    "hueMod": ("hue_modulation", "percent", 1_000),
    "hueOff": ("hue_offset", "degrees", 60_000),
}
_LINE_CAP_FROM_OOXML = {
    "flat": "flat",
    "rnd": "round",
    "sq": "square",
}
_LINE_CAP_TO_OOXML = {value: key for key, value in _LINE_CAP_FROM_OOXML.items()}
_LINE_DASH_FROM_OOXML = {
    "solid": "solid",
    "dot": "dot",
    "dash": "dash",
    "dashDot": "dash_dot",
    "lgDash": "large_dash",
    "lgDashDot": "large_dash_dot",
    "lgDashDotDot": "large_dash_dot_dot",
    "sysDot": "system_dot",
    "sysDash": "system_dash",
    "sysDashDot": "system_dash_dot",
    "sysDashDotDot": "system_dash_dot_dot",
}
_LINE_DASH_TO_OOXML = {value: key for key, value in _LINE_DASH_FROM_OOXML.items()}
_LINE_COMPOUND_FROM_OOXML = {
    "sng": "single",
    "dbl": "double",
    "thickThin": "thick_thin",
    "thinThick": "thin_thick",
    "tri": "triple",
}
_LINE_COMPOUND_TO_OOXML = {value: key for key, value in _LINE_COMPOUND_FROM_OOXML.items()}
_LINE_ALIGNMENT_FROM_OOXML = {
    "ctr": "center",
    "in": "inset",
}
_LINE_ALIGNMENT_TO_OOXML = {value: key for key, value in _LINE_ALIGNMENT_FROM_OOXML.items()}
_LINE_END_TYPE_FROM_OOXML = {
    "none": "none",
    "triangle": "triangle",
    "stealth": "stealth",
    "diamond": "diamond",
    "oval": "oval",
    "arrow": "arrow",
}
_LINE_END_TYPE_TO_OOXML = {value: key for key, value in _LINE_END_TYPE_FROM_OOXML.items()}
_LINE_END_SIZE_FROM_OOXML = {
    "sm": "small",
    "med": "medium",
    "lg": "large",
}
_LINE_END_SIZE_TO_OOXML = {value: key for key, value in _LINE_END_SIZE_FROM_OOXML.items()}

_RENDER_BLOCKED_FEATURES = frozenset(
    {
        "digital signatures",
        "embedded or ActiveX objects",
        "external relationships",
        "macros",
        "unsafe actions",
    }
)


@dataclass(frozen=True, slots=True)
class _Relationship:
    relationship_id: str
    relationship_type: str
    target: str
    external: bool


@dataclass(frozen=True, slots=True)
class _ContentTypes:
    defaults: dict[str, str]
    overrides: dict[str, str]

    def for_part(self, part_name: str) -> str | None:
        override = self.overrides.get(part_name)
        if override is not None:
            return override
        filename = posixpath.basename(part_name)
        _, separator, extension = filename.rpartition(".")
        return self.defaults.get(extension.lower()) if separator else None


@dataclass(frozen=True, slots=True)
class _Slide:
    part_name: str
    root: Any
    relationships: dict[str, _Relationship]
    layout_part_name: str | None
    layout_root: Any | None


@dataclass(frozen=True, slots=True)
class _ObjectRef:
    element: Any
    container_element: Any
    kind: str
    path_kind: str
    path: str
    parent_path: str
    z_order: int
    positional_index: int
    object_id: int | None
    identity_source: str


@dataclass(frozen=True, slots=True)
class _AnimationCandidate:
    effect_time_node: Any
    preset_class: str
    raw_shape_id: str
    timing_node_id: int | None
    group_id: int | None
    grid_legend_target: bool


@dataclass(frozen=True, slots=True)
class _PptxTextSpan:
    text_element: Any
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _PptxTextSegment:
    text: str
    spans: tuple[_PptxTextSpan, ...]


@dataclass(frozen=True, slots=True)
class _PptxFormattingTarget:
    slide: _Slide
    ref: _ObjectRef
    element: Any


@dataclass(frozen=True, slots=True)
class _PptxSlideFormattingTarget:
    slide: _Slide
    path: str
    element: Any


@dataclass(slots=True)
class _PptxAllowedFormattingMutation:
    element: Any
    properties: set[str]


@dataclass(frozen=True, slots=True)
class _PackageInfo:
    entry_count: int
    presentation: Any
    slides: tuple[_Slide, ...]
    risky_features: tuple[str, ...]
    width_emu: int
    height_emu: int
    content_types: _ContentTypes
    part_names: frozenset[str]
    part_sizes: dict[str, int]
    part_sha256: dict[str, str]
    relationships_by_source: dict[str, dict[str, _Relationship]]
    relationship_counts_by_part: dict[str, int]
    relationship_source_counts_by_part: dict[str, int]


@dataclass(frozen=True, slots=True)
class _ValidatedImageAsset:
    digest: str
    content_type: str
    extension: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class _PlannedImageFill:
    relationship_id: str


@dataclass(frozen=True, slots=True)
class _PptxImageMutationRequest:
    target_path: str
    slide: _Slide
    context_element: Any
    current_fill: Any | None
    image_path: str
    rotate_with_shape: bool
    normalize_missing_rotation: bool
    crop_signature: tuple[int, int, int, int] | None
    mode: str
    tile_signature: tuple[int | None, int | None, int, int, str, str] | None
    label: str


@dataclass(frozen=True, slots=True)
class _PptxPictureImageMutationRequest:
    target_path: str
    slide: _Slide
    context_element: Any
    current_relationship_id: str
    image_path: str
    label: str


@dataclass(frozen=True, slots=True)
class _PptxPictureSourceBinding:
    blip: Any
    embed_attribute: str
    relationship_id: str
    part_name: str
    content_type: str
    sha256: str


@dataclass(slots=True)
class _PptxImageMutationPlan:
    targets: dict[str, _PlannedImageFill]
    replacements: dict[str, bytes]
    additions: dict[str, bytes]


def _qname(element: Any) -> etree.QName:
    return etree.QName(element)


def _local_name(element: Any) -> str:
    return _qname(element).localname


def _children(element: Any, local_name: str) -> list[Any]:
    return [child for child in element if isinstance(child.tag, str) and _local_name(child) == local_name]


def _first_child(element: Any, local_name: str) -> Any | None:
    return next(iter(_children(element, local_name)), None)


def _safe_xml_root(payload: bytes, *, label: str, limit: int) -> Any:
    if len(payload) > limit:
        raise OfficePackageError(f"PPTX {label} exceeds the supported size limit")
    if b"<!DOCTYPE" in payload.upper():
        raise OfficePackageError(f"PPTX {label} must not contain a document type declaration")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_blank_text=False,
    )
    try:
        return etree.fromstring(payload, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise OfficePackageError(f"PPTX {label} is malformed: {exc}") from exc


def _validate_zip_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if name != normalized or normalized.startswith("/") or ".." in path.parts:
        raise OfficePackageError(f"PPTX contains an unsafe package entry: {name}")


def _relationship_part_name(part_name: str) -> str:
    parent, filename = posixpath.split(part_name)
    return posixpath.join(parent, "_rels", f"{filename}.rels")


def _relationship_source_part(relationship_part: str) -> str:
    if relationship_part == _ROOT_RELATIONSHIPS_XML:
        return ""
    parent, filename = posixpath.split(relationship_part)
    if posixpath.basename(parent) != "_rels" or not filename.endswith(".rels"):
        raise OfficePackageError(f"PPTX contains an invalid relationship part: {relationship_part}")
    source_filename = filename[: -len(".rels")]
    if not source_filename:
        raise OfficePackageError(f"PPTX contains an invalid relationship part: {relationship_part}")
    return posixpath.join(posixpath.dirname(parent), source_filename)


def _resolve_relationship_target(source_part: str, target: str) -> str:
    if not target or "\\" in target or "\x00" in target:
        raise OfficePackageError(f"PPTX {source_part} has an unsafe relationship target")
    target_path = target.split("#", 1)[0]
    if not target_path:
        raise OfficePackageError(f"PPTX {source_part} has an empty internal relationship target")
    if target_path.startswith("/"):
        resolved = posixpath.normpath(target_path.lstrip("/"))
    else:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target_path))
    if resolved in {"", ".", ".."} or resolved.startswith("../"):
        raise OfficePackageError(f"PPTX {source_part} has a relationship outside the package")
    return resolved


def _parse_relationships(payload: bytes, *, label: str) -> dict[str, _Relationship]:
    root = _safe_xml_root(payload, label=label, limit=_MAX_CONTROL_XML_BYTES)
    if root.tag != f"{{{_PACKAGE_RELATIONSHIPS_NS}}}Relationships":
        raise OfficePackageError(f"PPTX {label} has an unexpected relationships root element")
    relationships: dict[str, _Relationship] = {}
    for element in root:
        if not isinstance(element.tag, str) or _local_name(element) != "Relationship":
            continue
        relationship_id = element.get("Id") or ""
        relationship_type = element.get("Type") or ""
        target = element.get("Target") or ""
        if not relationship_id or relationship_id in relationships:
            raise OfficePackageError(f"PPTX {label} contains a missing or duplicate relationship ID")
        if not relationship_type or not target:
            raise OfficePackageError(f"PPTX {label} contains an incomplete relationship")
        raw_target_mode = element.get("TargetMode")
        target_mode = "internal" if raw_target_mode is None else raw_target_mode.strip().lower()
        if target_mode not in {"internal", "external"}:
            raise OfficePackageError(f"PPTX {label} relationship {relationship_id} has an invalid TargetMode")
        relationships[relationship_id] = _Relationship(
            relationship_id=relationship_id,
            relationship_type=relationship_type,
            target=target,
            external=target_mode == "external",
        )
    return relationships


def _validate_content_types(payload: bytes) -> _ContentTypes:
    root = _safe_xml_root(
        payload,
        label=_CONTENT_TYPES_XML,
        limit=_MAX_CONTROL_XML_BYTES,
    )
    if root.tag != f"{{{_CONTENT_TYPES_NS}}}Types":
        raise OfficePackageError("PPTX [Content_Types].xml has an unexpected root element")
    defaults: dict[str, str] = {}
    for element in root.findall(f"{{{_CONTENT_TYPES_NS}}}Default"):
        extension = (element.get("Extension") or "").lower()
        content_type = element.get("ContentType") or ""
        if not extension or not content_type or extension in defaults:
            raise OfficePackageError("PPTX [Content_Types].xml contains an invalid default")
        defaults[extension] = content_type

    overrides: dict[str, str] = {}
    for element in root.findall(f"{{{_CONTENT_TYPES_NS}}}Override"):
        part_name = (element.get("PartName") or "").lstrip("/")
        content_type = element.get("ContentType") or ""
        if not part_name or not content_type or part_name in overrides:
            raise OfficePackageError("PPTX [Content_Types].xml contains an invalid override")
        overrides[part_name] = content_type
    presentation_content_type = overrides.get(_PRESENTATION_XML, defaults.get("xml"))
    if presentation_content_type != _MAIN_PRESENTATION_CONTENT_TYPE:
        raise OfficePackageError("PPTX content types do not resolve a standard macro-free presentation part")
    return _ContentTypes(defaults=defaults, overrides=overrides)


def _validate_root_relationships(payload: bytes) -> None:
    relationships = _parse_relationships(payload, label=_ROOT_RELATIONSHIPS_XML)
    matches = []
    for relationship in relationships.values():
        if relationship.relationship_type not in _OFFICE_DOCUMENT_RELATIONSHIP_TYPES:
            continue
        if relationship.external:
            raise OfficePackageError("PPTX presentation relationship must be internal")
        if _resolve_relationship_target("", relationship.target) == _PRESENTATION_XML:
            matches.append(relationship)
    if len(matches) != 1:
        raise OfficePackageError("PPTX root relationships do not target one main presentation part")


def _risk_labels_for_token(token: str) -> set[str]:
    normalized = token.lower().replace("-", "").replace("_", "")
    labels: set[str] = set()
    if "vba" in normalized or "macroenabled" in normalized:
        labels.add("macros")
    if "digitalsignature" in normalized or "xmlsignatures" in normalized or "originsigs" in normalized:
        labels.add("digital signatures")
    if any(marker in normalized for marker in ("activex", "oleobject", "embeddedobject", "embeddedpackage", "embeddings/")):
        labels.add("embedded or ActiveX objects")
    return labels


def _relationship_risks(relationships: dict[str, _Relationship]) -> set[str]:
    labels: set[str] = set()
    for relationship in relationships.values():
        labels.update(_risk_labels_for_token(relationship.relationship_type))
        labels.update(_risk_labels_for_token(relationship.target))
        if relationship.external:
            labels.add("external hyperlinks" if _is_safe_external_hyperlink(relationship) else "external relationships")
    return labels


def _is_safe_external_hyperlink(relationship: _Relationship) -> bool:
    if relationship.relationship_type not in _HYPERLINK_RELATIONSHIP_TYPES:
        return False
    target = relationship.target
    if any(character in target for character in ("\\", "\x00", "\r", "\n")):
        return False
    try:
        parsed = urlsplit(target)
    except ValueError:
        return False
    scheme = parsed.scheme.lower()
    if scheme not in _EXTERNAL_HYPERLINK_SCHEMES:
        return False
    if scheme in _NETWORK_HYPERLINK_SCHEMES:
        return bool(parsed.netloc)
    return bool(parsed.path)


def _validate_internal_relationship_targets(
    source_part: str,
    relationships: dict[str, _Relationship],
    names: set[str],
) -> None:
    for relationship in relationships.values():
        if relationship.external:
            continue
        target = _resolve_relationship_target(source_part, relationship.target)
        if target not in names:
            source_label = source_part or "package root"
            raise OfficePackageError(f"PPTX {source_label} relationship {relationship.relationship_id} targets a missing part")


def _validate_referenced_relationships(
    slide: Any,
    relationships: dict[str, _Relationship],
    *,
    label: str,
) -> None:
    for element in slide.iter():
        for attribute_name, relationship_id in element.attrib.items():
            try:
                attribute = etree.QName(attribute_name)
            except ValueError:
                continue
            if attribute.namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES and attribute.localname in {"embed", "id", "link"} and relationship_id and relationship_id not in relationships:
                raise OfficePackageError(f"PPTX {label} references missing relationship {relationship_id}")


def _action_risks(
    slide: Any,
    relationships: dict[str, _Relationship],
    *,
    label: str,
) -> set[str]:
    labels: set[str] = set()
    for element in slide.iter():
        action = element.get("action")
        if action is None:
            continue
        normalized = action.strip().lower()
        relationship_id = _slide_relationship_id(element)
        if normalized == _SLIDE_JUMP_ACTION:
            relationship = relationships.get(relationship_id or "")
            if relationship is None or relationship.external or relationship.relationship_type not in _SLIDE_RELATIONSHIP_TYPES:
                raise OfficePackageError(f"PPTX {label} contains an invalid slide-jump action relationship")
        elif normalized not in _RELATIONSHIP_FREE_ACTIONS or relationship_id:
            labels.add("unsafe actions")
    return labels


def _slide_dimensions(presentation: Any) -> tuple[int, int]:
    slide_size = _first_child(presentation, "sldSz")
    if slide_size is None:
        return _DEFAULT_SLIDE_WIDTH_EMU, _DEFAULT_SLIDE_HEIGHT_EMU
    try:
        width = int(slide_size.get("cx", ""))
        height = int(slide_size.get("cy", ""))
    except ValueError as exc:
        raise OfficePackageError("PPTX presentation has an invalid slide size") from exc
    if not 1 <= width <= 100_000_000 or not 1 <= height <= 100_000_000:
        raise OfficePackageError("PPTX presentation has an unsupported slide size")
    return width, height


def _slide_relationship_id(slide_id: Any) -> str | None:
    for attribute_name, value in slide_id.attrib.items():
        try:
            attribute = etree.QName(attribute_name)
        except ValueError:
            continue
        if attribute.namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES and attribute.localname == "id":
            return value
    return None


def _load_package_info(data: bytes) -> _PackageInfo:
    if not data:
        raise OfficePackageError("PPTX input is empty")
    if len(data) > _MAX_PACKAGE_BYTES:
        raise OfficePackageError("PPTX input exceeds the 50 MiB package limit")

    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ENTRY_COUNT:
                raise OfficePackageError("PPTX contains too many package entries")
            names: set[str] = set()
            part_sizes: dict[str, int] = {}
            total_uncompressed = 0
            risky_features: set[str] = set()
            for info in infos:
                _validate_zip_name(info.filename)
                if info.filename in names:
                    raise OfficePackageError(f"PPTX contains a duplicate package entry: {info.filename}")
                names.add(info.filename)
                part_sizes[info.filename] = info.file_size
                risky_features.update(_risk_labels_for_token(info.filename))
                if info.flag_bits & 0x1:
                    raise OfficePackageError("Encrypted PPTX package entries are not supported")
                if info.file_size > _MAX_ENTRY_BYTES:
                    raise OfficePackageError(f"PPTX package entry is too large: {info.filename}")
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise OfficePackageError("PPTX uncompressed content exceeds the supported limit")
                if info.file_size and info.compress_size == 0:
                    raise OfficePackageError(f"PPTX package entry has an invalid compression ratio: {info.filename}")
                if info.compress_size and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO:
                    raise OfficePackageError(f"PPTX package entry is suspiciously compressed: {info.filename}")

            missing = _REQUIRED_ENTRIES - names
            if missing:
                raise OfficePackageError(f"PPTX is missing required package entries: {', '.join(sorted(missing))}")

            content_types_payload = archive.read(_CONTENT_TYPES_XML)
            content_types = _validate_content_types(content_types_payload)
            risky_features.update(_risk_labels_for_token(content_types_payload.decode("utf-8", "ignore")))
            part_sha256 = {part_name: hashlib.sha256(archive.read(part_name)).hexdigest() for part_name in sorted(names) if (content_types.for_part(part_name) or "").lower().startswith("image/")}
            _validate_root_relationships(archive.read(_ROOT_RELATIONSHIPS_XML))
            relationships_by_source: dict[str, dict[str, _Relationship]] = {}
            for relationships_name in sorted(name for name in names if name.endswith(".rels")):
                source_part = _relationship_source_part(relationships_name)
                if source_part and source_part not in names:
                    raise OfficePackageError(f"PPTX relationship part {relationships_name} has a missing source part: {source_part}")
                relationships = _parse_relationships(
                    archive.read(relationships_name),
                    label=relationships_name,
                )
                relationships_by_source[source_part] = relationships
                risky_features.update(_relationship_risks(relationships))
                _validate_internal_relationship_targets(
                    source_part,
                    relationships,
                    names,
                )

            relationship_counts_by_part: dict[str, int] = {}
            relationship_sources_by_part: dict[str, set[str]] = {}
            for source_part, relationships in relationships_by_source.items():
                for relationship in relationships.values():
                    if relationship.external:
                        continue
                    target_part = _resolve_relationship_target(
                        source_part,
                        relationship.target,
                    )
                    relationship_counts_by_part[target_part] = relationship_counts_by_part.get(target_part, 0) + 1
                    relationship_sources_by_part.setdefault(target_part, set()).add(source_part)
            relationship_source_counts_by_part = {part_name: len(source_parts) for part_name, source_parts in relationship_sources_by_part.items()}

            presentation = _safe_xml_root(
                archive.read(_PRESENTATION_XML),
                label=_PRESENTATION_XML,
                limit=_MAX_PRESENTATION_XML_BYTES,
            )
            presentation_name = _qname(presentation)
            if presentation_name.localname != "presentation" or presentation_name.namespace not in _PRESENTATION_NAMESPACES:
                raise OfficePackageError("PPTX presentation.xml has an unexpected root element")

            presentation_relationships = relationships_by_source[_PRESENTATION_XML]
            risky_features.update(_relationship_risks(presentation_relationships))
            _validate_internal_relationship_targets(
                _PRESENTATION_XML,
                presentation_relationships,
                names,
            )

            slide_id_list = _first_child(presentation, "sldIdLst")
            slide_ids = [] if slide_id_list is None else _children(slide_id_list, "sldId")
            if len(slide_ids) > _MAX_SLIDES:
                raise OfficePackageError(f"PPTX declares more than {_MAX_SLIDES:,} slides")

            seen_numeric_ids: set[str] = set()
            seen_relationship_ids: set[str] = set()
            slides: list[_Slide] = []
            layout_roots: dict[str, Any] = {}
            total_objects = 0
            total_text_nodes = 0
            total_text_chars = 0
            for slide_index, slide_id in enumerate(slide_ids, start=1):
                numeric_id = slide_id.get("id") or ""
                relationship_id = _slide_relationship_id(slide_id)
                if not numeric_id or numeric_id in seen_numeric_ids:
                    raise OfficePackageError("PPTX slide list contains a missing or duplicate slide ID")
                if not relationship_id or relationship_id in seen_relationship_ids:
                    raise OfficePackageError("PPTX slide list contains a missing or duplicate slide relationship ID")
                seen_numeric_ids.add(numeric_id)
                seen_relationship_ids.add(relationship_id)
                relationship = presentation_relationships.get(relationship_id)
                if relationship is None:
                    raise OfficePackageError(f"PPTX slide {slide_index} references missing relationship {relationship_id}")
                if relationship.external or relationship.relationship_type not in _SLIDE_RELATIONSHIP_TYPES:
                    raise OfficePackageError(f"PPTX slide {slide_index} does not resolve to an internal slide part")
                part_name = _resolve_relationship_target(_PRESENTATION_XML, relationship.target)
                if content_types.for_part(part_name) != _SLIDE_CONTENT_TYPE:
                    raise OfficePackageError(f"PPTX slide {slide_index} does not resolve to a standard slide content type")
                slide_root = _safe_xml_root(
                    archive.read(part_name),
                    label=part_name,
                    limit=_MAX_SLIDE_XML_BYTES,
                )
                slide_name = _qname(slide_root)
                if slide_name.localname != "sld" or slide_name.namespace not in _PRESENTATION_NAMESPACES:
                    raise OfficePackageError(f"PPTX {part_name} has an unexpected root element")

                slide_relationships = relationships_by_source.get(part_name, {})
                risky_features.update(_relationship_risks(slide_relationships))
                _validate_internal_relationship_targets(part_name, slide_relationships, names)
                _validate_referenced_relationships(
                    slide_root,
                    slide_relationships,
                    label=part_name,
                )
                risky_features.update(
                    _action_risks(
                        slide_root,
                        slide_relationships,
                        label=part_name,
                    )
                )

                layout_part_name = None
                layout_root = None
                for layout_relationship in slide_relationships.values():
                    if layout_relationship.external or layout_relationship.relationship_type not in _SLIDE_LAYOUT_RELATIONSHIP_TYPES:
                        continue
                    candidate_part = _resolve_relationship_target(
                        part_name,
                        layout_relationship.target,
                    )
                    if content_types.for_part(candidate_part) != _SLIDE_LAYOUT_CONTENT_TYPE:
                        continue
                    layout_part_name = candidate_part
                    layout_root = layout_roots.get(candidate_part)
                    if layout_root is None:
                        layout_root = _safe_xml_root(
                            archive.read(candidate_part),
                            label=candidate_part,
                            limit=_MAX_SLIDE_XML_BYTES,
                        )
                        layout_roots[candidate_part] = layout_root
                    break

                object_count = _count_logical_objects(slide_root)
                if object_count > _MAX_OBJECTS_PER_SLIDE:
                    raise OfficePackageError(f"PPTX slide {slide_index} contains more than {_MAX_OBJECTS_PER_SLIDE:,} objects")
                total_objects += object_count
                if total_objects > _MAX_OBJECTS:
                    raise OfficePackageError(f"PPTX contains more than {_MAX_OBJECTS:,} objects")

                for element in slide_root.iter():
                    if not isinstance(element.tag, str):
                        continue
                    name = _qname(element)
                    if name.localname != "t" or name.namespace not in _DRAWING_NAMESPACES:
                        continue
                    total_text_nodes += 1
                    total_text_chars += len(element.text or "")
                    if total_text_nodes > _MAX_TEXT_NODES or total_text_chars > _MAX_TEXT_CHARS:
                        raise OfficePackageError("PPTX visible text exceeds the supported contract")

                slides.append(
                    _Slide(
                        part_name=part_name,
                        root=slide_root,
                        relationships=slide_relationships,
                        layout_part_name=layout_part_name,
                        layout_root=layout_root,
                    )
                )

            width_emu, height_emu = _slide_dimensions(presentation)
            return _PackageInfo(
                entry_count=len(infos),
                presentation=presentation,
                slides=tuple(slides),
                risky_features=tuple(sorted(risky_features)),
                width_emu=width_emu,
                height_emu=height_emu,
                content_types=content_types,
                part_names=frozenset(names),
                part_sizes=part_sizes,
                part_sha256=part_sha256,
                relationships_by_source=relationships_by_source,
                relationship_counts_by_part=relationship_counts_by_part,
                relationship_source_counts_by_part=(relationship_source_counts_by_part),
            )
    except OfficePackageError:
        raise
    except (KeyError, zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise OfficePackageError(f"Invalid PPTX package: {exc}") from exc


def _shape_tree(slide: Any) -> Any | None:
    common_slide_data = _first_child(slide, "cSld")
    return None if common_slide_data is None else _first_child(common_slide_data, "spTree")


def _text_body_text(text_body: Any | None) -> str:
    if text_body is None:
        return ""
    paragraphs: list[str] = []
    for paragraph in text_body.iter():
        if not isinstance(paragraph.tag, str):
            continue
        name = _qname(paragraph)
        if name.localname != "p" or name.namespace not in _DRAWING_NAMESPACES:
            continue
        chunks: list[str] = []
        for element in paragraph.iter():
            if not isinstance(element.tag, str):
                continue
            element_name = _qname(element)
            if element_name.namespace not in _DRAWING_NAMESPACES:
                continue
            if element_name.localname == "t":
                chunks.append(element.text or "")
            elif element_name.localname == "br":
                chunks.append("\n")
            elif element_name.localname == "tab":
                chunks.append("\t")
        paragraphs.append("".join(chunks))
    return "\n".join(paragraphs)


def _shape_text(shape: Any) -> str:
    return _text_body_text(_first_child(shape, "txBody"))


def _shape_is_title(shape: Any) -> bool:
    non_visual = _first_child(shape, "nvSpPr")
    application_properties = None if non_visual is None else _first_child(non_visual, "nvPr")
    placeholder = None if application_properties is None else _first_child(application_properties, "ph")
    return placeholder is not None and placeholder.get("type") in {"title", "ctrTitle"}


def _graphic_kind(frame: Any) -> str | None:
    for element in frame.iter():
        if not isinstance(element.tag, str) or _local_name(element) != "graphicData":
            continue
        uri = (element.get("uri") or "").lower()
        if "table" in uri:
            return "table"
        if "chart" in uri:
            return "chart"
        if "ole" in uri:
            return "ole"
        if "diagram" in uri:
            return "smartart"
        if "model3d" in uri:
            return "model3d"
    if any(_local_name(element) == "tbl" for element in frame.iter() if isinstance(element.tag, str)):
        return "table"
    if any(_local_name(element) == "chart" and "chart" in (_qname(element).namespace or "").lower() for element in frame.iter() if isinstance(element.tag, str)):
        return "chart"
    if any(_local_name(element) == "oleObj" for element in frame.iter() if isinstance(element.tag, str)):
        return "ole"
    return None


def _is_presentation_object(element: Any) -> bool:
    if not isinstance(element.tag, str):
        return False
    name = _qname(element)
    return name.namespace in _PRESENTATION_NAMESPACES and name.localname in {
        "cxnSp",
        "graphicFrame",
        "grpSp",
        "pic",
        "sp",
    }


def _wrapped_picture(frame: Any) -> Any | None:
    return next(
        (element for element in frame.iter() if element is not frame and isinstance(element.tag, str) and _qname(element).namespace in _PRESENTATION_NAMESPACES and _local_name(element) == "pic"),
        None,
    )


def _picture_kind(picture: Any) -> str:
    non_visual = _first_child(picture, "nvPicPr")
    application_properties = None if non_visual is None else _first_child(non_visual, "nvPr")
    if application_properties is not None:
        child_names = {_local_name(child) for child in application_properties.iter() if isinstance(child.tag, str)}
        if "videoFile" in child_names:
            return "video"
        if "audioFile" in child_names:
            return "audio"
    return "picture"


def _picture_source_binding(
    picture: Any,
    *,
    slide: _Slide,
    package: _PackageInfo,
    label: str,
    require_supported_content_type: bool,
) -> _PptxPictureSourceBinding:
    name = _qname(picture)
    if name.namespace not in _PRESENTATION_NAMESPACES or name.localname != "pic":
        raise OfficeOperationError(f"{label} does not target a presentation picture")
    expected_drawing_namespace = _drawing_namespace_for_context(picture)
    expected_relationship_namespace = _document_relationship_namespace_for_context(picture)
    fills = [child for child in picture if isinstance(child.tag, str) and _qname(child).namespace == name.namespace and _local_name(child) == "blipFill"]
    if len(fills) != 1:
        raise OfficeOperationError(f"{label} requires exactly one direct picture blip fill")
    fill = fills[0]
    for element in fill.iter():
        if not isinstance(element.tag, str):
            continue
        namespace = _qname(element).namespace
        if namespace in _DRAWING_NAMESPACES and namespace != expected_drawing_namespace:
            raise OfficeOperationError(f"{label} mixes Strict and Transitional DrawingML")
    blips = [child for child in fill if isinstance(child.tag, str) and _qname(child).namespace == expected_drawing_namespace and _local_name(child) == "blip"]
    if len(blips) != 1:
        raise OfficeOperationError(f"{label} requires exactly one direct embedded-image blip")
    blip = blips[0]
    embed_attribute = str(etree.QName(expected_relationship_namespace, "embed"))
    relationship_attributes: list[tuple[Any, str]] = []
    for element in blip.iter():
        for attribute_name in element.attrib:
            try:
                attribute = etree.QName(attribute_name)
            except ValueError:
                continue
            if attribute.namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES:
                relationship_attributes.append((element, str(attribute)))
    if relationship_attributes != [(blip, embed_attribute)]:
        raise OfficeOperationError(f"{label} supports one embedded source and no linked or companion image")
    relationship_id = blip.get(embed_attribute) or ""
    if not relationship_id or len(relationship_id) > _MAX_RELATIONSHIP_ID_CHARS:
        raise OfficeOperationError(f"{label} has an invalid embedded image relationship")
    relationship = slide.relationships.get(relationship_id)
    expected_relationship_type = f"{expected_relationship_namespace}/image"
    if relationship is None or relationship.external or relationship.relationship_type != expected_relationship_type:
        raise OfficeOperationError(f"{label} has an invalid embedded image relationship")
    part_name = _resolve_relationship_target(slide.part_name, relationship.target)
    content_type = package.content_types.for_part(part_name) or ""
    if require_supported_content_type:
        if content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
            raise OfficeOperationError(f"{label} does not resolve to a supported PNG or baseline JPEG part")
    elif not content_type.lower().startswith("image/"):
        raise OfficeOperationError(f"{label} does not resolve to an image part")
    digest = package.part_sha256.get(part_name)
    if digest is None:
        raise OfficeOperationError(f"{label} image source digest is unavailable")
    return _PptxPictureSourceBinding(
        blip=blip,
        embed_attribute=embed_attribute,
        relationship_id=relationship_id,
        part_name=part_name,
        content_type=content_type,
        sha256=digest,
    )


def _picture_source_record(
    picture: Any,
    *,
    slide: _Slide,
    package: _PackageInfo,
) -> dict[str, Any] | None:
    try:
        binding = _picture_source_binding(
            picture,
            slide=slide,
            package=package,
            label="PPTX picture",
            require_supported_content_type=False,
        )
    except OfficeOperationError:
        return None
    return {
        "relationship_id": binding.relationship_id,
        "part_name": binding.part_name,
        "content_type": binding.content_type,
        "size_bytes": package.part_sizes.get(binding.part_name),
        "sha256": binding.sha256,
    }


def _shape_kind(shape: Any) -> str:
    if _shape_is_title(shape):
        return "title"
    non_visual = _first_child(shape, "nvSpPr")
    application_properties = None if non_visual is None else _first_child(non_visual, "nvPr")
    if application_properties is not None and _first_child(application_properties, "ph") is not None:
        return "placeholder"
    drawing_properties = None if non_visual is None else _first_child(non_visual, "cNvSpPr")
    if drawing_properties is not None and (drawing_properties.get("txBox") or "").lower() in {"1", "on", "true"}:
        return "text_box"
    return "shape"


def _logical_child(element: Any) -> tuple[Any, str, str] | None:
    if not _is_presentation_object(element):
        return None
    local_name = _local_name(element)
    if local_name == "sp":
        return element, _shape_kind(element), "shape"
    if local_name == "pic":
        return element, _picture_kind(element), "picture"
    if local_name == "grpSp":
        return element, "group", "group"
    if local_name == "cxnSp":
        return element, "connector", "connector"

    graphic_kind = _graphic_kind(element)
    if graphic_kind is None:
        wrapped_picture = _wrapped_picture(element)
        if wrapped_picture is not None:
            return wrapped_picture, _picture_kind(wrapped_picture), "picture"
        return element, "graphic_frame", "graphic_frame"
    return element, graphic_kind, graphic_kind


def _direct_logical_children(container: Any) -> list[tuple[Any, Any, str, str]]:
    children: list[tuple[Any, Any, str, str]] = []
    for child in container:
        if not isinstance(child.tag, str):
            continue
        if _local_name(child) == "AlternateContent":
            logical = _model3d_alternate_content_child(child)
            if logical is not None:
                logical_element, kind, path_kind = logical
                children.append((logical_element, logical_element, kind, path_kind))
            continue
        logical = _logical_child(child)
        if logical is None:
            continue
        logical_element, kind, path_kind = logical
        children.append((child, logical_element, kind, path_kind))
    return children


def _model3d_alternate_content_child(
    alternate_content: Any,
) -> tuple[Any, str, str] | None:
    for branch in _children(alternate_content, "Choice"):
        if not any(isinstance(element.tag, str) and _local_name(element) == "model3d" and _qname(element).namespace in _MODEL3D_NAMESPACES for element in branch.iter()):
            continue
        for child in branch:
            logical = _logical_child(child)
            if logical is not None:
                logical_element, _, _ = logical
                return logical_element, "model3d", "model3d"
    return None


def _non_visual_drawing_properties(element: Any) -> Any | None:
    container_name = {
        "cxnSp": "nvCxnSpPr",
        "graphicFrame": "nvGraphicFramePr",
        "grpSp": "nvGrpSpPr",
        "pic": "nvPicPr",
        "sp": "nvSpPr",
    }.get(_local_name(element))
    if container_name is None:
        return None
    container = _first_child(element, container_name)
    return None if container is None else _first_child(container, "cNvPr")


def _object_id(element: Any) -> int | None:
    non_visual = _non_visual_drawing_properties(element)
    raw_id = None if non_visual is None else non_visual.get("id")
    if raw_id is None:
        return None
    try:
        value = int(raw_id)
    except ValueError:
        return None
    return value if 0 <= value <= 4_294_967_295 else None


def _slide_object_refs(slide: Any, *, slide_index: int) -> list[_ObjectRef]:
    tree = _shape_tree(slide)
    if tree is None:
        return []

    id_counts: dict[int, int] = {}

    def count_ids(container: Any) -> None:
        for container_element, logical_element, _, _ in _direct_logical_children(container):
            object_id = _object_id(logical_element)
            if object_id is not None:
                id_counts[object_id] = id_counts.get(object_id, 0) + 1
            if _local_name(container_element) == "grpSp":
                count_ids(container_element)

    count_ids(tree)
    refs: list[_ObjectRef] = []

    def walk(container: Any, parent_path: str) -> None:
        positional_counts: dict[str, int] = {}
        for z_order, (container_element, logical_element, kind, path_kind) in enumerate(
            _direct_logical_children(container),
            start=1,
        ):
            positional_index = positional_counts.get(path_kind, 0) + 1
            positional_counts[path_kind] = positional_index
            object_id = _object_id(logical_element)
            if object_id is not None and id_counts.get(object_id) == 1:
                segment = f"{path_kind}[@id={object_id}]"
                identity_source = "cNvPr.id"
            else:
                segment = f"{path_kind}[{positional_index}]"
                identity_source = "position"
            path = f"{parent_path}/{segment}"
            refs.append(
                _ObjectRef(
                    element=logical_element,
                    container_element=container_element,
                    kind=kind,
                    path_kind=path_kind,
                    path=path,
                    parent_path=parent_path,
                    z_order=z_order,
                    positional_index=positional_index,
                    object_id=object_id,
                    identity_source=identity_source,
                )
            )
            if _local_name(container_element) == "grpSp":
                walk(container_element, path)

    walk(tree, f"/slide[{slide_index}]")
    return refs


def _count_logical_objects(slide: Any) -> int:
    return len(_slide_object_refs(slide, slide_index=1))


def _integer_attribute(element: Any | None, attribute: str, *, path: str) -> int | None:
    raw_value = None if element is None else element.get(attribute)
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except ValueError as exc:
        raise OfficePackageError(f"PPTX object {path} has invalid geometry") from exc


def _format_integer_attribute(
    element: Any | None,
    attribute: str,
    *,
    path: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    raw_value = None if element is None else element.get(attribute)
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise OfficePackageError(f"PPTX formatting at {path} has invalid {attribute}") from exc
    if minimum is not None and value < minimum:
        raise OfficePackageError(f"PPTX formatting at {path} has out-of-range {attribute}")
    if maximum is not None and value > maximum:
        raise OfficePackageError(f"PPTX formatting at {path} has out-of-range {attribute}")
    return value


def _boolean_attribute(element: Any | None, attribute: str, *, path: str) -> bool | None:
    raw_value = None if element is None else element.get(attribute)
    if raw_value is None:
        return None
    normalized = raw_value.lower()
    if normalized in {"1", "on", "true"}:
        return True
    if normalized in {"0", "false", "off"}:
        return False
    raise OfficePackageError(f"PPTX formatting at {path} has invalid {attribute}")


def _bounded_attribute(
    element: Any | None,
    attribute: str,
    *,
    limit: int = 256,
) -> tuple[str | None, bool]:
    return _bounded_string(
        None if element is None else element.get(attribute),
        limit,
    )


def _color_transform_records(
    color_element: Any,
    *,
    path: str,
) -> tuple[list[dict[str, Any]], int]:
    elements = [child for child in color_element if isinstance(child.tag, str) and _qname(child).namespace in _DRAWING_NAMESPACES and _local_name(child) in _COLOR_TRANSFORM_SPECS]
    records: list[dict[str, Any]] = []
    for index, transform in enumerate(elements[:_MAX_COLOR_TRANSFORMS], start=1):
        local_name = _local_name(transform)
        transform_type, unit, divisor = _COLOR_TRANSFORM_SPECS[local_name]
        transform_path = f"{path}/color_transform[{index}]"
        value = _format_integer_attribute(
            transform,
            "val",
            path=transform_path,
            minimum=-2_147_483_648,
            maximum=2_147_483_647,
        )
        if value is None:
            raise OfficePackageError(f"PPTX formatting at {transform_path} has a color transform without val")
        records.append(
            {
                "type": transform_type,
                "value": value,
                unit: round(value / divisor, 6),
            }
        )
    return records, len(elements)


def _color_record(color_element: Any, *, path: str) -> dict[str, Any]:
    color_type = _local_name(color_element)
    color: dict[str, Any]
    if color_type == "srgbClr":
        value = (color_element.get("val") or "").upper()
        if len(value) != 6 or any(char not in "0123456789ABCDEF" for char in value):
            raise OfficePackageError(f"PPTX formatting at {path} has invalid RGB color")
        color = {"type": "rgb", "value": f"#{value}"}
    elif color_type == "scrgbClr":
        color = {"type": "sc_rgb"}
        for attribute, key in (
            ("r", "red_percent"),
            ("g", "green_percent"),
            ("b", "blue_percent"),
        ):
            value = _format_integer_attribute(
                color_element,
                attribute,
                path=path,
                minimum=0,
                maximum=100_000,
            )
            if value is not None:
                color[key] = round(value / 1_000, 6)
    elif color_type == "hslClr":
        color = {"type": "hsl"}
        hue = _format_integer_attribute(
            color_element,
            "hue",
            path=path,
            minimum=0,
            maximum=21_600_000,
        )
        saturation = _format_integer_attribute(
            color_element,
            "sat",
            path=path,
            minimum=0,
            maximum=100_000,
        )
        luminance = _format_integer_attribute(
            color_element,
            "lum",
            path=path,
            minimum=0,
            maximum=100_000,
        )
        if hue is not None:
            color["hue_degrees"] = round(hue / 60_000, 6)
        if saturation is not None:
            color["saturation_percent"] = round(saturation / 1_000, 6)
        if luminance is not None:
            color["luminance_percent"] = round(luminance / 1_000, 6)
    else:
        mapped_type = {
            "prstClr": "preset",
            "schemeClr": "scheme",
            "sysClr": "system",
        }[color_type]
        value, value_truncated = _bounded_attribute(color_element, "val")
        color = {"type": mapped_type}
        if value is not None:
            color["value"] = value
        if value_truncated:
            color["value_truncated"] = True
        if color_type == "sysClr":
            last_rgb = (color_element.get("lastClr") or "").upper()
            if last_rgb:
                if len(last_rgb) != 6 or any(char not in "0123456789ABCDEF" for char in last_rgb):
                    raise OfficePackageError(f"PPTX formatting at {path} has invalid system fallback color")
                color["last_rgb"] = f"#{last_rgb}"

    alpha = _first_child(color_element, "alpha")
    opacity = _format_integer_attribute(
        alpha,
        "val",
        path=path,
        minimum=0,
        maximum=100_000,
    )
    if opacity is not None:
        color["opacity_percent"] = round(opacity / 1_000, 6)
    transforms, transform_count = _color_transform_records(
        color_element,
        path=path,
    )
    if transform_count:
        color.update(
            {
                "transform_count": transform_count,
                "transforms_returned": len(transforms),
                "transforms_truncated": len(transforms) < transform_count,
                "transforms": transforms,
            }
        )
    return color


def _direct_color(element: Any | None, *, path: str) -> dict[str, Any] | None:
    if element is None:
        return None
    color_element = next(
        (
            child
            for child in element
            if isinstance(child.tag, str)
            and _qname(child).namespace in _DRAWING_NAMESPACES
            and _local_name(child)
            in {
                "hslClr",
                "prstClr",
                "schemeClr",
                "scrgbClr",
                "srgbClr",
                "sysClr",
            }
        ),
        None,
    )
    return None if color_element is None else _color_record(color_element, path=path)


def _relationship_ids_from_blip(blip: Any | None) -> list[str]:
    relationship_ids: list[str] = []
    if blip is None:
        return relationship_ids
    for attribute_name, relationship_id in blip.attrib.items():
        try:
            attribute = etree.QName(attribute_name)
        except ValueError:
            continue
        if attribute.namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES and attribute.localname in {"embed", "link"} and relationship_id:
            relationship_ids.append(relationship_id)
    return relationship_ids


def _percentage_rectangle(
    element: Any | None,
    *,
    path: str,
) -> dict[str, float] | None:
    if element is None:
        return None
    result = {}
    for attribute, key in (
        ("l", "left_percent"),
        ("t", "top_percent"),
        ("r", "right_percent"),
        ("b", "bottom_percent"),
    ):
        value = _format_integer_attribute(element, attribute, path=path)
        if value is not None:
            result[key] = round(value / 1_000, 6)
    return result or None


def _blip_fill_formatting(
    blip_fill: Any | None,
    *,
    path: str,
) -> dict[str, Any] | None:
    if blip_fill is None:
        return None
    result: dict[str, Any] = {}
    dpi = _format_integer_attribute(
        blip_fill,
        "dpi",
        path=path,
        minimum=0,
    )
    if dpi is not None:
        result["dpi"] = dpi
    rotate_with_shape = _boolean_attribute(
        blip_fill,
        "rotWithShape",
        path=path,
    )
    if rotate_with_shape is not None:
        result["rotate_with_shape"] = rotate_with_shape

    crop = _percentage_rectangle(
        _first_child(blip_fill, "srcRect"),
        path=path,
    )
    if crop is not None:
        result["crop"] = crop

    tile = _first_child(blip_fill, "tile")
    stretch = _first_child(blip_fill, "stretch")
    if tile is not None:
        offset_x = _format_integer_attribute(tile, "tx", path=path)
        offset_y = _format_integer_attribute(tile, "ty", path=path)
        scale_x = _format_integer_attribute(tile, "sx", path=path)
        scale_y = _format_integer_attribute(tile, "sy", path=path)
        alignment, alignment_truncated = _bounded_attribute(tile, "algn")
        flip, flip_truncated = _bounded_attribute(tile, "flip")
        attribute_names = set(tile.attrib)
        is_canonical_center = (
            attribute_names == {"sx", "sy", "algn", "flip"} and offset_x is None and offset_y is None and scale_x == 100_000 and scale_y == 100_000 and alignment == "ctr" and flip == "none" and not alignment_truncated and not flip_truncated
        )
        if is_canonical_center:
            result["fill_mode"] = "center"
        else:
            result["fill_mode"] = "tile"
        tile_record: dict[str, Any] = {}
        if offset_x is not None:
            tile_record["offset_x_emu"] = offset_x
        if offset_y is not None:
            tile_record["offset_y_emu"] = offset_y
        if scale_x is not None:
            tile_record["scale_x_percent"] = round(scale_x / 1_000, 6)
        if scale_y is not None:
            tile_record["scale_y_percent"] = round(scale_y / 1_000, 6)
        if alignment is not None:
            tile_record["alignment"] = _PPTX_TILE_ALIGNMENT_FROM_XML.get(
                alignment,
                alignment,
            )
        if alignment_truncated:
            tile_record["alignment_truncated"] = True
        if flip is not None:
            tile_record["flip"] = _PPTX_TILE_FLIP_FROM_XML.get(flip, flip)
        if flip_truncated:
            tile_record["flip_truncated"] = True
        if tile_record and not is_canonical_center:
            result["tile"] = tile_record
    elif stretch is not None:
        result["fill_mode"] = "stretch"
        fill_rectangle_element = _first_child(stretch, "fillRect")
        if fill_rectangle_element is not None:
            result["fill_rectangle"] = (
                _percentage_rectangle(
                    fill_rectangle_element,
                    path=path,
                )
                or {}
            )

    blip = _first_child(blip_fill, "blip")
    source_relationship_ids = _relationship_ids_from_blip(blip)
    if source_relationship_ids:
        relationship_ids = []
        relationship_ids_truncated = len(source_relationship_ids) > _MAX_RELATIONSHIP_IDS_PER_OBJECT
        for relationship_id in source_relationship_ids[:_MAX_RELATIONSHIP_IDS_PER_OBJECT]:
            bounded_relationship_id, relationship_id_truncated = _bounded_string(
                relationship_id,
                _MAX_RELATIONSHIP_ID_CHARS,
            )
            relationship_ids.append(bounded_relationship_id or "")
            relationship_ids_truncated = relationship_ids_truncated or relationship_id_truncated
        result["relationship_ids"] = relationship_ids
        if relationship_ids_truncated:
            result["relationship_ids_truncated"] = True
    if blip is None:
        return result or None

    compression_state, compression_state_truncated = _bounded_attribute(
        blip,
        "cstate",
    )
    if compression_state is not None:
        result["compression_state"] = compression_state
    if compression_state_truncated:
        result["compression_state_truncated"] = True

    effects: dict[str, Any] = {}
    alpha_modulation = _format_integer_attribute(
        _first_child(blip, "alphaModFix"),
        "amt",
        path=path,
        minimum=0,
        maximum=100_000,
    )
    if alpha_modulation is not None:
        effects["alpha_modulation_percent"] = round(
            alpha_modulation / 1_000,
            6,
        )
    luminance = _first_child(blip, "lum")
    for attribute, key in (
        ("bright", "brightness_percent"),
        ("contrast", "contrast_percent"),
    ):
        value = _format_integer_attribute(
            luminance,
            attribute,
            path=path,
            minimum=-100_000,
            maximum=100_000,
        )
        if value is not None:
            effects[key] = round(value / 1_000, 6)
    if _first_child(blip, "grayscl") is not None:
        effects["grayscale"] = True
    bilevel_threshold = _format_integer_attribute(
        _first_child(blip, "biLevel"),
        "thresh",
        path=path,
        minimum=0,
        maximum=100_000,
    )
    if bilevel_threshold is not None:
        effects["bilevel_threshold_percent"] = round(
            bilevel_threshold / 1_000,
            6,
        )
    duotone = _first_child(blip, "duotone")
    if duotone is not None:
        color_elements = [
            child
            for child in duotone
            if isinstance(child.tag, str)
            and _qname(child).namespace in _DRAWING_NAMESPACES
            and _local_name(child)
            in {
                "hslClr",
                "prstClr",
                "schemeClr",
                "scrgbClr",
                "srgbClr",
                "sysClr",
            }
        ]
        effects["duotone_colors"] = [_color_record(color, path=path) for color in color_elements[:2]]
        if len(color_elements) > 2:
            effects["duotone_colors_truncated"] = True
    if effects:
        result["effects"] = effects
    return result or None


def _fill_style(element: Any | None, *, path: str) -> dict[str, Any] | None:
    if element is None:
        return None
    fill = next(
        (child for child in element if isinstance(child.tag, str) and _qname(child).namespace in _DRAWING_NAMESPACES and _local_name(child) in {"blipFill", "gradFill", "grpFill", "noFill", "pattFill", "solidFill"}),
        None,
    )
    if fill is None:
        return None

    fill_type = _local_name(fill)
    if fill_type == "noFill":
        return {"type": "none"}
    if fill_type == "grpFill":
        return {"type": "group"}
    if fill_type == "solidFill":
        result: dict[str, Any] = {"type": "solid"}
        color = _direct_color(fill, path=path)
        if color is not None:
            result["color"] = color
        return result
    if fill_type == "blipFill":
        result = {"type": "image"}
        image_formatting = _blip_fill_formatting(fill, path=path)
        if image_formatting is not None:
            result.update(image_formatting)
        return result
    if fill_type == "pattFill":
        result = {"type": "pattern"}
        preset, preset_truncated = _bounded_attribute(fill, "prst")
        if preset is not None:
            result["preset"] = preset
        if preset_truncated:
            result["preset_truncated"] = True
        for child_name, key in (
            ("fgClr", "foreground_color"),
            ("bgClr", "background_color"),
        ):
            color = _direct_color(_first_child(fill, child_name), path=path)
            if color is not None:
                result[key] = color
        return result

    result = {"type": "gradient"}
    rotate_with_shape = _boolean_attribute(fill, "rotWithShape", path=path)
    if rotate_with_shape is not None:
        result["rotate_with_shape"] = rotate_with_shape
    stop_list = _first_child(fill, "gsLst")
    stops = [] if stop_list is None else _children(stop_list, "gs")
    returned_stops = stops[:_MAX_GRADIENT_STOPS]
    if returned_stops:
        result["stops"] = []
        for stop in returned_stops:
            stop_record: dict[str, Any] = {}
            position = _format_integer_attribute(
                stop,
                "pos",
                path=path,
                minimum=0,
                maximum=100_000,
            )
            if position is not None:
                stop_record["position_percent"] = round(position / 1_000, 6)
            color = _direct_color(stop, path=path)
            if color is not None:
                stop_record["color"] = color
            result["stops"].append(stop_record)
    if len(returned_stops) < len(stops):
        result["stops_truncated"] = True
    linear = _first_child(fill, "lin")
    if linear is not None:
        angle = _format_integer_attribute(
            linear,
            "ang",
            path=path,
            minimum=0,
            maximum=21_600_000,
        )
        result["geometry"] = "linear"
        if angle is not None:
            result["angle_degrees"] = round(angle / 60_000, 6)
        scaled = _boolean_attribute(linear, "scaled", path=path)
        if scaled is not None:
            result["scaled"] = scaled
    path_gradient = _first_child(fill, "path")
    if path_gradient is not None:
        gradient_path, path_truncated = _bounded_attribute(path_gradient, "path")
        result["geometry"] = "path"
        if gradient_path is not None:
            result["path"] = gradient_path
        if path_truncated:
            result["path_truncated"] = True
        fill_to_rectangle_element = _first_child(path_gradient, "fillToRect")
        if fill_to_rectangle_element is not None:
            result["fill_to_rectangle"] = (
                _percentage_rectangle(
                    fill_to_rectangle_element,
                    path=path,
                )
                or {}
            )
    return result


def _line_style(properties: Any | None, *, path: str) -> dict[str, Any] | None:
    line = None if properties is None else _first_child(properties, "ln")
    if line is None:
        return None
    result: dict[str, Any] = {}
    width = _format_integer_attribute(
        line,
        "w",
        path=path,
        minimum=0,
        maximum=100_000_000,
    )
    if width is not None:
        result["width_emu"] = width
    cap, cap_truncated = _bounded_attribute(line, "cap")
    if cap is not None:
        try:
            result["cap"] = _LINE_CAP_FROM_OOXML[cap]
        except KeyError as exc:
            raise OfficePackageError(f"PPTX formatting at {path} has invalid line cap") from exc
    if cap_truncated:
        result["cap_truncated"] = True
    for attribute, key, values in (
        ("cmpd", "compound", _LINE_COMPOUND_FROM_OOXML),
        ("algn", "alignment", _LINE_ALIGNMENT_FROM_OOXML),
    ):
        value, truncated = _bounded_attribute(line, attribute)
        if value is not None:
            try:
                result[key] = values[value]
            except KeyError as exc:
                raise OfficePackageError(f"PPTX formatting at {path} has invalid line {key}") from exc
        if truncated:
            result[f"{key}_truncated"] = True
    fill = _fill_style(line, path=path)
    if fill is not None:
        result["fill"] = fill
    preset_dash = _first_child(line, "prstDash")
    if preset_dash is not None:
        dash, dash_truncated = _bounded_attribute(preset_dash, "val")
        if dash is not None:
            try:
                result["dash"] = _LINE_DASH_FROM_OOXML[dash]
            except KeyError as exc:
                raise OfficePackageError(f"PPTX formatting at {path} has invalid preset line dash") from exc
        if dash_truncated:
            result["dash_truncated"] = True
    elif _first_child(line, "custDash") is not None:
        result["dash"] = "custom"
    for join in ("round", "bevel", "miter"):
        join_element = _first_child(line, join)
        if join_element is not None:
            result["join"] = join
            if join == "miter":
                miter_limit = _format_integer_attribute(
                    join_element,
                    "lim",
                    path=path,
                    minimum=0,
                    maximum=2_147_483_647,
                )
                if miter_limit is not None:
                    result["miter_limit_percent"] = round(miter_limit / 1_000, 6)
            break
    for child_name, key in (("headEnd", "head_end"), ("tailEnd", "tail_end")):
        arrow = _first_child(line, child_name)
        if arrow is None:
            continue
        arrow_record = {}
        for attribute, output_key, values in (
            ("type", "type", _LINE_END_TYPE_FROM_OOXML),
            ("w", "width", _LINE_END_SIZE_FROM_OOXML),
            ("len", "length", _LINE_END_SIZE_FROM_OOXML),
        ):
            value, truncated = _bounded_attribute(arrow, attribute)
            if value is not None:
                try:
                    arrow_record[output_key] = values[value]
                except KeyError as exc:
                    raise OfficePackageError(f"PPTX formatting at {path} has invalid {key} {output_key}") from exc
            if truncated:
                arrow_record[f"{output_key}_truncated"] = True
        result[key] = arrow_record
    return result


def _text_box_style(text_body: Any | None, *, path: str) -> dict[str, Any] | None:
    body_properties = None if text_body is None else _first_child(text_body, "bodyPr")
    if body_properties is None:
        return None
    result: dict[str, Any] = {}
    margins = {}
    for attribute, key in (
        ("lIns", "left_emu"),
        ("tIns", "top_emu"),
        ("rIns", "right_emu"),
        ("bIns", "bottom_emu"),
    ):
        value = _format_integer_attribute(
            body_properties,
            attribute,
            path=path,
            minimum=-_MAX_TEXT_INSET_EMU,
            maximum=_MAX_TEXT_INSET_EMU,
        )
        if value is not None:
            margins[key] = value
    if margins:
        result["margins"] = margins

    anchor, anchor_truncated = _bounded_attribute(body_properties, "anchor")
    if anchor is not None:
        result["vertical_anchor"] = {
            "t": "top",
            "ctr": "middle",
            "b": "bottom",
            "just": "justify",
            "dist": "distributed",
        }.get(anchor, anchor)
    if anchor_truncated:
        result["vertical_anchor_truncated"] = True
    wrap, wrap_truncated = _bounded_attribute(body_properties, "wrap")
    if wrap is not None:
        result["wrap"] = wrap != "none"
    if wrap_truncated:
        result["wrap_truncated"] = True
    vertical, vertical_truncated = _bounded_attribute(body_properties, "vert")
    if vertical is not None:
        result["text_direction"] = {
            "horz": "horizontal",
            "vert": "vertical_90",
            "vert270": "vertical_270",
            "wordArtVert": "stacked",
        }.get(vertical, vertical)
    if vertical_truncated:
        result["text_direction_truncated"] = True
    for attribute, key in (
        ("rtlCol", "right_to_left_columns"),
        ("anchorCtr", "anchor_center"),
        ("upright", "upright"),
    ):
        value = _boolean_attribute(body_properties, attribute, path=path)
        if value is not None:
            result[key] = value
    column_count = _format_integer_attribute(
        body_properties,
        "numCol",
        path=path,
        minimum=1,
        maximum=1_000,
    )
    if column_count is not None:
        result["column_count"] = column_count
    column_spacing = _format_integer_attribute(
        body_properties,
        "spcCol",
        path=path,
        minimum=0,
    )
    if column_spacing is not None:
        result["column_spacing_emu"] = column_spacing
    for attribute, key in (
        ("vertOverflow", "vertical_overflow"),
        ("horzOverflow", "horizontal_overflow"),
    ):
        value, truncated = _bounded_attribute(body_properties, attribute)
        if value is not None:
            result[key] = value
        if truncated:
            result[f"{key}_truncated"] = True

    normal_autofit = _first_child(body_properties, "normAutofit")
    if normal_autofit is not None:
        result["autofit"] = "normal"
        font_scale = _format_integer_attribute(
            normal_autofit,
            "fontScale",
            path=path,
            minimum=0,
            maximum=100_000,
        )
        line_reduction = _format_integer_attribute(
            normal_autofit,
            "lnSpcReduction",
            path=path,
            minimum=0,
            maximum=100_000,
        )
        if font_scale is not None:
            result["font_scale_percent"] = round(font_scale / 1_000, 6)
        if line_reduction is not None:
            result["line_spacing_reduction_percent"] = round(
                line_reduction / 1_000,
                6,
            )
    elif _first_child(body_properties, "spAutoFit") is not None:
        result["autofit"] = "shape"
    elif _first_child(body_properties, "noAutofit") is not None:
        result["autofit"] = "none"
    return result or None


def _shape_style(ref: _ObjectRef) -> dict[str, Any] | None:
    if _local_name(ref.element) not in {"cxnSp", "pic", "sp"}:
        return None
    properties = _first_child(ref.element, "spPr")
    result: dict[str, Any] = {}
    if properties is not None:
        preset_geometry = _first_child(properties, "prstGeom")
        if preset_geometry is not None:
            preset, preset_truncated = _bounded_attribute(
                preset_geometry,
                "prst",
            )
            geometry: dict[str, Any] = {"type": "preset"}
            if preset is not None:
                geometry["preset"] = preset
            if preset_truncated:
                geometry["preset_truncated"] = True
            result["geometry"] = geometry
        elif _first_child(properties, "custGeom") is not None:
            result["geometry"] = {"type": "custom"}
        fill = _fill_style(properties, path=ref.path)
        if fill is not None:
            result["fill"] = fill
        line = _line_style(properties, path=ref.path)
        if line is not None:
            result["line"] = line
    if ref.path_kind == "picture":
        picture = _blip_fill_formatting(
            _first_child(ref.element, "blipFill"),
            path=ref.path,
        )
        if picture is not None:
            result["picture"] = picture
    if ref.path_kind == "shape":
        text_box = _text_box_style(_first_child(ref.element, "txBody"), path=ref.path)
        if text_box is not None:
            result["text_box"] = text_box
    return result or None


def _spacing_value(element: Any | None, *, path: str) -> dict[str, Any] | None:
    if element is None:
        return None
    percent = _first_child(element, "spcPct")
    if percent is not None:
        value = _format_integer_attribute(percent, "val", path=path)
        if value is not None:
            return {"unit": "percent", "value": round(value / 1_000, 6)}
    points = _first_child(element, "spcPts")
    if points is not None:
        value = _format_integer_attribute(points, "val", path=path)
        if value is not None:
            return {"unit": "points", "value": round(value / 100, 6)}
    return None


def _run_formatting(properties: Any | None, *, path: str) -> dict[str, Any]:
    if properties is None:
        return {}
    result: dict[str, Any] = {}
    fonts: dict[str, Any] = {}
    for child_name, key in (
        ("latin", "latin"),
        ("ea", "east_asia"),
        ("cs", "complex_script"),
        ("sym", "symbol"),
    ):
        font = _first_child(properties, child_name)
        typeface, typeface_truncated = _bounded_attribute(font, "typeface", limit=100)
        if typeface is not None:
            fonts[key] = typeface
        if typeface_truncated:
            fonts[f"{key}_truncated"] = True
    if fonts:
        result["fonts"] = fonts

    size = _format_integer_attribute(
        properties,
        "sz",
        path=path,
        minimum=0,
        maximum=400_000,
    )
    if size is not None:
        result["font_size_points"] = round(size / 100, 6)
    for attribute, key in (("b", "bold"), ("i", "italic"), ("rtl", "right_to_left")):
        value = _boolean_attribute(properties, attribute, path=path)
        if value is not None:
            result[key] = value

    underline, underline_truncated = _bounded_attribute(properties, "u")
    if underline is not None:
        result["underline"] = {
            "sng": "single",
            "dbl": "double",
        }.get(underline, underline)
    if underline_truncated:
        result["underline_truncated"] = True
    strike, strike_truncated = _bounded_attribute(properties, "strike")
    if strike is not None:
        result["strike"] = {
            "dblStrike": "double",
            "noStrike": "none",
            "sngStrike": "single",
        }.get(strike, strike)
    if strike_truncated:
        result["strike_truncated"] = True
    caps, caps_truncated = _bounded_attribute(properties, "cap")
    if caps is not None:
        result["capitalization"] = caps
    if caps_truncated:
        result["capitalization_truncated"] = True

    spacing = _format_integer_attribute(properties, "spc", path=path)
    if spacing is not None:
        result["character_spacing_points"] = round(spacing / 100, 6)
    baseline = _format_integer_attribute(properties, "baseline", path=path)
    if baseline is not None:
        result["baseline_percent"] = round(baseline / 1_000, 6)
    kerning = _format_integer_attribute(
        properties,
        "kern",
        path=path,
        minimum=0,
    )
    if kerning is not None:
        result["kerning_points"] = round(kerning / 100, 6)
    language, language_truncated = _bounded_attribute(properties, "lang", limit=100)
    if language is not None:
        result["language"] = language
    if language_truncated:
        result["language_truncated"] = True

    fill = _fill_style(properties, path=path)
    if fill is not None:
        result["fill"] = fill
    highlight = _direct_color(_first_child(properties, "highlight"), path=path)
    if highlight is not None:
        result["highlight"] = highlight
    return result


def _paragraph_bullet(
    properties: Any | None,
    *,
    path: str,
) -> dict[str, Any] | None:
    if properties is None:
        return None
    if _first_child(properties, "buNone") is not None:
        return {"type": "none"}
    bullet_character = _first_child(properties, "buChar")
    if bullet_character is not None:
        character, truncated = _bounded_attribute(bullet_character, "char", limit=32)
        result: dict[str, Any] = {"type": "character"}
        if character is not None:
            result["character"] = character
        if truncated:
            result["character_truncated"] = True
        return result
    automatic_number = _first_child(properties, "buAutoNum")
    if automatic_number is not None:
        result = {"type": "automatic_number"}
        numbering_type, numbering_type_truncated = _bounded_attribute(
            automatic_number,
            "type",
        )
        if numbering_type is not None:
            result["numbering_type"] = numbering_type
        if numbering_type_truncated:
            result["numbering_type_truncated"] = True
        start_at = _format_integer_attribute(
            automatic_number,
            "startAt",
            path=path,
            minimum=1,
        )
        if start_at is not None:
            result["start_at"] = start_at
        return result
    return None


def _paragraph_formatting(properties: Any | None, *, path: str) -> dict[str, Any]:
    if properties is None:
        return {}
    result: dict[str, Any] = {}
    alignment, alignment_truncated = _bounded_attribute(properties, "algn")
    if alignment is not None:
        result["alignment"] = {
            "l": "left",
            "ctr": "center",
            "r": "right",
            "just": "justify",
            "justLow": "justify_low",
            "dist": "distributed",
            "thaiDist": "thai_distributed",
        }.get(alignment, alignment)
    if alignment_truncated:
        result["alignment_truncated"] = True
    for attribute, key in (
        ("lvl", "level"),
        ("indent", "indent_emu"),
        ("marL", "margin_left_emu"),
        ("marR", "margin_right_emu"),
        ("defTabSz", "default_tab_size_emu"),
    ):
        value = _format_integer_attribute(properties, attribute, path=path)
        if value is not None:
            result[key] = value
    right_to_left = _boolean_attribute(properties, "rtl", path=path)
    if right_to_left is not None:
        result["right_to_left"] = right_to_left
    font_alignment, font_alignment_truncated = _bounded_attribute(properties, "fontAlgn")
    if font_alignment is not None:
        result["font_alignment"] = font_alignment
    if font_alignment_truncated:
        result["font_alignment_truncated"] = True

    for child_name, key in (
        ("lnSpc", "line_spacing"),
        ("spcBef", "space_before"),
        ("spcAft", "space_after"),
    ):
        spacing = _spacing_value(_first_child(properties, child_name), path=path)
        if spacing is not None:
            result[key] = spacing
    bullet = _paragraph_bullet(properties, path=path)
    if bullet is not None:
        result["bullet"] = bullet
    default_run_properties = _first_child(properties, "defRPr")
    if default_run_properties is not None:
        result["default_run_formatting"] = _run_formatting(
            default_run_properties,
            path=f"{path}/default_run",
        )

    tab_list = _first_child(properties, "tabLst")
    if tab_list is not None:
        tab_stops = _children(tab_list, "tab")
        result["tab_stops"] = []
        for tab in tab_stops[:64]:
            tab_record: dict[str, Any] = {}
            position = _format_integer_attribute(tab, "pos", path=path)
            if position is not None:
                tab_record["position_emu"] = position
            tab_alignment, truncated = _bounded_attribute(tab, "algn")
            if tab_alignment is not None:
                tab_record["alignment"] = tab_alignment
            if truncated:
                tab_record["alignment_truncated"] = True
            result["tab_stops"].append(tab_record)
        if len(tab_stops) > 64:
            result["tab_stops_truncated"] = True
    return result


def _paragraph_text(paragraph: Any) -> str:
    chunks: list[str] = []
    for child in paragraph:
        if not isinstance(child.tag, str):
            continue
        child_name = _local_name(child)
        if child_name in {"r", "fld"}:
            text = _first_child(child, "t")
            chunks.append("" if text is None else text.text or "")
        elif child_name == "br":
            chunks.append("\n")
        elif child_name == "tab":
            chunks.append("\t")
    return "".join(chunks)


def _bounded_formatting_text(
    value: str,
    *,
    budget: dict[str, int],
) -> tuple[str, bool]:
    available = max(
        0,
        min(
            _MAX_INSPECT_FORMATTING_ITEM_CHARS,
            _MAX_INSPECT_FORMATTING_TEXT_CHARS - budget["characters"],
        ),
    )
    returned = value[:available]
    budget["characters"] += len(returned)
    return returned, len(returned) < len(value)


def _paragraph_segments(
    paragraph: Any,
    *,
    paragraph_path: str,
    budget: dict[str, int],
) -> tuple[list[dict[str, Any]], int, bool]:
    source_segments = [child for child in paragraph if isinstance(child.tag, str) and _local_name(child) in {"br", "fld", "r", "tab"}]
    segments: list[dict[str, Any]] = []
    counters: dict[str, int] = {}
    truncated = False
    for child in source_segments:
        if budget["segments"] >= _MAX_INSPECT_FORMATTED_SEGMENTS:
            truncated = True
            break
        source_kind = _local_name(child)
        kind, path_kind = {
            "br": ("line_break", "line_break"),
            "fld": ("field", "field"),
            "r": ("run", "run"),
            "tab": ("tab", "tab"),
        }[source_kind]
        index = counters.get(path_kind, 0) + 1
        counters[path_kind] = index
        segment_path = f"{paragraph_path}/{path_kind}[{index}]"
        if source_kind in {"fld", "r"}:
            text_element = _first_child(child, "t")
            source_text = "" if text_element is None else text_element.text or ""
        elif source_kind == "br":
            source_text = "\n"
        else:
            source_text = "\t"
        text, text_truncated = _bounded_formatting_text(source_text, budget=budget)
        segment: dict[str, Any] = {
            "path": segment_path,
            "kind": kind,
            "text": text,
            "formatting": _run_formatting(
                _first_child(child, "rPr"),
                path=segment_path,
            ),
        }
        if text_truncated:
            segment["text_truncated"] = True
            truncated = True
        if source_kind == "fld":
            for attribute, key in (("id", "field_id"), ("type", "field_type")):
                value, value_truncated = _bounded_attribute(child, attribute)
                if value is not None:
                    segment[key] = value
                if value_truncated:
                    segment[f"{key}_truncated"] = True
                    truncated = True
        segments.append(segment)
        budget["segments"] += 1
    return segments, len(source_segments), truncated or len(segments) < len(source_segments)


def _text_body_inspection(
    text_body: Any,
    *,
    base_path: str,
    budget: dict[str, int],
) -> tuple[dict[str, Any], bool]:
    source_paragraphs = _children(text_body, "p")
    paragraphs: list[dict[str, Any]] = []
    truncated = False
    for index, paragraph in enumerate(source_paragraphs, start=1):
        if budget["paragraphs"] >= _MAX_INSPECT_FORMATTED_PARAGRAPHS:
            truncated = True
            break
        paragraph_path = f"{base_path}/paragraph[{index}]"
        paragraph_text, text_truncated = _bounded_formatting_text(
            _paragraph_text(paragraph),
            budget=budget,
        )
        segments, segment_count, segments_truncated = _paragraph_segments(
            paragraph,
            paragraph_path=paragraph_path,
            budget=budget,
        )
        record: dict[str, Any] = {
            "path": paragraph_path,
            "text": paragraph_text,
            "formatting": _paragraph_formatting(
                _first_child(paragraph, "pPr"),
                path=paragraph_path,
            ),
            "segment_count": segment_count,
            "segments_returned": len(segments),
            "segments_truncated": segments_truncated,
            "segments": segments,
        }
        if text_truncated:
            record["text_truncated"] = True
        end_properties = _first_child(paragraph, "endParaRPr")
        if end_properties is not None:
            record["end_run_formatting"] = _run_formatting(
                end_properties,
                path=f"{paragraph_path}/end_run",
            )
        paragraphs.append(record)
        budget["paragraphs"] += 1
        truncated = truncated or text_truncated or segments_truncated
    result = {
        "paragraph_count": len(source_paragraphs),
        "paragraphs_returned": len(paragraphs),
        "paragraphs_truncated": len(paragraphs) < len(source_paragraphs),
        "paragraphs": paragraphs,
    }
    return result, truncated or len(paragraphs) < len(source_paragraphs)


def _table_element(ref: _ObjectRef) -> Any | None:
    return next(
        (element for element in ref.element.iter() if isinstance(element.tag, str) and _local_name(element) == "tbl" and _qname(element).namespace in _DRAWING_NAMESPACES),
        None,
    )


def _table_cells_inspection(
    ref: _ObjectRef,
    *,
    budget: dict[str, int],
) -> tuple[dict[str, Any], bool]:
    table = _table_element(ref)
    source_cells: list[tuple[int, int, Any]] = []
    if table is not None:
        for row_index, row in enumerate(_children(table, "tr"), start=1):
            for cell_index, cell in enumerate(_children(row, "tc"), start=1):
                source_cells.append((row_index, cell_index, cell))
    cells: list[dict[str, Any]] = []
    truncated = False
    for row_index, cell_index, cell in source_cells:
        if budget["cells"] >= _MAX_INSPECT_FORMATTED_CELLS:
            truncated = True
            break
        cell_path = f"{ref.path}/row[{row_index}]/cell[{cell_index}]"
        record: dict[str, Any] = {
            "path": cell_path,
            "row": row_index,
            "column": cell_index,
        }
        text_body = _first_child(cell, "txBody")
        if text_body is not None:
            record["text_body"], text_truncated = _text_body_inspection(
                text_body,
                base_path=cell_path,
                budget=budget,
            )
            truncated = truncated or text_truncated
        cells.append(record)
        budget["cells"] += 1
    return (
        {
            "cell_count": len(source_cells),
            "cells_returned": len(cells),
            "cells_truncated": len(cells) < len(source_cells),
            "cells": cells,
        },
        truncated or len(cells) < len(source_cells),
    )


def _object_text(ref: _ObjectRef) -> str:
    if ref.path_kind == "shape":
        return _shape_text(ref.element)
    if ref.kind != "table":
        return ""
    table = _table_element(ref)
    if table is None:
        return ""
    return "\n".join(_text_body_text(_first_child(cell, "txBody")) for row in _children(table, "tr") for cell in _children(row, "tc"))


def _matches_object_selector(
    ref: _ObjectRef,
    selector: PptxObjectSelector | None,
) -> bool:
    if selector is None:
        return True
    if selector.paths is not None and ref.path not in selector.paths:
        return False
    if selector.kinds is not None and ref.kind not in selector.kinds:
        return False
    non_visual = _non_visual_drawing_properties(ref.element)
    name, _ = _bounded_string(
        None if non_visual is None else non_visual.get("name"),
        _MAX_OBJECT_NAME_CHARS,
    )
    alt_text = None if non_visual is None else non_visual.get("descr")
    if selector.name_equals is not None and name != selector.name_equals:
        return False
    if selector.has_alt_text is not None:
        has_alt_text = bool((alt_text or "").strip())
        if has_alt_text is not selector.has_alt_text:
            return False
    if selector.contains_text is not None or selector.has_text is not None:
        text = _object_text(ref)
        if selector.contains_text is not None and selector.contains_text not in text:
            return False
        if selector.has_text is not None and bool(text.strip()) is not selector.has_text:
            return False
    return True


def _object_transform(ref: _ObjectRef) -> Any | None:
    local_name = _local_name(ref.element)
    if local_name == "grpSp":
        properties = _first_child(ref.element, "grpSpPr")
    elif local_name == "graphicFrame":
        return _first_child(ref.element, "xfrm")
    else:
        properties = _first_child(ref.element, "spPr")
    return None if properties is None else _first_child(properties, "xfrm")


def _object_geometry(ref: _ObjectRef) -> dict[str, Any]:
    transform = _object_transform(ref)
    if transform is None:
        return {}
    offset = _first_child(transform, "off")
    extents = _first_child(transform, "ext")
    child_offset = _first_child(transform, "chOff")
    child_extents = _first_child(transform, "chExt")
    geometry = {
        key: value
        for key, value in {
            "x_emu": _integer_attribute(offset, "x", path=ref.path),
            "y_emu": _integer_attribute(offset, "y", path=ref.path),
            "width_emu": _integer_attribute(extents, "cx", path=ref.path),
            "height_emu": _integer_attribute(extents, "cy", path=ref.path),
            "child_x_emu": _integer_attribute(child_offset, "x", path=ref.path),
            "child_y_emu": _integer_attribute(child_offset, "y", path=ref.path),
            "child_width_emu": _integer_attribute(child_extents, "cx", path=ref.path),
            "child_height_emu": _integer_attribute(child_extents, "cy", path=ref.path),
        }.items()
        if value is not None
    }
    rotation = _integer_attribute(transform, "rot", path=ref.path)
    if rotation is not None:
        geometry["rotation_degrees"] = round(rotation / 60_000, 6)
    if (transform.get("flipH") or "").lower() in {"1", "on", "true"}:
        geometry["flip_horizontal"] = True
    if (transform.get("flipV") or "").lower() in {"1", "on", "true"}:
        geometry["flip_vertical"] = True
    return geometry


def _object_relationship_ids(ref: _ObjectRef) -> list[str]:
    relationship_ids: list[str] = []
    seen: set[str] = set()

    def visit(element: Any, *, root: bool) -> None:
        if not root and ref.kind == "group" and _is_presentation_object(element):
            return
        for attribute_name, relationship_id in element.attrib.items():
            try:
                attribute = etree.QName(attribute_name)
            except ValueError:
                continue
            if attribute.namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES and attribute.localname in {"embed", "id", "link"} and relationship_id and relationship_id not in seen:
                seen.add(relationship_id)
                relationship_ids.append(relationship_id)
        for child in element:
            if isinstance(child.tag, str):
                visit(child, root=False)

    visit(ref.element, root=True)
    return relationship_ids


def _bounded_string(value: str | None, limit: int) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    return value[:limit], len(value) > limit


def _attribute_by_local_name(element: Any | None, attribute: str) -> str | None:
    if element is None:
        return None
    direct = element.get(attribute)
    if direct is not None:
        return direct
    for attribute_name, value in element.attrib.items():
        try:
            name = etree.QName(attribute_name)
        except ValueError:
            continue
        if name.localname == attribute:
            return value
    return None


def _typed_boolean_value(raw_value: str | None, *, path: str, attribute: str) -> bool | None:
    if raw_value is None:
        return None
    normalized = raw_value.lower()
    if normalized in {"1", "on", "true"}:
        return True
    if normalized in {"0", "false", "off"}:
        return False
    raise OfficePackageError(f"PPTX metadata at {path} has invalid {attribute}")


def _typed_integer_value(
    raw_value: str | None,
    *,
    path: str,
    attribute: str,
    minimum: int = 0,
    maximum: int = 2_147_483_647,
) -> int | None:
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise OfficePackageError(f"PPTX metadata at {path} has invalid {attribute}") from exc
    if not minimum <= value <= maximum:
        raise OfficePackageError(f"PPTX metadata at {path} has out-of-range {attribute}")
    return value


def _transition_namespace_label(namespace: str | None) -> str:
    return {
        None: "unknown",
        _POWERPOINT_2010_NS: "extension_2010",
        _POWERPOINT_2012_NS: "extension_2012",
        _POWERPOINT_2015_NS: "extension_2015",
    }.get(namespace, "standard" if namespace in _PRESENTATION_NAMESPACES else "extension")


def _transition_direction(
    raw_value: str | None,
) -> tuple[str | None, bool]:
    if raw_value is None:
        return None, False
    normalized = raw_value.lower()
    known = {
        "d": "down",
        "horz": "horizontal",
        "in": "in",
        "l": "left",
        "ld": "left_down",
        "lu": "left_up",
        "out": "out",
        "r": "right",
        "rd": "right_down",
        "ru": "right_up",
        "u": "up",
        "vert": "vertical",
    }.get(normalized)
    if known is not None:
        return known, False
    return _bounded_string(normalized, 64)


def _transition_effect_name(local_name: str) -> str:
    return {
        "newsflash": "news_flash",
        "randomBar": "random_bars",
    }.get(local_name, local_name)


def _transition_effect_record(
    transition: Any,
    *,
    path: str,
    source: str,
) -> dict[str, Any]:
    effect = next(
        (child for child in transition if isinstance(child.tag, str) and _local_name(child) != "extLst"),
        None,
    )
    record: dict[str, Any] = {
        "path": path,
        "source": source,
        "effect": None,
    }
    if effect is not None:
        effect_name = _local_name(effect)
        record["schema"] = _transition_namespace_label(_qname(effect).namespace)
        if effect_name == "morph":
            record["effect"] = "morph"
            option = effect.get("option")
            if option:
                known_option = {
                    "byChar": "by_character",
                    "byObject": "by_object",
                    "byWord": "by_word",
                }.get(option)
                if known_option is not None:
                    record["option"] = known_option
                else:
                    bounded_option, option_truncated = _bounded_string(
                        option,
                        64,
                    )
                    record["option"] = bounded_option
                    if option_truncated:
                        record["option_truncated"] = True
        elif effect_name == "prstTrans":
            record["effect"] = "preset"
            preset, preset_truncated = _bounded_attribute(
                effect,
                "prst",
                limit=_MAX_OBJECT_NAME_CHARS,
            )
            if preset is not None:
                record["preset"] = preset
            if preset_truncated:
                record["preset_truncated"] = True
            for attribute, key in (("invX", "inverse_x"), ("invY", "inverse_y")):
                value = _typed_boolean_value(
                    effect.get(attribute),
                    path=path,
                    attribute=attribute,
                )
                if value is not None:
                    record[key] = value
        else:
            record["effect"] = _transition_effect_name(effect_name)

        direction, direction_truncated = _transition_direction(effect.get("dir"))
        if direction is not None:
            record["direction"] = direction
        if direction_truncated:
            record["direction_truncated"] = True
        orientation, orientation_truncated = _transition_direction(effect.get("orient"))
        if orientation is not None:
            record["orientation"] = orientation
        if orientation_truncated:
            record["orientation_truncated"] = True
        spokes = _typed_integer_value(
            effect.get("spokes"),
            path=path,
            attribute="spokes",
            maximum=1_000,
        )
        if spokes is not None:
            record["spokes"] = spokes
        through_black = _typed_boolean_value(
            effect.get("thruBlk"),
            path=path,
            attribute="thruBlk",
        )
        if through_black is not None:
            record["through_black"] = through_black
        if effect_name == "prism":
            is_content = _typed_boolean_value(
                effect.get("isContent"),
                path=path,
                attribute="isContent",
            )
            is_inverted = _typed_boolean_value(
                effect.get("isInverted"),
                path=path,
                attribute="isInverted",
            )
            if is_content is not None:
                record["content_only"] = is_content
            if is_inverted is not None:
                record["inverted"] = is_inverted

    speed, speed_truncated = _bounded_string(
        _attribute_by_local_name(transition, "spd"),
        32,
    )
    if speed is not None:
        record["speed"] = speed
    if speed_truncated:
        record["speed_truncated"] = True
    duration = _typed_integer_value(
        _attribute_by_local_name(transition, "dur"),
        path=path,
        attribute="duration",
        maximum=86_400_000,
    )
    if duration is not None:
        record["duration_ms"] = duration
    advance_after = _typed_integer_value(
        _attribute_by_local_name(transition, "advTm"),
        path=path,
        attribute="advance time",
        maximum=86_400_000,
    )
    if advance_after is not None:
        record["advance_after_ms"] = advance_after
    advance_on_click = _typed_boolean_value(
        _attribute_by_local_name(transition, "advClick"),
        path=path,
        attribute="advance on click",
    )
    if advance_on_click is not None:
        record["advance_on_click"] = advance_on_click
    return record


def _transition_in_branch(branch: Any) -> Any | None:
    return next(
        (candidate for candidate in branch if isinstance(candidate.tag, str) and _local_name(candidate) == "transition" and _qname(candidate).namespace in _PRESENTATION_NAMESPACES),
        None,
    )


def _transition_choice_supported(choice: Any) -> bool:
    required_prefixes = (choice.get("Requires") or "").split()
    if not required_prefixes:
        return False
    return all(choice.nsmap.get(prefix) in _SUPPORTED_TRANSITION_MC_NAMESPACES for prefix in required_prefixes)


def _slide_transition(slide_root: Any, *, path: str) -> dict[str, Any] | None:
    for child in slide_root:
        if not isinstance(child.tag, str):
            continue
        name = _qname(child)
        if name.localname == "transition" and name.namespace in _PRESENTATION_NAMESPACES:
            return _transition_effect_record(
                child,
                path=f"{path}/transition",
                source="direct",
            )
        if name.localname != "AlternateContent" or name.namespace != _MARKUP_COMPATIBILITY_NS:
            continue
        choice = next(
            (
                branch
                for branch in child
                if isinstance(branch.tag, str) and _qname(branch).namespace == _MARKUP_COMPATIBILITY_NS and _local_name(branch) == "Choice" and _transition_choice_supported(branch) and _transition_in_branch(branch) is not None
            ),
            None,
        )
        fallback = next(
            (branch for branch in child if isinstance(branch.tag, str) and _qname(branch).namespace == _MARKUP_COMPATIBILITY_NS and _local_name(branch) == "Fallback" and _transition_in_branch(branch) is not None),
            None,
        )
        selected_branch = choice if choice is not None else fallback
        if selected_branch is None:
            continue
        selected = _transition_in_branch(selected_branch)
        if selected is None:
            continue
        record = _transition_effect_record(
            selected,
            path=f"{path}/transition",
            source=("markup_compatibility_choice" if choice is not None else "markup_compatibility_fallback"),
        )
        fallback_transition = None if fallback is None else _transition_in_branch(fallback)
        if choice is not None and fallback_transition is not None:
            record["fallback"] = _transition_effect_record(
                fallback_transition,
                path=f"{path}/transition/fallback",
                source="markup_compatibility_fallback",
            )
        return record
    return None


_ENTRANCE_EXIT_ANIMATION_EFFECTS = {
    1: "appear",
    2: "fly",
    3: "blinds",
    4: "box",
    5: "checkerboard",
    6: "circle",
    7: "crawl",
    8: "diamond",
    9: "dissolve",
    10: "fade",
    11: "flash",
    12: "float",
    13: "plus",
    14: "random",
    15: "split",
    16: "strips",
    17: "swivel",
    18: "wedge",
    19: "wheel",
    20: "wipe",
    21: "zoom",
    24: "bounce",
}
_EMPHASIS_ANIMATION_EFFECTS = {
    1: "fill_color",
    6: "grow",
    7: "line_color",
    8: "spin",
    9: "transparency",
    10: "fade",
    14: "wave",
    19: "object_color",
    21: "complementary_color",
    22: "complementary_color_2",
    23: "contrasting_color",
    24: "darken",
    25: "desaturate",
    26: "pulse",
    27: "color_pulse",
    30: "lighten",
    32: "teeter",
}


def _animation_effect_name(
    filter_value: str,
    preset_id: int | None,
    preset_class: str,
) -> str | None:
    if preset_id is not None and preset_class == "emphasis":
        known = _EMPHASIS_ANIMATION_EFFECTS.get(preset_id)
        if known is not None:
            return known
    normalized_filter = filter_value.lower()
    for prefix, effect in (
        ("blinds", "blinds"),
        ("checkerboard", "checkerboard"),
        ("crawl", "crawl"),
        ("barn", "split"),
        ("strips", "strips"),
        ("wheel", "wheel"),
        ("wipe", "wipe"),
    ):
        if normalized_filter.startswith(prefix):
            return effect
    if normalized_filter in {
        "box",
        "circle",
        "diamond",
        "dissolve",
        "flash",
        "plus",
        "random",
        "wedge",
    }:
        return normalized_filter
    if normalized_filter == "fade" and preset_id != 17:
        return "fade"
    if preset_id is None:
        return None
    if preset_class == "emphasis":
        return _EMPHASIS_ANIMATION_EFFECTS.get(preset_id)
    return _ENTRANCE_EXIT_ANIMATION_EFFECTS.get(preset_id)


def _animation_timing_value(
    effect_time_node: Any,
    *,
    path: str,
) -> tuple[int | None, bool]:
    candidates: list[Any] = []
    for element_name in (
        "animEffect",
        "animMotion",
        "animScale",
        "animRot",
        "anim",
    ):
        animator = next(
            (element for element in effect_time_node.iter() if isinstance(element.tag, str) and _local_name(element) == element_name),
            None,
        )
        if animator is not None:
            candidates.extend(element for element in animator.iter() if isinstance(element.tag, str) and _local_name(element) == "cTn")
    candidates.append(effect_time_node)
    for candidate in candidates:
        raw_value = candidate.get("dur")
        if raw_value is None:
            continue
        if raw_value == "indefinite":
            return None, True
        return (
            _typed_integer_value(
                raw_value,
                path=path,
                attribute="duration",
                maximum=86_400_000,
            ),
            False,
        )
    return None, False


def _animation_trigger(effect_time_node: Any) -> str | None:
    current = effect_time_node
    while current is not None:
        if isinstance(current.tag, str) and _local_name(current) == "cTn":
            node_type = current.get("nodeType")
            trigger = {
                "afterEffect": "after_previous",
                "clickEffect": "on_click",
                "withEffect": "with_previous",
            }.get(node_type or "")
            if trigger is not None:
                return trigger
        current = current.getparent()
    return None


def _animation_delay(effect_time_node: Any, *, path: str) -> int | None:
    current = effect_time_node.getparent()
    for _ in range(5):
        if current is None:
            break
        if isinstance(current.tag, str) and _local_name(current) == "cTn":
            if _attribute_by_local_name(current, "presetID") is not None:
                current = current.getparent()
                continue
            conditions = _first_child(current, "stCondLst")
            condition = None if conditions is None else _first_child(conditions, "cond")
            raw_delay = None if condition is None else condition.get("delay")
            if raw_delay in {None, "0", "indefinite"}:
                return None
            delay = _typed_integer_value(
                raw_delay,
                path=path,
                attribute="delay",
                maximum=86_400_000,
            )
            return delay if delay not in {None, 0} else None
        current = current.getparent()
    return None


def _animation_effect_time_node(shape_target: Any) -> tuple[Any | None, str | None]:
    current = shape_target.getparent()
    while current is not None:
        if isinstance(current.tag, str) and _local_name(current) == "cTn":
            preset_class = _attribute_by_local_name(current, "presetClass")
            has_motion = any(isinstance(element.tag, str) and _local_name(element) == "animMotion" for element in current.iter())
            if preset_class in {"motion", "path"} and has_motion:
                return current, "path"
            if preset_class is not None and _attribute_by_local_name(current, "presetID") is not None:
                return current, preset_class
        current = current.getparent()
    return None, None


def _animation_has_grid_legend_target(effect_time_node: Any) -> bool:
    return any(isinstance(element.tag, str) and _local_name(element) == "chart" and element.get("bldStep") == "gridLegend" for element in effect_time_node.iter())


def _animation_candidates(
    timing: Any,
    *,
    slide_path: str,
) -> tuple[list[_AnimationCandidate], bool]:
    candidates: list[_AnimationCandidate] = []
    grouped_indices: dict[tuple[str, int], int] = {}
    seen_nodes: set[tuple[int, str]] = set()
    scan_truncated = False
    shape_targets = (element for element in timing.iter() if isinstance(element.tag, str) and _local_name(element) == "spTgt")
    for target_index, shape_target in enumerate(shape_targets, start=1):
        if target_index > _MAX_ANIMATION_TARGETS_PER_SLIDE:
            scan_truncated = True
            break
        raw_shape_id = shape_target.get("spid") or ""
        effect_time_node, preset_class = _animation_effect_time_node(shape_target)
        if effect_time_node is None or preset_class is None:
            continue
        node_identity = (id(effect_time_node), raw_shape_id)
        if node_identity in seen_nodes:
            continue
        seen_nodes.add(node_identity)
        group_id = _typed_integer_value(
            _attribute_by_local_name(effect_time_node, "grpId"),
            path=f"{slide_path}/animation",
            attribute="group ID",
            maximum=2_147_483_647,
        )
        candidate = _AnimationCandidate(
            effect_time_node=effect_time_node,
            preset_class=preset_class,
            raw_shape_id=raw_shape_id,
            timing_node_id=_typed_integer_value(
                _attribute_by_local_name(effect_time_node, "id"),
                path=f"{slide_path}/animation",
                attribute="timing node ID",
                maximum=4_294_967_295,
            ),
            group_id=group_id,
            grid_legend_target=_animation_has_grid_legend_target(effect_time_node),
        )
        if group_id is None:
            candidates.append(candidate)
            continue
        group_key = (raw_shape_id, group_id)
        existing_index = grouped_indices.get(group_key)
        if existing_index is None:
            grouped_indices[group_key] = len(candidates)
            candidates.append(candidate)
            continue
        existing = candidates[existing_index]
        if existing.grid_legend_target and not candidate.grid_legend_target:
            candidates[existing_index] = candidate
    return candidates, scan_truncated


def _animation_build_metadata(
    timing: Any,
    *,
    raw_shape_id: str,
) -> dict[str, Any]:
    build_list = _first_child(timing, "bldLst")
    if build_list is None:
        return {}
    for build in _children(build_list, "bldP"):
        if build.get("spid") != raw_shape_id:
            continue
        value, truncated = _bounded_attribute(
            build,
            "build",
            limit=64,
        )
        result: dict[str, Any] = {}
        if value is not None:
            result["paragraph_build"] = value
        if truncated:
            result["paragraph_build_truncated"] = True
        return result
    for build in _children(build_list, "bldGraphic"):
        if build.get("spid") != raw_shape_id:
            continue
        chart_build = next(
            (element for element in build.iter() if isinstance(element.tag, str) and _local_name(element) == "bldChart"),
            None,
        )
        if chart_build is not None:
            raw_value = chart_build.get("bld")
            if raw_value is not None:
                known_value = {
                    "asWhole": "as_whole",
                    "categoryEl": "category_elements",
                    "seriesEl": "series_elements",
                }.get(raw_value)
                if known_value is not None:
                    return {"chart_build": known_value}
                value, truncated = _bounded_string(raw_value, 64)
                result = {"chart_build": value}
                if truncated:
                    result["chart_build_truncated"] = True
                return result
        if _first_child(build, "bldAsOne") is not None:
            return {"chart_build": "as_whole"}
        return {}
    return {}


def _slide_animations(
    slide_root: Any,
    *,
    slide_path: str,
    object_refs: list[_ObjectRef],
    record_limit: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    timing = next(
        (child for child in slide_root if isinstance(child.tag, str) and _local_name(child) == "timing" and _qname(child).namespace in _PRESENTATION_NAMESPACES),
        None,
    )
    if timing is None:
        return [], 0, False

    object_paths: dict[int, list[str]] = {}
    for ref in object_refs:
        if ref.object_id is not None:
            object_paths.setdefault(ref.object_id, []).append(ref.path)

    records: list[dict[str, Any]] = []
    target_animation_counts: dict[str, int] = {}
    candidates, scan_truncated = _animation_candidates(
        timing,
        slide_path=slide_path,
    )
    timing_id_counts: dict[int, int] = {}
    for candidate in candidates:
        if candidate.timing_node_id is not None:
            timing_id_counts[candidate.timing_node_id] = timing_id_counts.get(candidate.timing_node_id, 0) + 1
    for candidate in candidates:
        raw_shape_id = candidate.raw_shape_id
        effect_time_node = candidate.effect_time_node
        preset_class = candidate.preset_class
        try:
            shape_id = int(raw_shape_id)
        except ValueError:
            shape_id = None
        matching_paths = [] if shape_id is None else object_paths.get(shape_id, [])
        target_path = matching_paths[0] if len(matching_paths) == 1 else None
        path_base = target_path or slide_path
        target_animation_counts[path_base] = target_animation_counts.get(path_base, 0) + 1
        stable_timing_id = candidate.timing_node_id if candidate.timing_node_id is not None and timing_id_counts[candidate.timing_node_id] == 1 else None
        animation_path = f"{path_base}/animation[@timing_id={stable_timing_id}]" if stable_timing_id is not None else f"{path_base}/animation[{target_animation_counts[path_base]}]"
        if len(records) >= record_limit:
            continue

        normalized_class = {
            "emph": "emphasis",
            "entr": "entrance",
            "motion": "path",
        }.get(preset_class, preset_class)
        record: dict[str, Any] = {
            "path": animation_path,
            "target_path": target_path,
            "target_resolved": target_path is not None,
            "preset_class": normalized_class,
        }
        if candidate.timing_node_id is not None:
            record["timing_node_id"] = candidate.timing_node_id
        if stable_timing_id is None:
            record["path_stable"] = False
        if candidate.group_id is not None:
            record["group_id"] = candidate.group_id
        if shape_id is not None:
            record["target_shape_id"] = shape_id
        else:
            bounded_id, id_truncated = _bounded_string(raw_shape_id, _MAX_OBJECT_NAME_CHARS)
            record["target_shape_id"] = bounded_id
            if id_truncated:
                record["target_shape_id_truncated"] = True
        if len(matching_paths) > 1:
            record["target_ambiguous"] = True

        preset_id = _typed_integer_value(
            _attribute_by_local_name(effect_time_node, "presetID"),
            path=animation_path,
            attribute="preset ID",
            maximum=65_535,
        )
        if preset_id is not None:
            record["preset_id"] = preset_id
        preset_subtype = _typed_integer_value(
            _attribute_by_local_name(effect_time_node, "presetSubtype"),
            path=animation_path,
            attribute="preset subtype",
            maximum=65_535,
        )
        if preset_subtype is not None:
            record["preset_subtype"] = preset_subtype

        animator = next(
            (element for element in effect_time_node.iter() if isinstance(element.tag, str) and _local_name(element) == "animEffect"),
            None,
        )
        filter_value = "" if animator is None else animator.get("filter") or ""
        effect_name = _animation_effect_name(
            filter_value,
            preset_id,
            normalized_class,
        )
        if normalized_class == "path":
            effect_name = "motion_path"
        record["effect"] = effect_name
        bounded_filter, filter_truncated = _bounded_string(
            filter_value or None,
            _MAX_OBJECT_NAME_CHARS,
        )
        if bounded_filter is not None:
            record["filter"] = bounded_filter
        if filter_truncated:
            record["filter_truncated"] = True

        if preset_subtype in {2, 8} or (preset_subtype in {1, 4} and effect_name in {"crawl", "fly", "wipe"}):
            record["direction"] = {
                1: "up",
                2: "right",
                4: "down",
                8: "left",
            }[preset_subtype]
        duration_ms, duration_indefinite = _animation_timing_value(
            effect_time_node,
            path=animation_path,
        )
        if duration_ms is not None:
            record["duration_ms"] = duration_ms
        if duration_indefinite:
            record["duration_indefinite"] = True
        trigger = _animation_trigger(effect_time_node)
        if trigger is not None:
            record["trigger"] = trigger
        delay_ms = _animation_delay(
            effect_time_node,
            path=animation_path,
        )
        if delay_ms is not None:
            record["delay_ms"] = delay_ms

        for attribute, key in (
            ("accel", "ease_in_percent"),
            ("decel", "ease_out_percent"),
        ):
            easing = _typed_integer_value(
                _attribute_by_local_name(effect_time_node, attribute),
                path=animation_path,
                attribute=attribute,
                maximum=100_000,
            )
            if easing is not None:
                record[key] = easing / 1_000

        repeat_count = _attribute_by_local_name(effect_time_node, "repeatCount")
        if repeat_count == "indefinite":
            record["repeat_indefinite"] = True
        elif repeat_count is not None:
            repeat_thousandths = _typed_integer_value(
                repeat_count,
                path=animation_path,
                attribute="repeat count",
                maximum=1_000_000_000,
            )
            if repeat_thousandths is not None:
                record["repeat_count"] = repeat_thousandths / 1_000
        auto_reverse = _typed_boolean_value(
            _attribute_by_local_name(effect_time_node, "autoRev"),
            path=animation_path,
            attribute="auto reverse",
        )
        if auto_reverse is not None:
            record["auto_reverse"] = auto_reverse
        restart = _attribute_by_local_name(effect_time_node, "restart")
        if restart is not None:
            known_restart = {
                "whenNotActive": "when_not_active",
            }.get(restart)
            if known_restart is not None:
                record["restart"] = known_restart
            else:
                bounded_restart, restart_truncated = _bounded_string(
                    restart,
                    64,
                )
                record["restart"] = bounded_restart
                if restart_truncated:
                    record["restart_truncated"] = True
        record.update(
            _animation_build_metadata(
                timing,
                raw_shape_id=raw_shape_id,
            )
        )

        motion = next(
            (element for element in effect_time_node.iter() if isinstance(element.tag, str) and _local_name(element) == "animMotion"),
            None,
        )
        motion_path, motion_path_truncated = _bounded_string(
            None if motion is None else motion.get("path"),
            _MAX_MOTION_PATH_CHARS,
        )
        if motion_path is not None:
            record["motion_path"] = motion_path
        if motion_path_truncated:
            record["motion_path_truncated"] = True
        records.append(record)

    return records, len(candidates), scan_truncated


def _slide_layout_metadata(slide: _Slide) -> dict[str, Any] | None:
    if slide.layout_part_name is None:
        return None
    result: dict[str, Any] = {"part_name": slide.layout_part_name}
    layout = slide.layout_root
    if layout is None or _local_name(layout) != "sldLayout" or _qname(layout).namespace not in _PRESENTATION_NAMESPACES:
        return result

    layout_type, layout_type_truncated = _bounded_attribute(
        layout,
        "type",
        limit=_MAX_OBJECT_NAME_CHARS,
    )
    if layout_type is not None:
        result["type"] = layout_type
    if layout_type_truncated:
        result["type_truncated"] = True

    common_slide_data = _first_child(layout, "cSld")
    candidates = (
        (
            None if common_slide_data is None else common_slide_data.get("name"),
            "common_slide_data",
        ),
        (layout.get("matchingName"), "matching_name"),
        (layout.get("type"), "type"),
    )
    for candidate, source in candidates:
        if not candidate:
            continue
        name, name_truncated = _bounded_string(
            candidate,
            _MAX_OBJECT_NAME_CHARS,
        )
        result["name"] = name
        result["name_source"] = source
        if name_truncated:
            result["name_truncated"] = True
        break
    return result


def _slide_background(slide: _Slide, *, path: str) -> dict[str, Any] | None:
    common_slide_data = _first_child(slide.root, "cSld")
    background = None if common_slide_data is None else _first_child(common_slide_data, "bg")
    if background is None:
        return None

    properties = _first_child(background, "bgPr")
    if properties is not None:
        result: dict[str, Any] = {"scope": "direct"}
        fill = _fill_style(properties, path=path)
        if fill is not None:
            result.update(fill)
        shade_to_title = _boolean_attribute(
            properties,
            "shadeToTitle",
            path=path,
        )
        if shade_to_title is not None:
            result["shade_to_title"] = shade_to_title
        return result

    reference = _first_child(background, "bgRef")
    if reference is None:
        return {"scope": "direct"}
    result = {"scope": "direct", "type": "theme_reference"}
    style_index = _format_integer_attribute(
        reference,
        "idx",
        path=path,
        minimum=0,
    )
    if style_index is not None:
        result["style_index"] = style_index
    color = _direct_color(reference, path=path)
    if color is not None:
        result["color"] = color
    return result


def _slide_metadata(slide: _Slide, *, path: str) -> dict[str, Any]:
    common_slide_data = _first_child(slide.root, "cSld")
    name, name_truncated = _bounded_string(
        None if common_slide_data is None else common_slide_data.get("name"),
        _MAX_OBJECT_NAME_CHARS,
    )
    show_master_shapes = _boolean_attribute(
        slide.root,
        "showMasterSp",
        path=path,
    )
    result: dict[str, Any] = {
        "name": name,
        "layout": _slide_layout_metadata(slide),
        "show_master_shapes": (True if show_master_shapes is None else show_master_shapes),
        "show_master_shapes_authored": show_master_shapes is not None,
        "background": _slide_background(slide, path=path),
        "transition": _slide_transition(slide.root, path=path),
    }
    if name_truncated:
        result["name_truncated"] = True
    return result


def _ancestor_before(element: Any, stop: Any, names: set[str]) -> Any | None:
    current = element.getparent()
    while current is not None and current is not stop:
        if isinstance(current.tag, str) and _local_name(current) in names:
            return current
        current = current.getparent()
    return None


def _table_cell_path(ref: _ObjectRef, element: Any) -> str | None:
    cell = _ancestor_before(element, ref.element, {"tc"})
    table = _table_element(ref)
    if cell is None or table is None:
        return None
    for row_index, row in enumerate(_children(table, "tr"), start=1):
        for cell_index, candidate in enumerate(_children(row, "tc"), start=1):
            if candidate is cell:
                return f"{ref.path}/row[{row_index}]/cell[{cell_index}]"
    return None


def _interaction_owner_path(ref: _ObjectRef, interaction: Any) -> str:
    paragraph = _ancestor_before(interaction, ref.element, {"p"})
    text_body = _ancestor_before(interaction, ref.element, {"txBody"})
    if paragraph is None or text_body is None:
        return ref.path

    paragraph_index = next(
        (
            index
            for index, candidate in enumerate(
                _children(text_body, "p"),
                start=1,
            )
            if candidate is paragraph
        ),
        None,
    )
    if paragraph_index is None:
        return ref.path
    base_path = _table_cell_path(ref, interaction) if ref.kind == "table" else ref.path
    if base_path is None:
        return ref.path
    paragraph_path = f"{base_path}/paragraph[{paragraph_index}]"

    segment = _ancestor_before(interaction, ref.element, {"br", "fld", "r"})
    if segment is not None:
        segment_kind = _local_name(segment)
        segment_index = next(
            (
                index
                for index, candidate in enumerate(
                    (child for child in paragraph if isinstance(child.tag, str) and _local_name(child) == segment_kind),
                    start=1,
                )
                if candidate is segment
            ),
            None,
        )
        if segment_index is None:
            return paragraph_path
        path_kind = {
            "br": "line_break",
            "fld": "field",
            "r": "run",
        }[segment_kind]
        return f"{paragraph_path}/{path_kind}[{segment_index}]"
    if _ancestor_before(interaction, ref.element, {"endParaRPr"}) is not None:
        return f"{paragraph_path}/end_run"
    if _ancestor_before(interaction, ref.element, {"defRPr"}) is not None:
        return f"{paragraph_path}/default_run"
    return paragraph_path


def _interaction_record(
    interaction: Any,
    *,
    ref: _ObjectRef,
    slide: _Slide,
    slide_paths_by_part: dict[str, str],
) -> dict[str, Any]:
    trigger = "click" if _local_name(interaction) == "hlinkClick" else "hover"
    record: dict[str, Any] = {
        "owner_path": _interaction_owner_path(ref, interaction),
        "trigger": trigger,
    }
    tooltip, tooltip_truncated = _bounded_attribute(
        interaction,
        "tooltip",
        limit=_MAX_INTERACTION_TOOLTIP_CHARS,
    )
    if tooltip is not None:
        record["tooltip"] = tooltip
    if tooltip_truncated:
        record["tooltip_truncated"] = True

    relationship_id = _slide_relationship_id(interaction)
    relationship = slide.relationships.get(relationship_id or "")
    if relationship_id:
        bounded_relationship_id, relationship_id_truncated = _bounded_string(
            relationship_id,
            _MAX_RELATIONSHIP_ID_CHARS,
        )
        record["relationship_id"] = bounded_relationship_id
        if relationship_id_truncated:
            record["relationship_id_truncated"] = True

    action = interaction.get("action")
    bounded_action, action_truncated = _bounded_string(
        action,
        _MAX_INTERACTION_ACTION_CHARS,
    )
    if bounded_action is not None:
        record["action"] = bounded_action
    if action_truncated:
        record["action_truncated"] = True
    normalized_action = "" if action is None else action.strip().lower()

    if relationship is not None:
        if relationship.external:
            target, target_truncated = _bounded_string(
                relationship.target,
                _MAX_RESOURCE_TARGET_CHARS,
            )
            safe_external_hyperlink = _is_safe_external_hyperlink(relationship)
            if safe_external_hyperlink:
                record["target_kind"] = "external_url"
            elif relationship.relationship_type in _HYPERLINK_RELATIONSHIP_TYPES:
                record["target_kind"] = "unsafe_external_url"
                record["unsafe_target"] = True
            else:
                record["target_kind"] = "unsafe_external_relationship"
                record["unsafe_target"] = True
            record["target"] = target
            if target_truncated:
                record["target_truncated"] = True
        else:
            resolved_part_name = _resolve_relationship_target(slide.part_name, relationship.target)
            part_name, part_name_truncated = _bounded_string(
                resolved_part_name,
                _MAX_RESOURCE_TARGET_CHARS,
            )
            record["part_name"] = part_name
            if part_name_truncated:
                record["part_name_truncated"] = True
            if relationship.relationship_type in _SLIDE_RELATIONSHIP_TYPES:
                record["target_kind"] = "slide"
                target_path = slide_paths_by_part.get(resolved_part_name)
                record["target"] = part_name if target_path is None else target_path
                if target_path is None and part_name_truncated:
                    record["target_truncated"] = True
            else:
                record["target_kind"] = _relationship_kind(relationship)
                record["target"] = part_name
                if part_name_truncated:
                    record["target_truncated"] = True
    elif normalized_action.startswith("ppaction://hlinkshowjump?jump="):
        jump = normalized_action.rsplit("=", 1)[-1]
        record["target_kind"] = "show_navigation"
        record["target"] = {
            "endshow": "end_show",
            "firstslide": "first_slide",
            "lastslide": "last_slide",
            "nextslide": "next_slide",
            "previousslide": "previous_slide",
        }.get(jump, jump)
    elif normalized_action == "ppaction://media":
        record["target_kind"] = "media"
        record["target"] = "media"
    elif normalized_action:
        record["target_kind"] = "unsafe_action"
        record["target"] = bounded_action
    else:
        record["target_kind"] = "none"

    if normalized_action:
        safe_action = (normalized_action == _SLIDE_JUMP_ACTION and relationship is not None and not relationship.external and relationship.relationship_type in _SLIDE_RELATIONSHIP_TYPES) or (
            normalized_action in _RELATIONSHIP_FREE_ACTIONS and not relationship_id
        )
        if not safe_action:
            record["unsafe_action"] = True
    return record


def _object_interactions(
    ref: _ObjectRef,
    *,
    slide: _Slide,
    slide_paths_by_part: dict[str, str],
    record_limit: int,
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    count = 0

    def visit(element: Any, *, root: bool) -> None:
        nonlocal count
        if not root and ref.kind == "group" and _is_presentation_object(element):
            return
        if isinstance(element.tag, str) and _qname(element).namespace in _DRAWING_NAMESPACES and _local_name(element) in {"hlinkClick", "hlinkHover", "hlinkMouseOver"}:
            count += 1
            if len(records) < record_limit:
                records.append(
                    _interaction_record(
                        element,
                        ref=ref,
                        slide=slide,
                        slide_paths_by_part=slide_paths_by_part,
                    )
                )
        for child in element:
            if isinstance(child.tag, str):
                visit(child, root=False)

    visit(ref.element, root=True)
    return records, count


def _has_truncation_marker(value: Any) -> bool:
    if isinstance(value, dict):
        return any((key.endswith("_truncated") and child is True) or _has_truncation_marker(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_has_truncation_marker(child) for child in value)
    return False


def _object_metadata(
    ref: _ObjectRef,
    *,
    slide: _Slide,
    package: _PackageInfo,
    interactions: list[dict[str, Any]] | None = None,
    interaction_count: int = 0,
    include_formatting: bool = False,
    formatting_budget: dict[str, int] | None = None,
) -> dict[str, Any]:
    non_visual = _non_visual_drawing_properties(ref.element)
    name, name_truncated = _bounded_string(
        None if non_visual is None else non_visual.get("name"),
        _MAX_OBJECT_NAME_CHARS,
    )
    alt_text, alt_text_truncated = _bounded_string(
        None if non_visual is None else non_visual.get("descr"),
        _MAX_ALT_TEXT_CHARS,
    )
    source_relationship_ids = _object_relationship_ids(ref)
    returned_relationship_ids = source_relationship_ids[:_MAX_RELATIONSHIP_IDS_PER_OBJECT]
    relationship_ids: list[str] = []
    relationship_ids_truncated = len(returned_relationship_ids) < len(source_relationship_ids)
    for relationship_id in returned_relationship_ids:
        bounded_relationship_id, relationship_id_truncated = _bounded_string(
            relationship_id,
            _MAX_RELATIONSHIP_ID_CHARS,
        )
        relationship_ids.append(bounded_relationship_id or "")
        relationship_ids_truncated = relationship_ids_truncated or relationship_id_truncated
    metadata: dict[str, Any] = {
        "path": ref.path,
        "parent_path": ref.parent_path,
        "kind": ref.kind,
        "id": ref.object_id,
        "identity_source": ref.identity_source,
        "name": name,
        "z_order": ref.z_order,
        "geometry": _object_geometry(ref),
        "relationship_id_count": len(source_relationship_ids),
        "relationship_ids_returned": len(relationship_ids),
        "relationship_ids_truncated": relationship_ids_truncated,
        "relationship_ids": relationship_ids,
    }
    if interaction_count:
        returned_interactions = interactions or []
        metadata.update(
            {
                "interaction_count": interaction_count,
                "interactions_returned": len(returned_interactions),
                "interactions_truncated": (len(returned_interactions) < interaction_count),
                "interactions": returned_interactions,
            }
        )
    if name_truncated:
        metadata["name_truncated"] = True
    if alt_text is not None:
        metadata["alt_text"] = alt_text
        if alt_text_truncated:
            metadata["alt_text_truncated"] = True
    if _local_name(ref.container_element) == "graphicFrame":
        graphic_data = next(
            (element for element in ref.container_element.iter() if isinstance(element.tag, str) and _local_name(element) == "graphicData"),
            None,
        )
        graphic_uri, graphic_uri_truncated = _bounded_string(
            None if graphic_data is None else graphic_data.get("uri"),
            _MAX_OBJECT_NAME_CHARS,
        )
        if graphic_uri is not None:
            metadata["graphic_uri"] = graphic_uri
            if graphic_uri_truncated:
                metadata["graphic_uri_truncated"] = True
    if ref.kind == "group":
        metadata["child_count"] = len(_direct_logical_children(ref.container_element))
    if ref.kind == "picture":
        source = _picture_source_record(
            ref.element,
            slide=slide,
            package=package,
        )
        if source is not None:
            metadata["source"] = source
    if include_formatting:
        if formatting_budget is None:
            raise RuntimeError("PPTX formatting inspection requires a budget")
        formatting_truncated = False
        style = _shape_style(ref)
        if style is not None:
            metadata["style"] = style
            formatting_truncated = _has_truncation_marker(style)
        if ref.path_kind == "shape":
            text_body = _first_child(ref.element, "txBody")
            if text_body is not None:
                metadata["text_body"], text_truncated = _text_body_inspection(
                    text_body,
                    base_path=ref.path,
                    budget=formatting_budget,
                )
                formatting_truncated = formatting_truncated or text_truncated
        elif ref.kind == "table":
            table_content, table_truncated = _table_cells_inspection(
                ref,
                budget=formatting_budget,
            )
            metadata.update(table_content)
            formatting_truncated = formatting_truncated or table_truncated
        if formatting_truncated:
            metadata["formatting_truncated"] = True
    return metadata


def _picture_has_alt_text(picture: Any) -> bool:
    for element in picture.iter():
        if not isinstance(element.tag, str) or _local_name(element) != "cNvPr":
            continue
        return bool((element.get("descr") or "").strip())
    return False


def _slide_inventory(slide: _Slide, object_refs: list[_ObjectRef]) -> dict[str, Any]:
    shape_refs = [ref for ref in object_refs if ref.path_kind == "shape"]
    picture_refs = [ref for ref in object_refs if ref.path_kind == "picture"]
    kinds = [ref.kind for ref in object_refs]
    relationship_types = {relationship.relationship_type for relationship in slide.relationships.values()}
    return {
        "shapes": len(shape_refs),
        "text_boxes": sum(1 for ref in shape_refs if _shape_text(ref.element).strip()),
        "pictures": len(picture_refs),
        "pictures_without_alt_text": sum(1 for ref in picture_refs if not _picture_has_alt_text(ref.element)),
        "tables": kinds.count("table"),
        "charts": kinds.count("chart"),
        "groups": kinds.count("group"),
        "connectors": kinds.count("connector"),
        "ole_objects": kinds.count("ole"),
        "has_notes": bool(relationship_types & _NOTES_RELATIONSHIP_TYPES),
        "has_legacy_comments": bool(relationship_types & _LEGACY_COMMENTS_RELATIONSHIP_TYPES),
        "has_modern_comments": bool(relationship_types & _MODERN_COMMENTS_RELATIONSHIP_TYPES),
        "has_timing": any(isinstance(child.tag, str) and _local_name(child) == "timing" and _qname(child).namespace in _PRESENTATION_NAMESPACES for child in slide.root),
    }


def _relationship_kind(relationship: _Relationship) -> str:
    return relationship.relationship_type.rstrip("/").rsplit("/", 1)[-1]


def _resource_record(
    *,
    source_part: str,
    relationship: _Relationship,
    depth: int,
    package: _PackageInfo,
) -> dict[str, Any]:
    bounded_source_part, source_part_truncated = _bounded_string(
        source_part,
        _MAX_RESOURCE_TARGET_CHARS,
    )
    target, target_truncated = _bounded_string(
        relationship.target,
        _MAX_RESOURCE_TARGET_CHARS,
    )
    relationship_id, relationship_id_truncated = _bounded_string(
        relationship.relationship_id,
        _MAX_RELATIONSHIP_ID_CHARS,
    )
    part_name = None if relationship.external else _resolve_relationship_target(source_part, relationship.target)
    bounded_part_name, part_name_truncated = _bounded_string(
        part_name,
        _MAX_RESOURCE_TARGET_CHARS,
    )
    kind, kind_truncated = _bounded_string(
        _relationship_kind(relationship),
        _MAX_OBJECT_NAME_CHARS,
    )
    content_type, content_type_truncated = _bounded_string(
        None if part_name is None else package.content_types.for_part(part_name),
        _MAX_OBJECT_NAME_CHARS,
    )
    relationship_count = None if part_name is None else package.relationship_counts_by_part.get(part_name, 0)
    relationship_source_count = None if part_name is None else package.relationship_source_counts_by_part.get(part_name, 0)
    record: dict[str, Any] = {
        "source_part": bounded_source_part,
        "relationship_id": relationship_id,
        "kind": kind,
        "target_mode": "external" if relationship.external else "internal",
        "target": target,
        "part_name": bounded_part_name,
        "content_type": content_type,
        "size_bytes": None if part_name is None else package.part_sizes.get(part_name),
        "package_relationship_count": relationship_count,
        "package_relationship_source_count": relationship_source_count,
        "shared_part": None if relationship_count is None else relationship_count > 1,
        "depth": depth,
        "owner_paths": [],
        "owner_paths_truncated": False,
    }
    if target_truncated:
        record["target_truncated"] = True
    if source_part_truncated:
        record["source_part_truncated"] = True
    if part_name_truncated:
        record["part_name_truncated"] = True
    if kind_truncated:
        record["kind_truncated"] = True
    if content_type_truncated:
        record["content_type_truncated"] = True
    if relationship_id_truncated:
        record["relationship_id_truncated"] = True
    if part_name is not None and part_name in package.part_sha256:
        record["sha256"] = package.part_sha256[part_name]
    return record


def _image_asset_inventory(package: _PackageInfo) -> dict[str, Any]:
    image_parts = sorted(part_name for part_name in package.part_names if (package.content_types.for_part(part_name) or "").lower().startswith("image/"))
    returned_parts = image_parts[:_MAX_INSPECT_IMAGE_ASSETS]
    records: list[dict[str, Any]] = []
    for part_name in returned_parts:
        relationship_count = package.relationship_counts_by_part.get(part_name, 0)
        relationship_source_count = package.relationship_source_counts_by_part.get(part_name, 0)
        records.append(
            {
                "part_name": part_name,
                "content_type": package.content_types.for_part(part_name),
                "size_bytes": package.part_sizes.get(part_name),
                "sha256": package.part_sha256.get(part_name),
                "relationship_count": relationship_count,
                "relationship_source_count": relationship_source_count,
                "orphan": relationship_count == 0,
                "shared_relationships": relationship_count > 1,
            }
        )
    return {
        "part_count": len(image_parts),
        "referenced_part_count": sum(package.relationship_counts_by_part.get(part_name, 0) > 0 for part_name in image_parts),
        "orphan_part_count": sum(package.relationship_counts_by_part.get(part_name, 0) == 0 for part_name in image_parts),
        "shared_part_count": sum(package.relationship_counts_by_part.get(part_name, 0) > 1 for part_name in image_parts),
        "parts_returned": len(records),
        "parts_truncated": len(records) < len(image_parts),
        "parts": records,
    }


def _media_gc_bounded_field(
    record: dict[str, Any],
    key: str,
    value: str | None,
    limit: int,
) -> None:
    bounded, truncated = _bounded_string(value, limit)
    record[key] = bounded
    if truncated:
        record[f"{key}_truncated"] = True


def _media_gc_relationship_record(
    *,
    source_part: str,
    relationship: _Relationship,
    part_name: str,
    package: _PackageInfo,
    source_part_sha256: str | None,
    relationship_part_sha256: str | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "actionable": False,
        "content_type": package.content_types.for_part(part_name),
        "size_bytes": package.part_sizes.get(part_name),
        "target_part_sha256": package.part_sha256.get(part_name),
        "source_content_type": package.content_types.for_part(source_part),
        "source_part_sha256": source_part_sha256,
        "relationship_part_sha256": relationship_part_sha256,
    }
    _media_gc_bounded_field(
        record,
        "source_part",
        source_part,
        _MAX_RESOURCE_TARGET_CHARS,
    )
    _media_gc_bounded_field(
        record,
        "relationship_part",
        _relationship_part_name(source_part),
        _MAX_RESOURCE_TARGET_CHARS,
    )
    _media_gc_bounded_field(
        record,
        "relationship_id",
        relationship.relationship_id,
        _MAX_RELATIONSHIP_ID_CHARS,
    )
    _media_gc_bounded_field(
        record,
        "relationship_type",
        relationship.relationship_type,
        _MAX_RESOURCE_TARGET_CHARS,
    )
    _media_gc_bounded_field(
        record,
        "part_name",
        part_name,
        _MAX_RESOURCE_TARGET_CHARS,
    )
    return record


def _media_gc_part_record(
    part_name: str,
    *,
    package: _PackageInfo,
    relationship_count: int,
    relationship_source_count: int,
    live_relationship_count: int,
    unreferenced_relationship_count: int,
    blocked_relationship_count: int,
    root_reachable_before_zero_ref_filter: bool,
    root_reachable_after_zero_ref_filter: bool,
    status: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "actionable": False,
        "content_type": package.content_types.for_part(part_name),
        "size_bytes": package.part_sizes.get(part_name),
        "sha256": package.part_sha256.get(part_name),
        "relationship_count": relationship_count,
        "relationship_source_count": relationship_source_count,
        "live_relationship_count": live_relationship_count,
        "unreferenced_relationship_count": unreferenced_relationship_count,
        "blocked_relationship_count": blocked_relationship_count,
        "root_reachable_before_zero_ref_filter": (root_reachable_before_zero_ref_filter),
        "root_reachable_after_zero_ref_filter": (root_reachable_after_zero_ref_filter),
        "status": status,
        "evidence": status,
    }
    _media_gc_bounded_field(
        record,
        "part_name",
        part_name,
        _MAX_RESOURCE_TARGET_CHARS,
    )
    return record


def _media_gc_unreachable_part_record(
    part_name: str,
    *,
    package: _PackageInfo,
    stats: dict[str, Any],
    incoming: list[tuple[str, _Relationship, str]],
    relationship_states: dict[
        tuple[str, str],
        tuple[str, int | None, str | None],
    ],
    source_part_sha256: dict[str, str],
    relationship_part_sha256: dict[str, str],
    root_reachable_before_zero_ref_filter: frozenset[str],
) -> dict[str, Any]:
    record = _media_gc_part_record(
        part_name,
        package=package,
        **stats,
    )
    ordered_incoming = sorted(
        incoming,
        key=lambda item: (item[0], item[1].relationship_id),
    )
    incoming_records: list[dict[str, Any]] = []
    for source_part, relationship, _ in ordered_incoming[:_MAX_MEDIA_GC_UNREACHABLE_RELATIONSHIPS_PER_PART]:
        state, reference_count, blocker_reason = relationship_states[(source_part, relationship.relationship_id)]
        incoming_record = _media_gc_relationship_record(
            source_part=source_part,
            relationship=relationship,
            part_name=part_name,
            package=package,
            source_part_sha256=source_part_sha256.get(source_part),
            relationship_part_sha256=relationship_part_sha256.get(source_part),
        )
        incoming_record.update(
            {
                "state": state,
                "xml_reference_count": reference_count,
                "source_root_reachable": (source_part in root_reachable_before_zero_ref_filter),
            }
        )
        if blocker_reason is not None:
            incoming_record["blocker_reason"] = blocker_reason
        incoming_records.append(incoming_record)

    record.update(
        {
            "reason": "unreachable_from_package_root",
            "incoming_relationships_count": len(ordered_incoming),
            "incoming_relationships_returned": len(incoming_records),
            "incoming_relationships_truncated": (len(incoming_records) < len(ordered_incoming)),
            "incoming_relationships": incoming_records,
        }
    )
    return record


def _media_gc_protected_part_record(
    part_name: str,
    *,
    package: _PackageInfo,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "actionable": False,
        "content_type": package.content_types.for_part(part_name),
        "size_bytes": package.part_sizes.get(part_name),
        "sha256": package.part_sha256.get(part_name),
        "reason": "outside_ppt_media_scope",
    }
    _media_gc_bounded_field(
        record,
        "part_name",
        part_name,
        _MAX_RESOURCE_TARGET_CHARS,
    )
    return record


def _media_gc_source_is_supported_xml(
    source_part: str,
    *,
    package: _PackageInfo,
) -> bool:
    if source_part == _CONTENT_TYPES_XML or source_part.endswith(".rels"):
        return False
    content_type = package.content_types.for_part(source_part)
    if content_type is None:
        return False
    normalized = content_type.partition(";")[0].strip().lower()
    return normalized in {"application/xml", "text/xml"} or normalized.endswith("+xml")


def _xml_relationship_reference_counts(root: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        for attribute_name, relationship_id in element.attrib.items():
            try:
                attribute = etree.QName(attribute_name)
            except ValueError:
                continue
            if attribute.namespace not in _DOCUMENT_RELATIONSHIPS_NAMESPACES or attribute.localname not in {"embed", "id", "link"} or not relationship_id:
                continue
            counts[relationship_id] = counts.get(relationship_id, 0) + 1
    return counts


@dataclass(frozen=True, slots=True)
class _MediaGcXmlScan:
    reference_counts: dict[str, dict[str, int]]
    source_part_sha256: dict[str, str]
    relationship_part_sha256: dict[str, str]
    source_blockers: dict[str, str]
    integrity_blockers: tuple[dict[str, Any], ...]
    xml_source_part_count: int
    scanned_source_part_count: int
    scanned_xml_bytes: int
    undeclared_relationship_reference_count: int


def _media_gc_integrity_blocker(
    *,
    reason: str,
    source_part: str,
    package: _PackageInfo,
    source_part_sha256: str | None = None,
    relationship_id: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "actionable": False,
        "reason": reason,
        "source_content_type": package.content_types.for_part(source_part),
        "source_size_bytes": package.part_sizes.get(source_part),
        "source_part_sha256": source_part_sha256,
    }
    _media_gc_bounded_field(
        record,
        "source_part",
        source_part,
        _MAX_RESOURCE_TARGET_CHARS,
    )
    if relationship_id is not None:
        _media_gc_bounded_field(
            record,
            "relationship_id",
            relationship_id,
            _MAX_RELATIONSHIP_ID_CHARS,
        )
    return record


def _scan_media_gc_xml_relationships(
    data: bytes,
    *,
    package: _PackageInfo,
    required_source_parts: frozenset[str],
) -> _MediaGcXmlScan:
    xml_source_parts = sorted(part_name for part_name in package.part_names if _media_gc_source_is_supported_xml(part_name, package=package))
    reference_counts: dict[str, dict[str, int]] = {}
    source_part_sha256: dict[str, str] = {}
    relationship_part_sha256: dict[str, str] = {}
    source_blockers: dict[str, str] = {}
    integrity_blockers: list[dict[str, Any]] = []
    undeclared_relationship_reference_count = 0
    scanned_xml_bytes = 0

    for source_part in required_source_parts:
        if source_part not in package.part_names:
            source_blockers[source_part] = "relationship_source_missing"
        elif not _media_gc_source_is_supported_xml(source_part, package=package):
            source_blockers[source_part] = "relationship_source_content_type_is_not_xml"

    with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
        for source_part in xml_source_parts:
            source_size = package.part_sizes.get(source_part, 0)
            blocker_reason: str | None = None
            if source_size > _MAX_MEDIA_GC_SOURCE_XML_BYTES:
                blocker_reason = "xml_source_exceeds_scan_limit"
            elif scanned_xml_bytes + source_size > _MAX_MEDIA_GC_TOTAL_XML_BYTES:
                blocker_reason = "xml_source_scan_budget_exhausted"
            if blocker_reason is not None:
                if source_part in required_source_parts:
                    source_blockers[source_part] = blocker_reason
                else:
                    integrity_blockers.append(
                        _media_gc_integrity_blocker(
                            reason=blocker_reason,
                            source_part=source_part,
                            package=package,
                        )
                    )
                continue

            payload = archive.read(source_part)
            scanned_xml_bytes += len(payload)
            digest = hashlib.sha256(payload).hexdigest()
            source_part_sha256[source_part] = digest
            relationship_part = _relationship_part_name(source_part)
            if relationship_part in package.part_names:
                relationship_part_sha256[source_part] = hashlib.sha256(archive.read(relationship_part)).hexdigest()
            try:
                root = _safe_xml_root(
                    payload,
                    label=source_part,
                    limit=_MAX_MEDIA_GC_SOURCE_XML_BYTES,
                )
            except OfficePackageError:
                blocker_reason = "xml_source_is_not_supported_xml"
                if source_part in required_source_parts:
                    source_blockers[source_part] = blocker_reason
                else:
                    integrity_blockers.append(
                        _media_gc_integrity_blocker(
                            reason=blocker_reason,
                            source_part=source_part,
                            package=package,
                            source_part_sha256=digest,
                        )
                    )
                continue

            counts = _xml_relationship_reference_counts(root)
            reference_counts[source_part] = counts
            declared_relationships = package.relationships_by_source.get(
                source_part,
                {},
            )
            for relationship_id in sorted(counts.keys() - declared_relationships.keys()):
                undeclared_relationship_reference_count += counts[relationship_id]
                integrity_blockers.append(
                    _media_gc_integrity_blocker(
                        reason="undeclared_xml_relationship_reference",
                        source_part=source_part,
                        package=package,
                        source_part_sha256=digest,
                        relationship_id=relationship_id,
                    )
                )

    return _MediaGcXmlScan(
        reference_counts=reference_counts,
        source_part_sha256=source_part_sha256,
        relationship_part_sha256=relationship_part_sha256,
        source_blockers=source_blockers,
        integrity_blockers=tuple(integrity_blockers),
        xml_source_part_count=len(xml_source_parts),
        scanned_source_part_count=len(reference_counts),
        scanned_xml_bytes=scanned_xml_bytes,
        undeclared_relationship_reference_count=(undeclared_relationship_reference_count),
    )


def _media_gc_root_reachable_parts(
    package: _PackageInfo,
    *,
    excluded_relationships: frozenset[tuple[str, str]] = frozenset(),
) -> frozenset[str]:
    reachable: set[str] = set()
    visited_sources: set[str] = set()
    pending = [""]
    while pending:
        source_part = pending.pop()
        if source_part in visited_sources:
            continue
        visited_sources.add(source_part)
        for relationship in package.relationships_by_source.get(
            source_part,
            {},
        ).values():
            if (
                relationship.external
                or (
                    source_part,
                    relationship.relationship_id,
                )
                in excluded_relationships
            ):
                continue
            target_part = _resolve_relationship_target(
                source_part,
                relationship.target,
            )
            if target_part in reachable:
                continue
            reachable.add(target_part)
            pending.append(target_part)
    return frozenset(reachable)


def _pptx_media_gc_plan(
    data: bytes,
    *,
    package: _PackageInfo,
) -> dict[str, Any]:
    all_image_parts = sorted(part_name for part_name in package.part_names if (package.content_types.for_part(part_name) or "").lower().startswith("image/"))
    image_parts = [part_name for part_name in all_image_parts if part_name.startswith("ppt/media/")]
    protected_image_parts = [part_name for part_name in all_image_parts if not part_name.startswith("ppt/media/")]
    returned_protected_parts = [_media_gc_protected_part_record(part_name, package=package) for part_name in protected_image_parts[:_MAX_MEDIA_GC_PROTECTED_PARTS]]
    protected_parts_truncated = len(returned_protected_parts) < len(protected_image_parts)
    image_part_names = set(image_parts)
    graph_part_names = {part_name for part_name in package.part_names if part_name != _CONTENT_TYPES_XML and not part_name.endswith(".rels") and not part_name.endswith("/")}
    root_reachable_before_zero_ref_filter = _media_gc_root_reachable_parts(package)
    base_plan = {
        "contract_version": 2,
        "package_sha256": hashlib.sha256(data).hexdigest(),
        "mode": "dry_run",
        "actionable": False,
        "candidate_evidence_only": True,
        "destructive": False,
        "deletion_supported": False,
        "scope": {
            "content_type_prefix": "image/",
            "part_prefix": "ppt/media/",
            "external_relationships_in_scope": False,
            "package_root_reachability_analyzed": True,
        },
        "liveness_basis": ("package_root_graph_and_content_type_declared_xml_relationship_id_embed_link_attributes"),
        "analysis_limitations": [
            "direct_part_uri_references_not_analyzed",
            "non_xml_or_untyped_part_contents_not_scanned",
            "non_image_relationship_semantics_assumed_live",
        ],
        "graph_part_count": len(graph_part_names),
        "root_reachable_part_count": len(graph_part_names & root_reachable_before_zero_ref_filter),
        "root_unreachable_part_count": len(graph_part_names - root_reachable_before_zero_ref_filter),
        "root_reachable_scoped_image_part_count": len(image_part_names & root_reachable_before_zero_ref_filter),
        "root_unreachable_scoped_image_part_count": len(image_part_names - root_reachable_before_zero_ref_filter),
        "protected_image_part_count": len(protected_image_parts),
        "protected_image_parts_returned": len(returned_protected_parts),
        "protected_image_parts_truncated": protected_parts_truncated,
        "protected_image_parts": returned_protected_parts,
    }
    incoming_by_part: dict[
        str,
        list[tuple[str, _Relationship, str]],
    ] = {part_name: [] for part_name in image_parts}
    standard_relationships: list[tuple[str, _Relationship, str]] = []
    scoped_relationship_count = 0
    standard_relationship_count = 0
    nonstandard_relationship_count = 0
    external_image_relationship_count = 0

    for source_part, relationships in package.relationships_by_source.items():
        for relationship in relationships.values():
            if relationship.external:
                if relationship.relationship_type in _IMAGE_RELATIONSHIP_TYPES:
                    external_image_relationship_count += 1
                continue
            target_part = _resolve_relationship_target(
                source_part,
                relationship.target,
            )
            if target_part not in image_part_names:
                continue
            scoped_relationship_count += 1
            category = "standard" if relationship.relationship_type in _IMAGE_RELATIONSHIP_TYPES else "nonstandard"
            if category == "standard":
                standard_relationship_count += 1
            else:
                nonstandard_relationship_count += 1
            if scoped_relationship_count <= _MAX_MEDIA_GC_RELATIONSHIPS:
                incoming_by_part[target_part].append((source_part, relationship, category))
                if category == "standard":
                    standard_relationships.append((source_part, relationship, target_part))

    if scoped_relationship_count > _MAX_MEDIA_GC_RELATIONSHIPS:
        unreachable_evidence_count = base_plan["root_unreachable_scoped_image_part_count"]
        return {
            **base_plan,
            "analysis_complete": False,
            "package_xml_integrity_complete": False,
            "projected_root_reachability_analyzed": False,
            "projected_root_reachable_part_count": None,
            "projected_root_unreachable_part_count": None,
            "projected_root_reachable_scoped_image_part_count": None,
            "projected_root_unreachable_scoped_image_part_count": None,
            "image_part_count": len(image_parts),
            "out_of_scope_image_part_count": len(all_image_parts) - len(image_parts),
            "image_relationship_count": scoped_relationship_count,
            "standard_image_relationship_count": standard_relationship_count,
            "nonstandard_image_relationship_count": nonstandard_relationship_count,
            "external_image_relationship_count": external_image_relationship_count,
            "xml_source_part_count": sum(
                _media_gc_source_is_supported_xml(
                    part_name,
                    package=package,
                )
                for part_name in package.part_names
            ),
            "scanned_source_part_count": 0,
            "scanned_xml_bytes": 0,
            "undeclared_relationship_reference_count": 0,
            "package_integrity_blocker_count": 0,
            "relationship_source_blocker_count": 0,
            "live_relationship_count": 0,
            "unreferenced_relationship_count": 0,
            "blocked_relationship_count": scoped_relationship_count,
            "relationship_candidate_count": 0,
            "relationship_candidates_returned": 0,
            "relationship_candidates_truncated": False,
            "relationship_candidates": [],
            "part_candidate_count": 0,
            "zero_incoming_relationship_part_count": 0,
            "all_incoming_relationships_zero_xml_refs_part_count": 0,
            "estimated_reclaimable_uncompressed_bytes": 0,
            "part_candidates_returned": 0,
            "part_candidates_truncated": False,
            "part_candidates": [],
            "root_unreachable_scoped_image_evidence_count": (unreachable_evidence_count),
            "root_unreachable_scoped_image_evidence_returned": 0,
            "root_unreachable_scoped_image_evidence_truncated": bool(unreachable_evidence_count),
            "root_unreachable_scoped_image_evidence": [],
            "blocker_count": 1,
            "blockers_returned": 1,
            "blockers_truncated": False,
            "blockers": [
                {
                    "reason": "relationship_scan_limit_exceeded",
                    "relationship_limit": _MAX_MEDIA_GC_RELATIONSHIPS,
                    "relationship_count": scoped_relationship_count,
                }
            ],
            "output_truncated": (protected_parts_truncated or bool(unreachable_evidence_count)),
        }

    required_source_parts = frozenset(source_part for source_part, _, _ in standard_relationships if source_part)
    xml_scan = _scan_media_gc_xml_relationships(
        data,
        package=package,
        required_source_parts=required_source_parts,
    )
    source_reference_counts = xml_scan.reference_counts
    source_blockers = xml_scan.source_blockers
    source_part_sha256 = xml_scan.source_part_sha256
    relationship_part_sha256 = xml_scan.relationship_part_sha256

    relationship_states: dict[
        tuple[str, str],
        tuple[str, int | None, str | None],
    ] = {}
    for incoming in incoming_by_part.values():
        for source_part, relationship, category in incoming:
            key = (source_part, relationship.relationship_id)
            if category != "standard":
                relationship_states[key] = (
                    "blocked",
                    None,
                    "nonstandard_image_relationship_type",
                )
                continue
            if not source_part:
                relationship_states[key] = ("live", None, None)
                continue
            blocker = source_blockers.get(source_part)
            if blocker is not None:
                relationship_states[key] = ("blocked", None, blocker)
                continue
            reference_count = source_reference_counts[source_part].get(
                relationship.relationship_id,
                0,
            )
            relationship_states[key] = (
                "live" if reference_count > 0 else "unreferenced",
                reference_count,
                None,
            )

    zero_ref_relationships = frozenset(relationship_key for relationship_key, (state, _, _) in relationship_states.items() if state == "unreferenced")
    root_reachable_after_zero_ref_filter = _media_gc_root_reachable_parts(
        package,
        excluded_relationships=zero_ref_relationships,
    )

    part_stats: dict[str, dict[str, Any]] = {}
    part_candidates: list[dict[str, Any]] = []
    zero_incoming_relationship_part_count = 0
    all_incoming_relationships_zero_xml_refs_part_count = 0
    estimated_reclaimable_uncompressed_bytes = 0
    for part_name in image_parts:
        incoming = incoming_by_part[part_name]
        live_count = 0
        unreferenced_count = 0
        blocked_count = 0
        for source_part, relationship, _ in incoming:
            state, _, _ = relationship_states[(source_part, relationship.relationship_id)]
            if state == "live":
                live_count += 1
            elif state == "unreferenced":
                unreferenced_count += 1
            else:
                blocked_count += 1
        status = "has_live_or_blocked_incoming_relationships"
        if not incoming:
            status = "zero_incoming_relationships"
            zero_incoming_relationship_part_count += 1
        elif unreferenced_count > 0 and live_count == 0 and blocked_count == 0:
            status = "all_incoming_relationships_have_zero_xml_references"
            all_incoming_relationships_zero_xml_refs_part_count += 1
        part_stats[part_name] = {
            "relationship_count": len(incoming),
            "relationship_source_count": len({source_part for source_part, _, _ in incoming}),
            "live_relationship_count": live_count,
            "unreferenced_relationship_count": unreferenced_count,
            "blocked_relationship_count": blocked_count,
            "root_reachable_before_zero_ref_filter": (part_name in root_reachable_before_zero_ref_filter),
            "root_reachable_after_zero_ref_filter": (part_name in root_reachable_after_zero_ref_filter),
            "status": status,
        }
        if status in {
            "zero_incoming_relationships",
            "all_incoming_relationships_have_zero_xml_references",
        }:
            estimated_reclaimable_uncompressed_bytes += package.part_sizes.get(
                part_name,
                0,
            )
            part_candidates.append(
                _media_gc_part_record(
                    part_name,
                    package=package,
                    **part_stats[part_name],
                )
            )

    unreachable_part_evidence = [
        _media_gc_unreachable_part_record(
            part_name,
            package=package,
            stats=part_stats[part_name],
            incoming=incoming_by_part[part_name],
            relationship_states=relationship_states,
            source_part_sha256=source_part_sha256,
            relationship_part_sha256=relationship_part_sha256,
            root_reachable_before_zero_ref_filter=(root_reachable_before_zero_ref_filter),
        )
        for part_name in image_parts
        if part_name not in root_reachable_before_zero_ref_filter
    ]
    returned_unreachable_evidence = unreachable_part_evidence[:_MAX_MEDIA_GC_UNREACHABLE_IMAGE_PARTS]
    unreachable_evidence_truncated = len(returned_unreachable_evidence) < len(unreachable_part_evidence) or any(item["incoming_relationships_truncated"] for item in returned_unreachable_evidence)

    relationship_candidates: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = list(xml_scan.integrity_blockers)
    live_relationship_count = 0
    unreferenced_relationship_count = 0
    blocked_relationship_count = 0
    for part_name in image_parts:
        stats = part_stats[part_name]
        for source_part, relationship, _ in incoming_by_part[part_name]:
            state, reference_count, blocker_reason = relationship_states[(source_part, relationship.relationship_id)]
            if state == "live":
                live_relationship_count += 1
                continue
            record = _media_gc_relationship_record(
                source_part=source_part,
                relationship=relationship,
                part_name=part_name,
                package=package,
                source_part_sha256=source_part_sha256.get(source_part),
                relationship_part_sha256=relationship_part_sha256.get(source_part),
            )
            if state == "unreferenced":
                unreferenced_relationship_count += 1
                record.update(
                    {
                        "xml_reference_count": reference_count,
                        "reason": "zero_source_xml_relationship_attribute_references",
                        "source_root_reachable": (source_part in root_reachable_before_zero_ref_filter),
                        "target_root_reachable_before_zero_ref_filter": (part_name in root_reachable_before_zero_ref_filter),
                        "target_root_reachable_after_zero_ref_filter": (part_name in root_reachable_after_zero_ref_filter),
                        "part_status": stats["status"],
                        "part_relationship_count": stats["relationship_count"],
                        "part_live_relationship_count": stats["live_relationship_count"],
                        "part_unreferenced_relationship_count": stats["unreferenced_relationship_count"],
                        "part_all_incoming_relationships_have_zero_xml_references": stats["status"] == "all_incoming_relationships_have_zero_xml_references",
                    }
                )
                relationship_candidates.append(record)
                continue
            blocked_relationship_count += 1
            record["reason"] = blocker_reason
            blockers.append(record)

    relationship_candidates.sort(
        key=lambda item: (
            item.get("source_part") or "",
            item.get("relationship_id") or "",
        )
    )
    part_candidates.sort(key=lambda item: item.get("part_name") or "")
    blockers.sort(
        key=lambda item: (
            item.get("source_part") or "",
            item.get("relationship_id") or "",
        )
    )
    returned_relationships = relationship_candidates[:_MAX_MEDIA_GC_RELATIONSHIP_CANDIDATES]
    returned_parts = part_candidates[:_MAX_MEDIA_GC_PART_CANDIDATES]
    returned_blockers = blockers[:_MAX_MEDIA_GC_BLOCKERS]
    relationships_truncated = len(returned_relationships) < len(relationship_candidates)
    parts_truncated = len(returned_parts) < len(part_candidates)
    blockers_truncated = len(returned_blockers) < len(blockers)
    return {
        **base_plan,
        "analysis_complete": not blockers,
        "package_xml_integrity_complete": (not xml_scan.integrity_blockers and not any(reason.startswith("xml_source_") for reason in source_blockers.values())),
        "projected_root_reachability_analyzed": True,
        "projected_root_reachable_part_count": len(graph_part_names & root_reachable_after_zero_ref_filter),
        "projected_root_unreachable_part_count": len(graph_part_names - root_reachable_after_zero_ref_filter),
        "projected_root_reachable_scoped_image_part_count": len(image_part_names & root_reachable_after_zero_ref_filter),
        "projected_root_unreachable_scoped_image_part_count": len(image_part_names - root_reachable_after_zero_ref_filter),
        "image_part_count": len(image_parts),
        "out_of_scope_image_part_count": len(all_image_parts) - len(image_parts),
        "image_relationship_count": scoped_relationship_count,
        "standard_image_relationship_count": standard_relationship_count,
        "nonstandard_image_relationship_count": nonstandard_relationship_count,
        "external_image_relationship_count": external_image_relationship_count,
        "xml_source_part_count": xml_scan.xml_source_part_count,
        "scanned_source_part_count": xml_scan.scanned_source_part_count,
        "scanned_xml_bytes": xml_scan.scanned_xml_bytes,
        "undeclared_relationship_reference_count": (xml_scan.undeclared_relationship_reference_count),
        "package_integrity_blocker_count": len(xml_scan.integrity_blockers),
        "relationship_source_blocker_count": len(source_blockers),
        "live_relationship_count": live_relationship_count,
        "unreferenced_relationship_count": unreferenced_relationship_count,
        "blocked_relationship_count": blocked_relationship_count,
        "relationship_candidate_count": len(relationship_candidates),
        "relationship_candidates_returned": len(returned_relationships),
        "relationship_candidates_truncated": relationships_truncated,
        "relationship_candidates": returned_relationships,
        "part_candidate_count": len(part_candidates),
        "zero_incoming_relationship_part_count": zero_incoming_relationship_part_count,
        "all_incoming_relationships_zero_xml_refs_part_count": (all_incoming_relationships_zero_xml_refs_part_count),
        "estimated_reclaimable_uncompressed_bytes": (estimated_reclaimable_uncompressed_bytes),
        "part_candidates_returned": len(returned_parts),
        "part_candidates_truncated": parts_truncated,
        "part_candidates": returned_parts,
        "root_unreachable_scoped_image_evidence_count": len(unreachable_part_evidence),
        "root_unreachable_scoped_image_evidence_returned": len(returned_unreachable_evidence),
        "root_unreachable_scoped_image_evidence_truncated": (unreachable_evidence_truncated),
        "root_unreachable_scoped_image_evidence": returned_unreachable_evidence,
        "blocker_count": len(blockers),
        "blockers_returned": len(returned_blockers),
        "blockers_truncated": blockers_truncated,
        "blockers": returned_blockers,
        "output_truncated": (relationships_truncated or parts_truncated or blockers_truncated or protected_parts_truncated or unreachable_evidence_truncated),
    }


def _nested_resource_relationships(
    package: _PackageInfo,
    source_part: str,
) -> tuple[_Relationship, ...]:
    relationships = package.relationships_by_source.get(source_part, {})
    nested: list[_Relationship] = []
    for relationship in relationships.values():
        kind = _relationship_kind(relationship)
        if kind == "slide":
            # Notes and comments may point back to their owning slide. The direct
            # slide relationship remains visible; nested back-references do not.
            continue
        if kind == "slideLayout" and package.content_types.for_part(source_part) == _SLIDE_MASTER_CONTENT_TYPE:
            # A master catalogs every layout that uses it. Following those edges
            # would make one selected slide appear to own the whole layout set.
            continue
        nested.append(relationship)
    return tuple(nested)


def _slide_resources(
    slide: _Slide,
    *,
    slide_index: int,
    object_refs: list[_ObjectRef],
    package: _PackageInfo,
) -> tuple[list[dict[str, Any]], bool]:
    slide_path = f"/slide[{slide_index}]"
    direct_owners: dict[str, list[str]] = {}
    for ref in object_refs:
        for relationship_id in _object_relationship_ids(ref):
            owners = direct_owners.setdefault(relationship_id, [])
            if ref.path not in owners:
                owners.append(ref.path)

    records: dict[tuple[str, str], dict[str, Any]] = {}
    queue: list[tuple[str, _Relationship, int, str]] = []
    scheduled_contexts: set[tuple[str, str, str]] = set()
    traversal_truncated = False

    def schedule(
        source_part: str,
        relationship: _Relationship,
        depth: int,
        owner_path: str,
    ) -> bool:
        context = (source_part, relationship.relationship_id, owner_path)
        if context in scheduled_contexts:
            return True
        if len(scheduled_contexts) >= _MAX_RESOURCE_GRAPH_EDGES_PER_SLIDE:
            return False
        scheduled_contexts.add(context)
        queue.append((source_part, relationship, depth, owner_path))
        return True

    for relationship in slide.relationships.values():
        owner_paths = direct_owners.get(relationship.relationship_id) or [slide_path]
        for owner_path in owner_paths:
            if not schedule(slide.part_name, relationship, 0, owner_path):
                traversal_truncated = True
                break
        if traversal_truncated:
            break

    # Breadth-first traversal makes the first scheduled context its minimum depth.
    queue_index = 0
    while queue_index < len(queue):
        source_part, relationship, depth, owner_path = queue[queue_index]
        queue_index += 1
        key = (source_part, relationship.relationship_id)
        record = records.get(key)
        if record is None:
            record = _resource_record(
                source_part=source_part,
                relationship=relationship,
                depth=depth,
                package=package,
            )
            records[key] = record
        else:
            record["depth"] = min(record["depth"], depth)
        owners = record["owner_paths"]
        if owner_path not in owners:
            if len(owners) < _MAX_RESOURCE_OWNERS:
                owners.append(owner_path)
            else:
                record["owner_paths_truncated"] = True

        if relationship.external or _relationship_kind(relationship) in {
            "hyperlink",
            "slide",
        }:
            continue
        target_part = _resolve_relationship_target(source_part, relationship.target)
        if traversal_truncated:
            continue
        for nested in _nested_resource_relationships(package, target_part):
            if not schedule(target_part, nested, depth + 1, owner_path):
                traversal_truncated = True
                break

    return list(records.values()), traversal_truncated


def _append_text_item(
    items: list[dict[str, Any]],
    *,
    path: str,
    item_type: str,
    text: str,
    budget: dict[str, int],
) -> bool:
    if not text.strip():
        return True
    if len(items) >= _MAX_INSPECT_TEXT_ITEMS or budget["characters"] >= _MAX_INSPECT_TEXT_CHARS:
        return False
    available = min(
        _MAX_TEXT_ITEM_CHARS,
        _MAX_INSPECT_TEXT_CHARS - budget["characters"],
    )
    returned_text = text[:available]
    items.append(
        {
            "path": path,
            "type": item_type,
            "text": returned_text,
            "truncated": len(returned_text) < len(text),
        }
    )
    budget["characters"] += len(returned_text)
    return len(returned_text) == len(text)


def _slide_text_items(
    object_refs: list[_ObjectRef],
    *,
    budget: dict[str, int],
) -> tuple[list[dict[str, Any]], bool]:
    items: list[dict[str, Any]] = []
    truncated = False
    for ref in object_refs:
        if ref.path_kind == "shape":
            complete = _append_text_item(
                items,
                path=ref.path,
                item_type="title" if ref.kind == "title" else "text_box",
                text=_shape_text(ref.element),
                budget=budget,
            )
            if not complete:
                truncated = True
        elif ref.kind == "table":
            table = _table_element(ref)
            if table is not None:
                for row_index, row in enumerate(_children(table, "tr"), start=1):
                    for cell_index, cell in enumerate(_children(row, "tc"), start=1):
                        complete = _append_text_item(
                            items,
                            path=(f"{ref.path}/row[{row_index}]/cell[{cell_index}]"),
                            item_type="table_cell",
                            text=_text_body_text(_first_child(cell, "txBody")),
                            budget=budget,
                        )
                        if not complete:
                            truncated = True
        if len(items) >= _MAX_INSPECT_TEXT_ITEMS or budget["characters"] >= _MAX_INSPECT_TEXT_CHARS:
            return items, True
    return items, truncated


def _annotation_relationships(
    relationships: dict[str, _Relationship],
    relationship_types: frozenset[str],
) -> list[_Relationship]:
    return [relationship for relationship in relationships.values() if relationship.relationship_type in relationship_types]


def _annotation_root(
    archive: zipfile.ZipFile,
    *,
    package: _PackageInfo,
    source_part: str,
    relationship: _Relationship,
    content_type: str,
    root_names: frozenset[str],
    root_namespaces: frozenset[str],
    cache: dict[str, Any],
) -> tuple[str, Any]:
    if relationship.external:
        raise OfficePackageError(f"PPTX {source_part} annotation relationship must be internal")
    part_name = _resolve_relationship_target(source_part, relationship.target)
    if package.content_types.for_part(part_name) != content_type:
        raise OfficePackageError(f"PPTX {part_name} has an unexpected annotation content type")
    root = cache.get(part_name)
    if root is None:
        root = _safe_xml_root(
            archive.read(part_name),
            label=part_name,
            limit=_MAX_ANNOTATION_XML_BYTES,
        )
        root_name = _qname(root)
        if root_name.localname not in root_names or root_name.namespace not in root_namespaces:
            raise OfficePackageError(f"PPTX {part_name} has an unexpected annotation root element")
        relationships = package.relationships_by_source.get(part_name, {})
        _validate_referenced_relationships(
            root,
            relationships,
            label=part_name,
        )
        _action_risks(root, relationships, label=part_name)
        cache[part_name] = root
    return part_name, root


def _annotation_text(
    value: str,
    *,
    budget: dict[str, int],
    item_limit: int,
) -> tuple[str, bool]:
    available = max(
        0,
        min(
            item_limit,
            _MAX_INSPECT_ANNOTATION_CHARS - budget["characters"],
        ),
    )
    returned = value[:available]
    budget["characters"] += len(returned)
    return returned, len(returned) < len(value)


def _notes_text_body(notes_root: Any) -> Any | None:
    common_slide_data = _first_child(notes_root, "cSld")
    shape_tree = None if common_slide_data is None else _first_child(common_slide_data, "spTree")
    if shape_tree is None:
        return None
    typed_body: Any | None = None
    indexed_body: Any | None = None
    for shape in _children(shape_tree, "sp"):
        non_visual = _first_child(shape, "nvSpPr")
        application_properties = None if non_visual is None else _first_child(non_visual, "nvPr")
        placeholder = None if application_properties is None else _first_child(application_properties, "ph")
        if placeholder is None:
            continue
        text_body = _first_child(shape, "txBody")
        if text_body is None:
            continue
        if placeholder.get("type") == "body":
            typed_body = text_body
            break
        if placeholder.get("idx") == "1" and indexed_body is None:
            indexed_body = text_body
    return typed_body if typed_body is not None else indexed_body


def _annotation_author_value(
    author: dict[str, Any] | None,
    key: str,
) -> tuple[str | None, bool]:
    if author is None:
        return None, False
    return author.get(key), author.get(f"{key}_truncated") is True


def _legacy_comment_author_id(
    raw_value: str | None,
    *,
    path: str,
    required: bool,
) -> str | None:
    if raw_value in {None, ""}:
        if required:
            raise OfficePackageError("PPTX legacy comment author is missing an ID")
        return None
    value = _typed_integer_value(
        raw_value,
        path=path,
        attribute="legacy comment author ID",
        maximum=4_294_967_295,
    )
    return None if value is None else str(value)


def _modern_comment_author_id(
    raw_value: str | None,
    *,
    path: str,
    required: bool,
) -> str | None:
    if raw_value in {None, ""}:
        if required:
            raise OfficePackageError("PPTX modern comment author is missing an ID")
        return None
    value, truncated = _bounded_string(
        raw_value,
        _MAX_OBJECT_NAME_CHARS,
    )
    if truncated:
        raise OfficePackageError(f"PPTX metadata at {path} has an overlong modern comment author ID")
    return value


def _modern_annotation_path(
    *,
    parent_path: str,
    kind: str,
    raw_id: str | None,
    fallback_index: int,
    seen_paths: set[str],
) -> tuple[str, bool]:
    bounded_id, id_truncated = _bounded_string(raw_id, 128)
    if bounded_id and not id_truncated:
        escaped_id = quote(bounded_id, safe="-._~")
        path = f"{parent_path}/{kind}[@id={escaped_id}]"
        if path not in seen_paths:
            seen_paths.add(path)
            return path, True
    path = f"{parent_path}/{kind}[{fallback_index}]"
    seen_paths.add(path)
    return path, False


def _legacy_annotation_path(
    comment: Any,
    *,
    slide_path: str,
    fallback_index: int,
    seen_paths: set[str],
) -> tuple[str, bool]:
    fallback_path = f"{slide_path}/comment[{fallback_index}]"
    author_id = _legacy_comment_author_id(
        comment.get("authorId"),
        path=fallback_path,
        required=False,
    )
    authored_index = _typed_integer_value(
        comment.get("idx"),
        path=fallback_path,
        attribute="comment index",
        maximum=2_147_483_647,
    )
    if author_id is not None and authored_index is not None:
        path = f"{slide_path}/comment[@author_id={author_id}][@index={authored_index}]"
        if path not in seen_paths:
            seen_paths.add(path)
            return path, True
    seen_paths.add(fallback_path)
    return fallback_path, False


def _annotation_author_record(author: Any) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for key in ("name", "initials"):
        value, truncated = _bounded_string(
            author.get(key) or "",
            _MAX_OBJECT_NAME_CHARS,
        )
        record[key] = value or ""
        if truncated:
            record[f"{key}_truncated"] = True
    return record


def _legacy_comment_authors(
    roots: list[Any],
    *,
    budget: dict[str, int],
) -> tuple[dict[str, dict[str, Any]], bool]:
    authors: dict[str, dict[str, Any]] = {}
    for root in roots:
        for author_index, author in enumerate(
            _children(root, "cmAuthor"),
            start=1,
        ):
            if budget["authors"] >= _MAX_ANNOTATION_AUTHORS:
                return authors, True
            author_id = _legacy_comment_author_id(
                author.get("id"),
                path=f"/legacy_comment_author[{author_index}]",
                required=True,
            )
            if author_id in authors:
                raise OfficePackageError("PPTX legacy comment authors contain a duplicate ID")
            authors[author_id] = _annotation_author_record(author)
            budget["authors"] += 1
    return authors, False


def _modern_comment_authors(
    roots: list[Any],
    *,
    budget: dict[str, int],
) -> tuple[dict[str, dict[str, Any]], bool]:
    authors: dict[str, dict[str, Any]] = {}
    for root in roots:
        for author_index, author in enumerate(
            _children(root, "author"),
            start=1,
        ):
            if budget["authors"] >= _MAX_ANNOTATION_AUTHORS:
                return authors, True
            author_id = _modern_comment_author_id(
                author.get("id"),
                path=f"/modern_comment_author[{author_index}]",
                required=True,
            )
            if author_id in authors:
                raise OfficePackageError("PPTX modern comment authors contain a duplicate ID")
            authors[author_id] = _annotation_author_record(author)
            budget["authors"] += 1
    return authors, False


def _comment_author_fields(
    record: dict[str, Any],
    *,
    author_id: str | None,
    authors: dict[str, dict[str, Any]],
) -> None:
    if author_id is not None:
        bounded_id, id_truncated = _bounded_string(
            author_id,
            _MAX_OBJECT_NAME_CHARS,
        )
        record["author_id"] = bounded_id
        if id_truncated:
            record["author_id_truncated"] = True
    author = None if author_id is None else authors.get(author_id)
    for key in ("name", "initials"):
        value, value_truncated = _annotation_author_value(author, key)
        if value is not None:
            record["author" if key == "name" else key] = value
        if value_truncated:
            record[f"{'author' if key == 'name' else key}_truncated"] = True
    if author_id is not None and author is None:
        record["author_resolved"] = False
    elif author_id is not None:
        record["author_resolved"] = True


def _legacy_comment_record(
    comment: Any,
    *,
    path: str,
    part_name: str,
    authors: dict[str, dict[str, Any]],
    budget: dict[str, int],
) -> dict[str, Any]:
    text_element = _first_child(comment, "text")
    text, text_truncated = _annotation_text(
        "" if text_element is None else text_element.text or "",
        budget=budget,
        item_limit=_MAX_INSPECT_COMMENT_CHARS,
    )
    record: dict[str, Any] = {
        "path": path,
        "type": "comment",
        "part_name": part_name,
        "text": text,
    }
    if text_truncated:
        record["text_truncated"] = True
    _comment_author_fields(
        record,
        author_id=_legacy_comment_author_id(
            comment.get("authorId"),
            path=path,
            required=False,
        ),
        authors=authors,
    )
    authored_index = _typed_integer_value(
        comment.get("idx"),
        path=path,
        attribute="comment index",
        maximum=2_147_483_647,
    )
    if authored_index is not None:
        record["authored_index"] = authored_index
    created, created_truncated = _bounded_attribute(
        comment,
        "dt",
        limit=128,
    )
    if created is not None:
        record["created"] = created
    if created_truncated:
        record["created_truncated"] = True
    position = _first_child(comment, "pos")
    if position is not None:
        x = _typed_integer_value(
            position.get("x"),
            path=path,
            attribute="comment x",
            minimum=-9_007_199_254_740_991,
            maximum=9_007_199_254_740_991,
        )
        y = _typed_integer_value(
            position.get("y"),
            path=path,
            attribute="comment y",
            minimum=-9_007_199_254_740_991,
            maximum=9_007_199_254_740_991,
        )
        if x is not None or y is not None:
            record["position"] = {"x_emu": x, "y_emu": y}
    return record


def _modern_comment_record(
    comment: Any,
    *,
    path: str,
    part_name: str,
    record_type: str,
    parent_path: str | None,
    authors: dict[str, dict[str, Any]],
    budget: dict[str, int],
) -> dict[str, Any]:
    text_body = _first_child(comment, "txBody")
    text, text_truncated = _annotation_text(
        _text_body_text(text_body),
        budget=budget,
        item_limit=_MAX_INSPECT_COMMENT_CHARS,
    )
    record: dict[str, Any] = {
        "path": path,
        "type": record_type,
        "part_name": part_name,
        "parent_path": parent_path,
        "text": text,
    }
    if text_truncated:
        record["text_truncated"] = True
    _comment_author_fields(
        record,
        author_id=_modern_comment_author_id(
            comment.get("authorId"),
            path=path,
            required=False,
        ),
        authors=authors,
    )
    comment_id, comment_id_truncated = _bounded_attribute(
        comment,
        "id",
        limit=128,
    )
    if comment_id is not None:
        record["id"] = comment_id
    if comment_id_truncated:
        record["id_truncated"] = True
    created, created_truncated = _bounded_attribute(
        comment,
        "created",
        limit=128,
    )
    if created is not None:
        record["created"] = created
    if created_truncated:
        record["created_truncated"] = True
    if record_type == "comment_thread":
        record["resolved"] = (comment.get("status") or "").lower() == "resolved"
    position = _first_child(comment, "pos")
    if position is not None:
        x = _typed_integer_value(
            position.get("x"),
            path=path,
            attribute="comment x",
            minimum=-9_007_199_254_740_991,
            maximum=9_007_199_254_740_991,
        )
        y = _typed_integer_value(
            position.get("y"),
            path=path,
            attribute="comment y",
            minimum=-9_007_199_254_740_991,
            maximum=9_007_199_254_740_991,
        )
        if x is not None or y is not None:
            record["position"] = {"x_emu": x, "y_emu": y}
    return record


def _inspect_annotations(
    data: bytes,
    *,
    package: _PackageInfo,
    selected: tuple[_Slide, ...],
    start_slide: int,
    include_formatting: bool,
    formatting_budget: dict[str, int],
) -> dict[int, dict[str, Any]]:
    budget = {
        "items": 0,
        "characters": 0,
        "scanned": 0,
        "authors": 0,
    }
    results: dict[int, dict[str, Any]] = {}
    cache: dict[str, Any] = {}
    comment_scan_stopped = False
    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            presentation_relationships = package.relationships_by_source.get(
                _PRESENTATION_XML,
                {},
            )
            legacy_author_roots = [
                _annotation_root(
                    archive,
                    package=package,
                    source_part=_PRESENTATION_XML,
                    relationship=relationship,
                    content_type=_LEGACY_COMMENT_AUTHORS_CONTENT_TYPE,
                    root_names=frozenset({"cmAuthorLst"}),
                    root_namespaces=_PRESENTATION_NAMESPACES,
                    cache=cache,
                )[1]
                for relationship in _annotation_relationships(
                    presentation_relationships,
                    _LEGACY_COMMENT_AUTHORS_RELATIONSHIP_TYPES,
                )
            ]
            modern_author_roots = [
                _annotation_root(
                    archive,
                    package=package,
                    source_part=_PRESENTATION_XML,
                    relationship=relationship,
                    content_type=_MODERN_COMMENT_AUTHORS_CONTENT_TYPE,
                    root_names=frozenset({"authorLst"}),
                    root_namespaces=frozenset({_POWERPOINT_COMMENTS_NS}),
                    cache=cache,
                )[1]
                for relationship in _annotation_relationships(
                    presentation_relationships,
                    _MODERN_COMMENT_AUTHORS_RELATIONSHIP_TYPES,
                )
            ]
            legacy_authors, legacy_authors_truncated = _legacy_comment_authors(
                legacy_author_roots,
                budget=budget,
            )
            modern_authors, modern_authors_truncated = _modern_comment_authors(
                modern_author_roots,
                budget=budget,
            )
            authors_truncated = legacy_authors_truncated or modern_authors_truncated

            for slide_index, slide in enumerate(selected, start=start_slide):
                slide_path = f"/slide[{slide_index}]"
                notes_relationships = _annotation_relationships(
                    slide.relationships,
                    _NOTES_RELATIONSHIP_TYPES,
                )
                if len(notes_relationships) > 1:
                    raise OfficePackageError(f"PPTX {slide.part_name} has multiple notes slide relationships")
                notes: dict[str, Any] | None = None
                if notes_relationships:
                    part_name, notes_root = _annotation_root(
                        archive,
                        package=package,
                        source_part=slide.part_name,
                        relationship=notes_relationships[0],
                        content_type=_NOTES_CONTENT_TYPE,
                        root_names=frozenset({"notes"}),
                        root_namespaces=_PRESENTATION_NAMESPACES,
                        cache=cache,
                    )
                    text_body = _notes_text_body(notes_root)
                    source_text = _text_body_text(text_body)
                    note_text, note_text_truncated = _annotation_text(
                        source_text,
                        budget=budget,
                        item_limit=_MAX_INSPECT_NOTE_CHARS,
                    )
                    notes = {
                        "path": f"{slide_path}/notes",
                        "part_name": part_name,
                        "body_found": text_body is not None,
                        "text": note_text,
                        "paragraph_count": (0 if text_body is None else len(_children(text_body, "p"))),
                    }
                    if note_text_truncated:
                        notes["text_truncated"] = True
                    if include_formatting and text_body is not None:
                        notes["text_body"], formatting_truncated = _text_body_inspection(
                            text_body,
                            base_path=f"{slide_path}/notes",
                            budget=formatting_budget,
                        )
                        if formatting_truncated:
                            notes["formatting_truncated"] = True

                legacy_count = 0
                modern_thread_count = 0
                modern_reply_count = 0
                comment_items: list[dict[str, Any]] = []
                comment_paths: set[str] = set()
                slide_scan_truncated = False
                legacy_relationships = _annotation_relationships(
                    slide.relationships,
                    _LEGACY_COMMENTS_RELATIONSHIP_TYPES,
                )
                if comment_scan_stopped and legacy_relationships:
                    slide_scan_truncated = True
                for relationship in legacy_relationships:
                    if comment_scan_stopped:
                        break
                    part_name, root = _annotation_root(
                        archive,
                        package=package,
                        source_part=slide.part_name,
                        relationship=relationship,
                        content_type=_LEGACY_COMMENTS_CONTENT_TYPE,
                        root_names=frozenset({"cmLst"}),
                        root_namespaces=_PRESENTATION_NAMESPACES,
                        cache=cache,
                    )
                    for comment in _children(root, "cm"):
                        if budget["scanned"] >= _MAX_ANNOTATION_SCAN_ITEMS:
                            comment_scan_stopped = True
                            slide_scan_truncated = True
                            break
                        budget["scanned"] += 1
                        legacy_count += 1
                        if budget["items"] >= _MAX_INSPECT_ANNOTATIONS:
                            continue
                        comment_path, path_stable = _legacy_annotation_path(
                            comment,
                            slide_path=slide_path,
                            fallback_index=legacy_count,
                            seen_paths=comment_paths,
                        )
                        record = _legacy_comment_record(
                            comment,
                            path=comment_path,
                            part_name=part_name,
                            authors=legacy_authors,
                            budget=budget,
                        )
                        if not path_stable:
                            record["path_stable"] = False
                        comment_items.append(record)
                        budget["items"] += 1

                modern_relationships = _annotation_relationships(
                    slide.relationships,
                    _MODERN_COMMENTS_RELATIONSHIP_TYPES,
                )
                if comment_scan_stopped and modern_relationships:
                    slide_scan_truncated = True
                for relationship in modern_relationships:
                    if comment_scan_stopped:
                        break
                    part_name, root = _annotation_root(
                        archive,
                        package=package,
                        source_part=slide.part_name,
                        relationship=relationship,
                        content_type=_MODERN_COMMENTS_CONTENT_TYPE,
                        root_names=frozenset({"cmLst"}),
                        root_namespaces=frozenset({_POWERPOINT_COMMENTS_NS}),
                        cache=cache,
                    )
                    for comment in _children(root, "cm"):
                        if budget["scanned"] >= _MAX_ANNOTATION_SCAN_ITEMS:
                            comment_scan_stopped = True
                            slide_scan_truncated = True
                            break
                        budget["scanned"] += 1
                        modern_thread_count += 1
                        thread_path, thread_path_stable = _modern_annotation_path(
                            parent_path=slide_path,
                            kind="comment_thread",
                            raw_id=comment.get("id"),
                            fallback_index=modern_thread_count,
                            seen_paths=comment_paths,
                        )
                        if budget["items"] < _MAX_INSPECT_ANNOTATIONS:
                            record = _modern_comment_record(
                                comment,
                                path=thread_path,
                                part_name=part_name,
                                record_type="comment_thread",
                                parent_path=None,
                                authors=modern_authors,
                                budget=budget,
                            )
                            if not thread_path_stable:
                                record["path_stable"] = False
                            comment_items.append(record)
                            budget["items"] += 1
                        reply_list = _first_child(comment, "replyLst")
                        replies = [] if reply_list is None else _children(reply_list, "reply")
                        for reply_index, reply in enumerate(replies, start=1):
                            if budget["scanned"] >= _MAX_ANNOTATION_SCAN_ITEMS:
                                comment_scan_stopped = True
                                slide_scan_truncated = True
                                break
                            budget["scanned"] += 1
                            modern_reply_count += 1
                            if budget["items"] >= _MAX_INSPECT_ANNOTATIONS:
                                continue
                            reply_path, reply_path_stable = _modern_annotation_path(
                                parent_path=thread_path,
                                kind="reply",
                                raw_id=reply.get("id"),
                                fallback_index=reply_index,
                                seen_paths=comment_paths,
                            )
                            record = _modern_comment_record(
                                reply,
                                path=reply_path,
                                part_name=part_name,
                                record_type="comment_reply",
                                parent_path=thread_path,
                                authors=modern_authors,
                                budget=budget,
                            )
                            if not reply_path_stable:
                                record["path_stable"] = False
                            comment_items.append(record)
                            budget["items"] += 1
                        if comment_scan_stopped:
                            break
                    if comment_scan_stopped:
                        break

                total_comments = legacy_count + modern_thread_count + modern_reply_count
                text_truncated = any(item.get("text_truncated") is True for item in comment_items)
                results[slide_index] = {
                    "notes": notes,
                    "comments": {
                        "legacy_count": legacy_count,
                        "modern_thread_count": modern_thread_count,
                        "modern_reply_count": modern_reply_count,
                        "returned": len(comment_items),
                        "scanned": total_comments,
                        "count_truncated": slide_scan_truncated,
                        "scan_truncated": slide_scan_truncated,
                        "authors_truncated": authors_truncated,
                        "truncated": (len(comment_items) < total_comments or text_truncated or slide_scan_truncated or authors_truncated),
                        "items": comment_items,
                    },
                }
    except OfficePackageError:
        raise
    except (KeyError, zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise OfficePackageError(f"Invalid PPTX annotations: {exc}") from exc
    return results


def _drawing_children(element: Any, local_name: str | None = None) -> list[Any]:
    return [child for child in element if isinstance(child.tag, str) and _qname(child).namespace in _DRAWING_NAMESPACES and (local_name is None or _local_name(child) == local_name)]


def _first_drawing_child(element: Any, local_name: str) -> Any | None:
    return next(iter(_drawing_children(element, local_name)), None)


def _drawing_namespace_for_context(element: Any) -> str:
    drawing_namespace = None
    current = element
    while current is not None:
        if isinstance(current.tag, str):
            namespace = _qname(current).namespace
            if namespace in _PRESENTATION_NAMESPACES:
                expected = _DRAWING_NAMESPACE_BY_PRESENTATION[namespace]
                if drawing_namespace is not None and drawing_namespace != expected:
                    raise OfficeOperationError("PPTX formatting target mixes Strict and Transitional DrawingML")
                return expected
            if drawing_namespace is None and namespace in _DRAWING_NAMESPACES:
                drawing_namespace = namespace
        current = current.getparent()
    if drawing_namespace is not None:
        return drawing_namespace
    candidates = {namespace for namespace in element.nsmap.values() if namespace in _DRAWING_NAMESPACES}
    if len(candidates) == 1:
        return candidates.pop()
    raise OfficeOperationError("PPTX formatting target has no unambiguous DrawingML namespace")


def _require_consistent_drawing_children(
    parent: Any,
    known_names: set[str] | frozenset[str] | dict[str, int],
    *,
    label: str,
) -> None:
    expected = _drawing_namespace_for_context(parent)
    mismatched = [_local_name(child) for child in parent if isinstance(child.tag, str) and _local_name(child) in known_names and _qname(child).namespace != expected]
    if mismatched:
        raise OfficeOperationError(f"{label} mixes Strict and Transitional DrawingML")


def _new_drawing_child(parent: Any, local_name: str) -> Any:
    return etree.Element(etree.QName(_drawing_namespace_for_context(parent), local_name))


def _insert_ordered_drawing_child(
    parent: Any,
    child: Any,
    ranks: dict[str, int],
) -> None:
    new_rank = ranks[_local_name(child)]
    for index, existing in enumerate(parent):
        if not isinstance(existing.tag, str) or _qname(existing).namespace not in _DRAWING_NAMESPACES:
            continue
        existing_rank = ranks.get(_local_name(existing))
        if existing_rank is not None and existing_rank > new_rank:
            parent.insert(index, child)
            return
    parent.append(child)


def _require_supported_child_order(
    parent: Any,
    ranks: dict[str, int],
    *,
    label: str,
) -> None:
    known_ranks = [ranks[_local_name(child)] for child in _drawing_children(parent) if _local_name(child) in ranks]
    if any(current < previous for previous, current in zip(known_ranks, known_ranks[1:])):
        raise OfficeOperationError(f"{label} uses unsupported DrawingML child order")


def _remove_drawing_children(parent: Any, local_names: set[str] | frozenset[str]) -> None:
    for child in list(parent):
        if isinstance(child.tag, str) and _qname(child).namespace in _DRAWING_NAMESPACES and _local_name(child) in local_names:
            parent.remove(child)


def _ensure_run_properties(run: Any) -> Any:
    properties = _first_drawing_child(run, "rPr")
    if properties is not None:
        return properties
    properties = _new_drawing_child(run, "rPr")
    text = _first_drawing_child(run, "t")
    if text is None:
        run.insert(0, properties)
    else:
        run.insert(run.index(text), properties)
    return properties


def _ensure_paragraph_properties(paragraph: Any) -> Any:
    properties = _first_drawing_child(paragraph, "pPr")
    if properties is not None:
        return properties
    properties = _new_drawing_child(paragraph, "pPr")
    paragraph.insert(0, properties)
    return properties


def _set_run_font(properties: Any, local_name: str, typeface: str) -> None:
    fonts = _drawing_children(properties, local_name)
    if len(fonts) > 1:
        raise OfficeOperationError(f"PPTX run properties contain duplicate {local_name} font slots")
    if fonts:
        fonts[0].set("typeface", typeface)
        return
    font = _new_drawing_child(properties, local_name)
    font.set("typeface", typeface)
    _insert_ordered_drawing_child(properties, font, _RUN_PROPERTY_CHILD_RANK)


def _require_supported_solid_fill_color(
    solid_fill: Any,
    *,
    label: str,
) -> list[Any]:
    expected_namespace = _drawing_namespace_for_context(solid_fill)
    children = [child for child in solid_fill if isinstance(child.tag, str)]
    if any(_qname(child).namespace != expected_namespace or _local_name(child) not in _RUN_COLOR_CHILDREN for child in children):
        raise OfficeOperationError(f"{label} contains an unsupported color child")
    colors = children
    if len(colors) > 1:
        raise OfficeOperationError(f"{label} contains multiple colors")
    if colors and any(isinstance(child.tag, str) and _qname(child).namespace != expected_namespace for child in colors[0]):
        raise OfficeOperationError(f"{label} contains a mixed-namespace color transform")
    return colors


def _set_solid_fill_color(
    solid_fill: Any,
    color: str,
    *,
    label: str,
) -> None:
    colors = _require_supported_solid_fill_color(
        solid_fill,
        label=label,
    )
    if colors:
        rgb = colors[0]
        rgb.tag = etree.QName(_qname(rgb).namespace, "srgbClr")
        rgb.attrib.clear()
    else:
        rgb = _new_drawing_child(solid_fill, "srgbClr")
        solid_fill.append(rgb)
    rgb.set("val", color.removeprefix("#").upper())


def _set_run_color(properties: Any, color: str) -> None:
    fills = [child for child in _drawing_children(properties) if _local_name(child) in _RUN_FILL_CHILDREN]
    if len(fills) > 1:
        raise OfficeOperationError("PPTX run properties contain multiple direct fills")
    if fills and _local_name(fills[0]) not in {"noFill", "solidFill"}:
        raise OfficeOperationError("PPTX run color cannot replace a gradient, pattern, picture, or group fill")
    if not fills or _local_name(fills[0]) == "noFill":
        _remove_drawing_children(properties, _RUN_FILL_CHILDREN)
        solid_fill = _new_drawing_child(properties, "solidFill")
        _insert_ordered_drawing_child(
            properties,
            solid_fill,
            _RUN_PROPERTY_CHILD_RANK,
        )
    else:
        solid_fill = fills[0]

    _set_solid_fill_color(
        solid_fill,
        color,
        label="PPTX solid text fill",
    )


def _formatting_property_names(formatting: Any) -> set[str]:
    return {name for name in type(formatting).model_fields if getattr(formatting, name) is not None}


def _apply_pptx_run_formatting(run: Any, formatting: PptxRunFormatting) -> bool:
    before = etree.tostring(run, method="c14n", with_comments=True)
    properties = _ensure_run_properties(run)
    _require_supported_child_order(
        properties,
        _RUN_PROPERTY_CHILD_RANK,
        label="PPTX run properties",
    )
    if formatting.bold is not None:
        properties.set("b", "1" if formatting.bold else "0")
    if formatting.italic is not None:
        properties.set("i", "1" if formatting.italic else "0")
    if formatting.font_size is not None:
        properties.set("sz", str(round(formatting.font_size * 100)))
    if formatting.underline is not None:
        properties.set(
            "u",
            {"none": "none", "single": "sng", "double": "dbl"}[formatting.underline],
        )
        if formatting.underline == "none":
            _remove_drawing_children(properties, _RUN_UNDERLINE_CHILDREN)
    if formatting.strike is not None:
        properties.set(
            "strike",
            {
                "none": "noStrike",
                "single": "sngStrike",
                "double": "dblStrike",
            }[formatting.strike],
        )
    if formatting.color is not None:
        _set_run_color(properties, formatting.color)
    if formatting.font is not None:
        _set_run_font(properties, "latin", formatting.font)
        _set_run_font(properties, "ea", formatting.font)
    if formatting.font_latin is not None:
        _set_run_font(properties, "latin", formatting.font_latin)
    if formatting.font_east_asia is not None:
        _set_run_font(properties, "ea", formatting.font_east_asia)
    if formatting.font_complex_script is not None:
        _set_run_font(properties, "cs", formatting.font_complex_script)
    return before != etree.tostring(run, method="c14n", with_comments=True)


def _set_paragraph_spacing(
    properties: Any,
    container_name: str,
    value_name: str,
    value: int,
) -> None:
    _remove_drawing_children(properties, {container_name})
    container = _new_drawing_child(properties, container_name)
    spacing = _new_drawing_child(properties, value_name)
    spacing.set("val", str(value))
    container.append(spacing)
    _insert_ordered_drawing_child(
        properties,
        container,
        _PARAGRAPH_PROPERTY_CHILD_RANK,
    )


def _apply_pptx_paragraph_formatting(
    paragraph: Any,
    formatting: PptxParagraphFormatting,
) -> bool:
    before = etree.tostring(paragraph, method="c14n", with_comments=True)
    properties = _ensure_paragraph_properties(paragraph)
    _require_supported_child_order(
        properties,
        _PARAGRAPH_PROPERTY_CHILD_RANK,
        label="PPTX paragraph properties",
    )
    if formatting.alignment is not None:
        properties.set(
            "algn",
            {
                "left": "l",
                "center": "ctr",
                "right": "r",
                "justify": "just",
            }[formatting.alignment],
        )
    if formatting.space_before is not None:
        _set_paragraph_spacing(
            properties,
            "spcBef",
            "spcPts",
            round(formatting.space_before * 100),
        )
    if formatting.space_after is not None:
        _set_paragraph_spacing(
            properties,
            "spcAft",
            "spcPts",
            round(formatting.space_after * 100),
        )
    if formatting.line_spacing_points is not None:
        _set_paragraph_spacing(
            properties,
            "lnSpc",
            "spcPts",
            round(formatting.line_spacing_points * 100),
        )
    if formatting.line_spacing_percent is not None:
        _set_paragraph_spacing(
            properties,
            "lnSpc",
            "spcPct",
            round(formatting.line_spacing_percent * 1_000),
        )
    return before != etree.tostring(paragraph, method="c14n", with_comments=True)


def _direct_fill_children(
    parent: Any,
    fill_names: frozenset[str],
) -> list[Any]:
    return [child for child in _drawing_children(parent) if _local_name(child) in fill_names]


def _validate_png_asset(
    payload: bytes,
    *,
    label: str,
) -> _ValidatedImageAsset:
    if not isinstance(payload, bytes) or not payload:
        raise OfficeOperationError(f"{label} is empty")
    if len(payload) > _MAX_IMAGE_ASSET_BYTES:
        raise OfficeOperationError(f"{label} exceeds the 10 MiB image limit")
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise OfficeOperationError(f"{label} is not a PNG image")

    offset = 8
    header: tuple[int, int, int, int] | None = None
    idat_chunks: list[bytes] = []
    seen_palette = False
    seen_idat = False
    idat_closed = False
    seen_end = False
    while offset < len(payload):
        if len(payload) - offset < 12:
            raise OfficeOperationError(f"{label} has a truncated PNG chunk")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(payload):
            raise OfficeOperationError(f"{label} has a truncated PNG chunk")
        if len(chunk_type) != 4 or any(not (65 <= value <= 90 or 97 <= value <= 122) for value in chunk_type):
            raise OfficeOperationError(f"{label} has an invalid PNG chunk type")
        chunk_payload = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise OfficeOperationError(f"{label} has an invalid PNG chunk checksum")

        if offset == 8 and chunk_type != b"IHDR":
            raise OfficeOperationError(f"{label} must start with a PNG IHDR chunk")
        if chunk_type == b"IHDR":
            if header is not None or length != 13:
                raise OfficeOperationError(f"{label} has an invalid PNG IHDR chunk")
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", chunk_payload)
            if not 1 <= width <= _MAX_IMAGE_DIMENSION or not 1 <= height <= _MAX_IMAGE_DIMENSION or width * height > _MAX_IMAGE_PIXELS:
                raise OfficeOperationError(f"{label} has unsupported PNG dimensions")
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if bit_depth not in valid_depths.get(color_type, set()) or compression != 0 or filter_method != 0 or interlace != 0:
                raise OfficeOperationError(f"{label} uses an unsupported PNG encoding")
            header = (width, height, bit_depth, color_type)
        elif chunk_type == b"PLTE":
            if header is None or seen_palette or seen_idat or length < 3 or length > 768 or length % 3:
                raise OfficeOperationError(f"{label} has an invalid PNG palette")
            seen_palette = True
        elif chunk_type == b"IDAT":
            if header is None or idat_closed:
                raise OfficeOperationError(f"{label} has invalid PNG image-data ordering")
            seen_idat = True
            idat_chunks.append(chunk_payload)
        elif chunk_type == b"IEND":
            if not seen_idat or length != 0 or chunk_end != len(payload):
                raise OfficeOperationError(f"{label} has an invalid PNG end chunk")
            seen_end = True
        else:
            if seen_idat:
                idat_closed = True
            if chunk_type[0] & 0x20 == 0:
                raise OfficeOperationError(f"{label} contains an unsupported critical PNG chunk")
        offset = chunk_end

    if header is None or not seen_end:
        raise OfficeOperationError(f"{label} is an incomplete PNG image")
    width, height, bit_depth, color_type = header
    if color_type == 3 and not seen_palette:
        raise OfficeOperationError(f"{label} is missing its PNG palette")
    if color_type in {0, 4} and seen_palette:
        raise OfficeOperationError(f"{label} has a forbidden PNG palette")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = (width * channels * bit_depth + 7) // 8
    expected_size = height * (row_bytes + 1)
    decompressor = zlib.decompressobj()
    decoded = bytearray()
    try:
        for chunk in idat_chunks:
            decoded.extend(decompressor.decompress(chunk, expected_size + 1 - len(decoded)))
            if decompressor.unconsumed_tail or len(decoded) > expected_size:
                raise OfficeOperationError(f"{label} expands beyond its declared PNG dimensions")
        decoded.extend(decompressor.flush(expected_size + 1 - len(decoded)))
    except zlib.error as exc:
        raise OfficeOperationError(f"{label} contains invalid compressed PNG data") from exc
    if not decompressor.eof or decompressor.unused_data or len(decoded) != expected_size:
        raise OfficeOperationError(f"{label} contains incomplete PNG image data")
    if any(decoded[row * (row_bytes + 1)] > 4 for row in range(height)):
        raise OfficeOperationError(f"{label} contains an invalid PNG row filter")
    return _ValidatedImageAsset(
        digest=hashlib.sha256(payload).hexdigest(),
        content_type=_PNG_CONTENT_TYPE,
        extension=".png",
        width=width,
        height=height,
    )


def _validate_jpeg_asset(
    payload: bytes,
    *,
    label: str,
) -> _ValidatedImageAsset:
    if not isinstance(payload, bytes) or not payload:
        raise OfficeOperationError(f"{label} is empty")
    if len(payload) > _MAX_IMAGE_ASSET_BYTES:
        raise OfficeOperationError(f"{label} exceeds the 10 MiB image limit")
    if len(payload) < 4 or payload[:2] != b"\xff\xd8":
        raise OfficeOperationError(f"{label} is not a JPEG image")

    start_of_frame_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    offset = 2
    width = 0
    height = 0
    frame_component_ids: tuple[int, ...] = ()
    frame_quantization_tables: set[int] = set()
    quantization_tables: set[int] = set()
    huffman_tables: set[tuple[int, int]] = set()
    scan_count = 0
    seen_end = False

    while offset < len(payload):
        if payload[offset] != 0xFF:
            raise OfficeOperationError(f"{label} has invalid JPEG marker ordering")
        while offset < len(payload) and payload[offset] == 0xFF:
            offset += 1
        if offset >= len(payload):
            raise OfficeOperationError(f"{label} has a truncated JPEG marker")
        marker = payload[offset]
        offset += 1
        if marker == 0x00:
            raise OfficeOperationError(f"{label} has an invalid JPEG marker")
        if marker == 0xD9:
            if scan_count != 1 or offset != len(payload):
                raise OfficeOperationError(f"{label} has an invalid JPEG end marker")
            seen_end = True
            break
        if scan_count:
            raise OfficeOperationError(f"{label} contains unsupported JPEG markers after image data")
        if marker in {0xD8, 0x01, *range(0xD0, 0xD8)}:
            raise OfficeOperationError(f"{label} has an unexpected standalone JPEG marker")
        if len(payload) - offset < 2:
            raise OfficeOperationError(f"{label} has a truncated JPEG segment")
        segment_length = struct.unpack(">H", payload[offset : offset + 2])[0]
        if segment_length < 2:
            raise OfficeOperationError(f"{label} has an invalid JPEG segment length")
        segment_end = offset + segment_length
        if segment_end > len(payload):
            raise OfficeOperationError(f"{label} has a truncated JPEG segment")
        segment = payload[offset + 2 : segment_end]
        offset = segment_end

        if marker in start_of_frame_markers:
            if marker == 0xC2:
                raise OfficeOperationError(f"{label} uses progressive JPEG encoding")
            if marker in {0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                raise OfficeOperationError(f"{label} uses arithmetic-coded JPEG encoding")
            if marker != 0xC0:
                raise OfficeOperationError(f"{label} uses unsupported JPEG frame encoding")
            if frame_component_ids or len(segment) < 6:
                raise OfficeOperationError(f"{label} has an invalid JPEG frame header")
            precision = segment[0]
            height = struct.unpack(">H", segment[1:3])[0]
            width = struct.unpack(">H", segment[3:5])[0]
            component_count = segment[5]
            if precision != 8:
                raise OfficeOperationError(f"{label} must use 8-bit baseline JPEG samples")
            if component_count not in {1, 3}:
                raise OfficeOperationError(f"{label} uses unsupported CMYK or multi-component JPEG encoding")
            if len(segment) != 6 + 3 * component_count:
                raise OfficeOperationError(f"{label} has an invalid JPEG frame header")
            if not 1 <= width <= _MAX_IMAGE_DIMENSION or not 1 <= height <= _MAX_IMAGE_DIMENSION or width * height > _MAX_IMAGE_PIXELS:
                raise OfficeOperationError(f"{label} has unsupported JPEG dimensions")
            component_ids: list[int] = []
            sampling_units = 0
            for index in range(component_count):
                component_offset = 6 + index * 3
                component_id = segment[component_offset]
                sampling = segment[component_offset + 1]
                quantization_table = segment[component_offset + 2]
                horizontal_sampling = sampling >> 4
                vertical_sampling = sampling & 0x0F
                if component_id in component_ids or not 1 <= horizontal_sampling <= 4 or not 1 <= vertical_sampling <= 4 or quantization_table > 3:
                    raise OfficeOperationError(f"{label} has an invalid JPEG frame component")
                component_ids.append(component_id)
                frame_quantization_tables.add(quantization_table)
                sampling_units += horizontal_sampling * vertical_sampling
            if sampling_units > 10:
                raise OfficeOperationError(f"{label} has unsupported JPEG sampling factors")
            frame_component_ids = tuple(component_ids)
            continue

        if marker == 0xDB:
            if not segment:
                raise OfficeOperationError(f"{label} has an invalid JPEG quantization table")
            table_offset = 0
            while table_offset < len(segment):
                table_info = segment[table_offset]
                table_offset += 1
                precision = table_info >> 4
                table_id = table_info & 0x0F
                if precision != 0 or table_id > 3 or table_id in quantization_tables:
                    raise OfficeOperationError(f"{label} has an unsupported JPEG quantization table")
                if len(segment) - table_offset < 64:
                    raise OfficeOperationError(f"{label} has a truncated JPEG quantization table")
                if any(value == 0 for value in segment[table_offset : table_offset + 64]):
                    raise OfficeOperationError(f"{label} has an invalid JPEG quantization table")
                quantization_tables.add(table_id)
                table_offset += 64
            continue

        if marker == 0xC4:
            if not segment:
                raise OfficeOperationError(f"{label} has an invalid JPEG Huffman table")
            table_offset = 0
            while table_offset < len(segment):
                if len(segment) - table_offset < 17:
                    raise OfficeOperationError(f"{label} has a truncated JPEG Huffman table")
                table_info = segment[table_offset]
                table_class = table_info >> 4
                table_id = table_info & 0x0F
                code_counts = segment[table_offset + 1 : table_offset + 17]
                symbol_count = sum(code_counts)
                table_offset += 17
                table_key = (table_class, table_id)
                if table_class not in {0, 1} or table_id > 3 or table_key in huffman_tables or not 1 <= symbol_count <= 256:
                    raise OfficeOperationError(f"{label} has an unsupported JPEG Huffman table")
                if len(segment) - table_offset < symbol_count:
                    raise OfficeOperationError(f"{label} has a truncated JPEG Huffman table")
                table_offset += symbol_count
                huffman_tables.add(table_key)
            continue

        if marker == 0xDA:
            if not frame_component_ids or scan_count:
                raise OfficeOperationError(f"{label} has an unsupported JPEG scan layout")
            if len(segment) < 4:
                raise OfficeOperationError(f"{label} has an invalid JPEG scan header")
            component_count = segment[0]
            if component_count != len(frame_component_ids) or len(segment) != 1 + 2 * component_count + 3:
                raise OfficeOperationError(f"{label} has an unsupported JPEG scan layout")
            scan_component_ids: list[int] = []
            for index in range(component_count):
                component_offset = 1 + index * 2
                component_id = segment[component_offset]
                tables = segment[component_offset + 1]
                dc_table = tables >> 4
                ac_table = tables & 0x0F
                if component_id in scan_component_ids or (0, dc_table) not in huffman_tables or (1, ac_table) not in huffman_tables:
                    raise OfficeOperationError(f"{label} has an invalid JPEG scan component")
                scan_component_ids.append(component_id)
            if set(scan_component_ids) != set(frame_component_ids) or tuple(segment[-3:]) != (0, 63, 0):
                raise OfficeOperationError(f"{label} is not a single-scan baseline JPEG image")
            if not frame_quantization_tables <= quantization_tables:
                raise OfficeOperationError(f"{label} references a missing JPEG quantization table")
            scan_count = 1

            entropy_offset = offset
            entropy_data_seen = False
            while entropy_offset < len(payload):
                if payload[entropy_offset] != 0xFF:
                    entropy_data_seen = True
                    entropy_offset += 1
                    continue
                marker_end = entropy_offset + 1
                while marker_end < len(payload) and payload[marker_end] == 0xFF:
                    marker_end += 1
                if marker_end >= len(payload):
                    raise OfficeOperationError(f"{label} has truncated JPEG image data")
                entropy_marker = payload[marker_end]
                if entropy_marker == 0x00:
                    entropy_data_seen = True
                    entropy_offset = marker_end + 1
                    continue
                if 0xD0 <= entropy_marker <= 0xD7:
                    entropy_offset = marker_end + 1
                    continue
                if not entropy_data_seen:
                    raise OfficeOperationError(f"{label} has empty JPEG image data")
                offset = entropy_offset
                break
            else:
                raise OfficeOperationError(f"{label} has incomplete JPEG image data")
            continue

        if marker == 0xCC:
            raise OfficeOperationError(f"{label} uses arithmetic-coded JPEG encoding")
        if marker == 0xDD:
            if len(segment) != 2:
                raise OfficeOperationError(f"{label} has an invalid JPEG restart interval")
            continue
        if 0xE0 <= marker <= 0xEF:
            if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
                raise OfficeOperationError(f"{label} contains unsupported EXIF orientation metadata")
            if marker == 0xEE and segment.startswith(b"Adobe") and len(segment) >= 12 and segment[11] == 2:
                raise OfficeOperationError(f"{label} uses unsupported CMYK or YCCK JPEG encoding")
            continue
        if marker == 0xFE:
            continue
        raise OfficeOperationError(f"{label} contains an unsupported JPEG segment")

    if not seen_end or not frame_component_ids or not quantization_tables or not huffman_tables:
        raise OfficeOperationError(f"{label} is an incomplete JPEG image")
    return _ValidatedImageAsset(
        digest=hashlib.sha256(payload).hexdigest(),
        content_type=_JPEG_CONTENT_TYPE,
        extension=".jpg",
        width=width,
        height=height,
    )


def _validate_image_asset_for_path(
    payload: bytes,
    *,
    path: str,
    label: str,
) -> _ValidatedImageAsset:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".png":
        return _validate_png_asset(payload, label=label)
    if suffix in {".jpg", ".jpeg"}:
        return _validate_jpeg_asset(payload, label=label)
    raise OfficeOperationError(f"{label} has an unsupported image filename extension")


def _validate_image_asset_for_content_type(
    payload: bytes,
    *,
    content_type: str | None,
    label: str,
) -> _ValidatedImageAsset:
    if content_type == _PNG_CONTENT_TYPE:
        return _validate_png_asset(payload, label=label)
    if content_type == _JPEG_CONTENT_TYPE:
        return _validate_jpeg_asset(payload, label=label)
    raise OfficeOperationError(f"{label} has an unsupported embedded image content type")


def _require_supported_direct_fill(
    parent: Any,
    fill_names: frozenset[str],
    *,
    label: str,
    allow_gradient: bool = False,
    allow_pattern: bool = False,
    allow_image: bool = False,
) -> list[Any]:
    fills = _direct_fill_children(parent, fill_names)
    if len(fills) > 1:
        raise OfficeOperationError(f"{label} contains multiple direct fills")
    supported = {"noFill", "solidFill"}
    if allow_gradient:
        supported.add("gradFill")
    if allow_pattern:
        supported.add("pattFill")
    if allow_image:
        supported.add("blipFill")
    if fills and _local_name(fills[0]) not in supported:
        fill_label = {
            "gradFill": "gradient",
            "pattFill": "pattern",
            "blipFill": "picture",
            "grpFill": "group",
        }.get(_local_name(fills[0]), "unsupported")
        raise OfficeOperationError(f"{label} cannot replace a {fill_label} fill")
    return fills


def _gradient_boolean_attribute(
    element: Any,
    attribute: str,
    *,
    label: str,
) -> bool | None:
    raw_value = element.get(attribute)
    if raw_value is None:
        return None
    normalized = raw_value.lower()
    if normalized in {"1", "on", "true"}:
        return True
    if normalized in {"0", "false", "off"}:
        return False
    raise OfficeOperationError(f"{label} has invalid {attribute}")


def _gradient_integer_attribute(
    element: Any,
    attribute: str,
    *,
    label: str,
    minimum: int,
    maximum: int,
    required: bool = True,
) -> int | None:
    raw_value = element.get(attribute)
    if raw_value is None:
        if required:
            raise OfficeOperationError(f"{label} is missing {attribute}")
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise OfficeOperationError(f"{label} has invalid {attribute}") from exc
    if not minimum <= value <= maximum:
        raise OfficeOperationError(f"{label} has out-of-range {attribute}")
    return value


def _gradient_signature(
    gradient: Any,
    *,
    label: str,
) -> tuple[
    bool | None,
    tuple[tuple[int, str, int | None], ...],
    tuple[Any, ...],
]:
    expected_namespace = _drawing_namespace_for_context(gradient)
    if set(gradient.attrib) - {"rotWithShape"}:
        raise OfficeOperationError(f"{label} contains unsupported gradient attributes")
    rotate_with_shape = _gradient_boolean_attribute(
        gradient,
        "rotWithShape",
        label=label,
    )

    if any(not isinstance(child.tag, str) for child in gradient):
        raise OfficeOperationError(f"{label} contains unsupported gradient content")
    children = list(gradient)
    if any(_qname(child).namespace != expected_namespace for child in children):
        raise OfficeOperationError(f"{label} mixes Strict and Transitional DrawingML")
    child_names = [_local_name(child) for child in children]
    if child_names not in (["gsLst", "lin"], ["gsLst", "path"]):
        raise OfficeOperationError(f"{label} supports only ordered linear gradient children or ordered radial path-gradient children")
    stop_list, geometry = children
    if stop_list.attrib or any(not isinstance(child.tag, str) for child in stop_list):
        raise OfficeOperationError(f"{label} contains unsupported gradient-stop-list metadata")

    stops = list(stop_list)
    if not 2 <= len(stops) <= _MAX_GRADIENT_STOPS:
        raise OfficeOperationError(f"{label} must contain between 2 and {_MAX_GRADIENT_STOPS} gradient stops")
    stop_records: list[tuple[int, str, int | None]] = []
    previous_position = -1
    for index, stop in enumerate(stops, start=1):
        stop_label = f"{label} stop {index}"
        if not isinstance(stop.tag, str) or _qname(stop).namespace != expected_namespace or _local_name(stop) != "gs":
            raise OfficeOperationError(f"{label} contains an unsupported gradient stop")
        if set(stop.attrib) != {"pos"}:
            raise OfficeOperationError(f"{stop_label} contains unsupported attributes")
        if any(not isinstance(child.tag, str) for child in stop):
            raise OfficeOperationError(f"{stop_label} contains unsupported content")
        position = _gradient_integer_attribute(
            stop,
            "pos",
            label=stop_label,
            minimum=0,
            maximum=100_000,
        )
        if position is None or position <= previous_position:
            raise OfficeOperationError(f"{label} stop positions must be strictly increasing")
        previous_position = position

        colors = list(stop)
        if len(colors) != 1 or _qname(colors[0]).namespace != expected_namespace or _local_name(colors[0]) != "srgbClr":
            raise OfficeOperationError(f"{stop_label} requires exactly one direct RGB color")
        color = colors[0]
        raw_color = color.get("val", "")
        if set(color.attrib) != {"val"} or len(raw_color) != 6 or any(character not in "0123456789abcdefABCDEF" for character in raw_color):
            raise OfficeOperationError(f"{stop_label} has an invalid RGB color")
        if any(not isinstance(child.tag, str) for child in color):
            raise OfficeOperationError(f"{stop_label} contains unsupported color content")
        transforms = list(color)
        if len(transforms) > 1:
            raise OfficeOperationError(f"{stop_label} contains unsupported color transforms")
        alpha_value = None
        if transforms:
            alpha = transforms[0]
            if _qname(alpha).namespace != expected_namespace or _local_name(alpha) != "alpha" or set(alpha.attrib) != {"val"} or len(alpha):
                raise OfficeOperationError(f"{stop_label} contains an unsupported color transform")
            alpha_value = _gradient_integer_attribute(
                alpha,
                "val",
                label=f"{stop_label} alpha",
                minimum=0,
                maximum=100_000,
            )
        stop_records.append((position, raw_color.upper(), alpha_value))

    if child_names[1] == "lin":
        if set(geometry.attrib) - {"ang", "scaled"} or len(geometry):
            raise OfficeOperationError(f"{label} contains unsupported linear-gradient metadata")
        angle = _gradient_integer_attribute(
            geometry,
            "ang",
            label=f"{label} linear geometry",
            minimum=0,
            maximum=21_599_999,
            required=False,
        )
        scaled = _gradient_boolean_attribute(
            geometry,
            "scaled",
            label=f"{label} linear geometry",
        )
        geometry_signature: tuple[Any, ...] = ("linear", angle, scaled)
    else:
        if set(geometry.attrib) != {"path"} or geometry.get("path") != "circle":
            raise OfficeOperationError(f"{label} supports only radial circle path geometry")
        if any(not isinstance(child.tag, str) for child in geometry):
            raise OfficeOperationError(f"{label} contains unsupported radial path content")
        path_children = list(geometry)
        if len(path_children) != 1 or _qname(path_children[0]).namespace != expected_namespace or _local_name(path_children[0]) != "fillToRect":
            raise OfficeOperationError(f"{label} requires exactly one radial fill rectangle")
        fill_rectangle = path_children[0]
        if set(fill_rectangle.attrib) != {"l", "t", "r", "b"} or len(fill_rectangle):
            raise OfficeOperationError(f"{label} contains unsupported radial fill-rectangle metadata")
        rectangle = tuple(
            _gradient_integer_attribute(
                fill_rectangle,
                attribute,
                label=f"{label} radial fill rectangle",
                minimum=0,
                maximum=100_000,
            )
            for attribute in ("l", "t", "r", "b")
        )
        if any(value is None for value in rectangle):
            raise OfficeOperationError(f"{label} has an incomplete radial fill rectangle")
        left, top, right, bottom = rectangle
        if left + right != 100_000 or top + bottom != 100_000:
            raise OfficeOperationError(f"{label} radial fill-rectangle edges must sum to 100 percent on each axis")
        geometry_signature = ("path", "circle", rectangle)
    return rotate_with_shape, tuple(stop_records), geometry_signature


def _requested_gradient_signature(
    formatting: PptxShapeFillFormatting,
) -> tuple[bool, tuple[tuple[int, str, int | None], ...], tuple[Any, ...]]:
    if formatting.type != "gradient" or formatting.stops is None or formatting.geometry is None or formatting.rotate_with_shape is None:
        raise OfficeOperationError("PPTX gradient formatting is incomplete")
    stops = tuple(
        (
            round(stop.position_percent * 1_000),
            stop.color.removeprefix("#").upper(),
            None if stop.opacity_percent is None else round(stop.opacity_percent * 1_000),
        )
        for stop in formatting.stops
    )
    if isinstance(formatting.geometry, PptxLinearGradientFormatting):
        geometry_signature: tuple[Any, ...] = (
            "linear",
            round(formatting.geometry.angle_degrees * 60_000),
            formatting.geometry.scaled,
        )
    elif isinstance(formatting.geometry, PptxPathGradientFormatting):
        rectangle = formatting.geometry.fill_to_rectangle
        geometry_signature = (
            "path",
            formatting.geometry.path,
            tuple(
                round(value * 1_000)
                for value in (
                    rectangle.left_percent,
                    rectangle.top_percent,
                    rectangle.right_percent,
                    rectangle.bottom_percent,
                )
            ),
        )
    else:
        raise OfficeOperationError("PPTX gradient geometry is unsupported")
    return formatting.rotate_with_shape, stops, geometry_signature


def _build_gradient_fill(
    parent: Any,
    formatting: PptxShapeFillFormatting,
) -> Any:
    rotate_with_shape, stops, geometry_signature = _requested_gradient_signature(formatting)
    gradient = _new_drawing_child(parent, "gradFill")
    gradient.set("rotWithShape", "1" if rotate_with_shape else "0")
    stop_list = _new_drawing_child(gradient, "gsLst")
    for position, color, opacity in stops:
        stop = _new_drawing_child(stop_list, "gs")
        stop.set("pos", str(position))
        rgb = _new_drawing_child(stop, "srgbClr")
        rgb.set("val", color)
        if opacity is not None:
            alpha = _new_drawing_child(rgb, "alpha")
            alpha.set("val", str(opacity))
            rgb.append(alpha)
        stop.append(rgb)
        stop_list.append(stop)
    gradient.append(stop_list)
    if geometry_signature[0] == "linear":
        _, angle, scaled = geometry_signature
        linear = _new_drawing_child(gradient, "lin")
        linear.set("ang", str(angle))
        linear.set("scaled", "1" if scaled else "0")
        gradient.append(linear)
    else:
        _, path_kind, rectangle = geometry_signature
        path_geometry = _new_drawing_child(gradient, "path")
        path_geometry.set("path", path_kind)
        fill_rectangle = _new_drawing_child(path_geometry, "fillToRect")
        for attribute, value in zip(
            ("l", "t", "r", "b"),
            rectangle,
            strict=True,
        ):
            fill_rectangle.set(attribute, str(value))
        path_geometry.append(fill_rectangle)
        gradient.append(path_geometry)
    return gradient


def _pattern_rgb_signature(
    color_slot: Any,
    *,
    expected_namespace: str,
    label: str,
) -> str:
    if color_slot.attrib or (color_slot.text or "").strip() or any(not isinstance(child.tag, str) for child in color_slot):
        raise OfficeOperationError(f"{label} contains unsupported color-slot metadata")
    colors = list(color_slot)
    if len(colors) != 1 or _qname(colors[0]).namespace != expected_namespace or _local_name(colors[0]) != "srgbClr":
        raise OfficeOperationError(f"{label} requires exactly one direct RGB color")
    color = colors[0]
    raw_color = color.get("val", "")
    if set(color.attrib) != {"val"} or len(raw_color) != 6 or any(character not in "0123456789abcdefABCDEF" for character in raw_color) or len(color) or (color.text or "").strip():
        raise OfficeOperationError(f"{label} has an unsupported direct RGB color")
    return raw_color.upper()


def _pattern_signature(
    pattern: Any,
    *,
    label: str,
) -> tuple[str, str, str]:
    expected_namespace = _drawing_namespace_for_context(pattern)
    preset = pattern.get("prst")
    if set(pattern.attrib) != {"prst"} or preset not in _PPTX_PATTERN_PRESETS:
        raise OfficeOperationError(f"{label} has an unsupported pattern preset")
    if (pattern.text or "").strip() or any(not isinstance(child.tag, str) for child in pattern):
        raise OfficeOperationError(f"{label} contains unsupported pattern content")
    children = list(pattern)
    if any(_qname(child).namespace != expected_namespace for child in children):
        raise OfficeOperationError(f"{label} mixes Strict and Transitional DrawingML")
    if [_local_name(child) for child in children] != ["fgClr", "bgClr"]:
        raise OfficeOperationError(f"{label} requires ordered foreground and background colors")
    foreground = _pattern_rgb_signature(
        children[0],
        expected_namespace=expected_namespace,
        label=f"{label} foreground",
    )
    background = _pattern_rgb_signature(
        children[1],
        expected_namespace=expected_namespace,
        label=f"{label} background",
    )
    return preset, foreground, background


def _requested_pattern_signature(
    formatting: PptxShapeFillFormatting,
) -> tuple[str, str, str]:
    if formatting.type != "pattern" or formatting.preset is None or formatting.foreground_color is None or formatting.background_color is None:
        raise OfficeOperationError("PPTX pattern formatting is incomplete")
    return (
        formatting.preset,
        formatting.foreground_color.removeprefix("#").upper(),
        formatting.background_color.removeprefix("#").upper(),
    )


def _build_pattern_fill(
    parent: Any,
    formatting: PptxShapeFillFormatting,
) -> Any:
    preset, foreground, background = _requested_pattern_signature(formatting)
    pattern = _new_drawing_child(parent, "pattFill")
    pattern.set("prst", preset)
    for child_name, color_value in (
        ("fgClr", foreground),
        ("bgClr", background),
    ):
        color_slot = _new_drawing_child(pattern, child_name)
        color = _new_drawing_child(color_slot, "srgbClr")
        color.set("val", color_value)
        color_slot.append(color)
        pattern.append(color_slot)
    return pattern


def _document_relationship_namespace_for_context(element: Any) -> str:
    root_namespace = _qname(element.getroottree().getroot()).namespace
    try:
        return _DOCUMENT_RELATIONSHIP_NAMESPACE_BY_PRESENTATION[root_namespace]
    except KeyError as exc:
        raise OfficeOperationError("PPTX image fill has no supported relationship namespace") from exc


def _requested_image_crop_signature(
    formatting: PptxShapeFillFormatting,
) -> tuple[int, int, int, int] | None:
    if formatting.type != "image" or formatting.image_path is None or formatting.rotate_with_shape is None:
        raise OfficeOperationError("PPTX image formatting is incomplete")
    if formatting.crop is None:
        return None
    return tuple(
        round(getattr(formatting.crop, field_name) * 1_000)
        for field_name in (
            "left_percent",
            "top_percent",
            "right_percent",
            "bottom_percent",
        )
    )


def _requested_image_framing_signature(
    formatting: PptxShapeFillFormatting,
) -> tuple[
    str,
    tuple[int | None, int | None, int, int, str, str] | None,
]:
    if formatting.type != "image" or formatting.image_path is None or formatting.rotate_with_shape is None:
        raise OfficeOperationError("PPTX image formatting is incomplete")
    mode = formatting.mode or "stretch"
    if mode == "stretch":
        return mode, None
    if mode == "center":
        return mode, (None, None, 100_000, 100_000, "ctr", "none")
    tile = formatting.tile
    if tile is None:
        raise OfficeOperationError("PPTX tile image formatting is incomplete")
    return mode, (
        tile.offset_x_emu,
        tile.offset_y_emu,
        round(tile.scale_x_percent * 1_000),
        round(tile.scale_y_percent * 1_000),
        _PPTX_TILE_ALIGNMENT_TO_XML[tile.alignment],
        _PPTX_TILE_FLIP_TO_XML[tile.flip],
    )


def _image_fill_signature(
    image_fill: Any,
    *,
    label: str,
) -> tuple[
    str,
    bool | None,
    tuple[int, int, int, int] | None,
    str,
    tuple[int | None, int | None, int, int, str, str] | None,
]:
    expected_drawing_namespace = _drawing_namespace_for_context(image_fill)
    expected_relationship_namespace = _document_relationship_namespace_for_context(image_fill)
    if set(image_fill.attrib) - {"rotWithShape"}:
        raise OfficeOperationError(f"{label} contains unsupported image-fill attributes")
    rotate_with_shape = _gradient_boolean_attribute(
        image_fill,
        "rotWithShape",
        label=label,
    )
    if any(not isinstance(child.tag, str) for child in image_fill):
        raise OfficeOperationError(f"{label} contains unsupported image-fill content")
    children = list(image_fill)
    if any(_qname(child).namespace != expected_drawing_namespace for child in children):
        raise OfficeOperationError(f"{label} mixes Strict and Transitional DrawingML")
    child_names = [_local_name(child) for child in children]
    if child_names not in (
        ["blip", "stretch"],
        ["blip", "srcRect", "stretch"],
        ["blip", "tile"],
    ):
        raise OfficeOperationError(f"{label} supports only ordered blip, optional stretch crop, and typed framing children")

    blip = children[0]
    expected_embed = str(etree.QName(expected_relationship_namespace, "embed"))
    if set(blip.attrib) != {expected_embed} or len(blip) or (blip.text or "").strip():
        raise OfficeOperationError(f"{label} requires one effect-free embedded image relationship")
    relationship_id = blip.get(expected_embed) or ""
    if not relationship_id or len(relationship_id) > _MAX_RELATIONSHIP_ID_CHARS:
        raise OfficeOperationError(f"{label} has an invalid embedded image relationship")

    crop_signature = None
    if len(children) == 3:
        source_rectangle = children[1]
        if set(source_rectangle.attrib) - {"l", "t", "r", "b"} or len(source_rectangle) or (source_rectangle.text or "").strip():
            raise OfficeOperationError(f"{label} has unsupported crop metadata")
        crop_values = tuple(
            _gradient_integer_attribute(
                source_rectangle,
                attribute,
                label=f"{label} crop",
                minimum=0,
                maximum=100_000,
                required=False,
            )
            or 0
            for attribute in ("l", "t", "r", "b")
        )
        if crop_values[0] + crop_values[2] >= 100_000 or crop_values[1] + crop_values[3] >= 100_000:
            raise OfficeOperationError(f"{label} crop removes the complete image area")
        if any(crop_values):
            crop_signature = crop_values

    framing = children[-1]
    if child_names[-1] == "stretch":
        if framing.attrib or (framing.text or "").strip() or any(not isinstance(child.tag, str) for child in framing):
            raise OfficeOperationError(f"{label} has unsupported stretch metadata")
        stretch_children = list(framing)
        if len(stretch_children) != 1 or _qname(stretch_children[0]).namespace != expected_drawing_namespace or _local_name(stretch_children[0]) != "fillRect":
            raise OfficeOperationError(f"{label} requires one stretch fill rectangle")
        fill_rectangle = stretch_children[0]
        if fill_rectangle.attrib or len(fill_rectangle) or (fill_rectangle.text or "").strip():
            raise OfficeOperationError(f"{label} does not support fill-rectangle tuning")
        return relationship_id, rotate_with_shape, crop_signature, "stretch", None

    if len(framing) or (framing.text or "").strip():
        raise OfficeOperationError(f"{label} has unsupported tile content")
    tile_attributes = set(framing.attrib)
    center_attributes = {"sx", "sy", "algn", "flip"}
    if tile_attributes == center_attributes:
        center_scale_x = _gradient_integer_attribute(
            framing,
            "sx",
            label=f"{label} center framing",
            minimum=100_000,
            maximum=100_000,
        )
        center_scale_y = _gradient_integer_attribute(
            framing,
            "sy",
            label=f"{label} center framing",
            minimum=100_000,
            maximum=100_000,
        )
        if framing.get("algn") == "ctr" and framing.get("flip") == "none":
            return (
                relationship_id,
                rotate_with_shape,
                None,
                "center",
                (None, None, center_scale_x, center_scale_y, "ctr", "none"),
            )
    expected_tile_attributes = {"tx", "ty", "sx", "sy", "algn", "flip"}
    if tile_attributes != expected_tile_attributes:
        raise OfficeOperationError(f"{label} requires explicit typed tile attributes")
    tile_signature = (
        _gradient_integer_attribute(
            framing,
            "tx",
            label=f"{label} tile framing",
            minimum=-2_147_483_648,
            maximum=2_147_483_647,
        ),
        _gradient_integer_attribute(
            framing,
            "ty",
            label=f"{label} tile framing",
            minimum=-2_147_483_648,
            maximum=2_147_483_647,
        ),
        _gradient_integer_attribute(
            framing,
            "sx",
            label=f"{label} tile framing",
            minimum=1_000,
            maximum=500_000,
        ),
        _gradient_integer_attribute(
            framing,
            "sy",
            label=f"{label} tile framing",
            minimum=1_000,
            maximum=500_000,
        ),
        framing.get("algn") or "",
        framing.get("flip") or "",
    )
    if tile_signature[4] not in _PPTX_TILE_ALIGNMENT_FROM_XML:
        raise OfficeOperationError(f"{label} has unsupported tile alignment")
    if tile_signature[5] not in _PPTX_TILE_FLIP_FROM_XML:
        raise OfficeOperationError(f"{label} has unsupported tile flip")
    return relationship_id, rotate_with_shape, None, "tile", tile_signature


def _build_image_fill(
    parent: Any,
    formatting: PptxShapeFillFormatting,
    *,
    relationship_id: str,
    emit_rotate_with_shape: bool = True,
) -> Any:
    crop_signature = _requested_image_crop_signature(formatting)
    mode, tile_signature = _requested_image_framing_signature(formatting)
    image_fill = _new_drawing_child(parent, "blipFill")
    if emit_rotate_with_shape:
        image_fill.set(
            "rotWithShape",
            "1" if formatting.rotate_with_shape else "0",
        )
    blip = _new_drawing_child(image_fill, "blip")
    blip.set(
        etree.QName(
            _document_relationship_namespace_for_context(parent),
            "embed",
        ),
        relationship_id,
    )
    image_fill.append(blip)
    if crop_signature is not None:
        source_rectangle = _new_drawing_child(image_fill, "srcRect")
        for attribute, value in zip(
            ("l", "t", "r", "b"),
            crop_signature,
            strict=True,
        ):
            source_rectangle.set(attribute, str(value))
        image_fill.append(source_rectangle)
    if mode == "stretch":
        stretch = _new_drawing_child(image_fill, "stretch")
        stretch.append(_new_drawing_child(stretch, "fillRect"))
        image_fill.append(stretch)
    else:
        if tile_signature is None:
            raise OfficeOperationError("PPTX image tile framing is incomplete")
        tile = _new_drawing_child(image_fill, "tile")
        offset_x, offset_y, scale_x, scale_y, alignment, flip = tile_signature
        if mode == "tile":
            if offset_x is None or offset_y is None:
                raise OfficeOperationError("PPTX image tile offsets are incomplete")
            tile.set("tx", str(offset_x))
            tile.set("ty", str(offset_y))
        tile.set("sx", str(scale_x))
        tile.set("sy", str(scale_y))
        tile.set("algn", alignment)
        tile.set("flip", flip)
        image_fill.append(tile)
    return image_fill


def _relationship_id_sort_key(relationship_id: str) -> tuple[int, int, str]:
    suffix = relationship_id[3:] if relationship_id.startswith("rId") else ""
    if suffix.isdigit():
        return 0, int(suffix), relationship_id
    return 1, 0, relationship_id


def _next_relationship_id(relationships: dict[str, _Relationship]) -> str:
    index = 1
    while f"rId{index}" in relationships:
        index += 1
    return f"rId{index}"


def _content_types_replacement_for_additions(
    data: bytes,
    package: _PackageInfo,
    required_content_types: dict[str, str],
) -> bytes | None:
    missing = {part_name: content_type for part_name, content_type in required_content_types.items() if package.content_types.for_part(part_name) != content_type}
    if not missing:
        return None
    with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
        root = _safe_xml_root(
            archive.read(_CONTENT_TYPES_XML),
            label=_CONTENT_TYPES_XML,
            limit=_MAX_CONTROL_XML_BYTES,
        )

    defaults_to_add: dict[str, str] = {}
    overrides_to_add: dict[str, str] = {}
    for part_name, content_type in sorted(missing.items()):
        extension = PurePosixPath(part_name).suffix.removeprefix(".").lower()
        if not extension:
            raise OfficeOperationError("PPTX added package part has no content-type extension")
        existing_default = package.content_types.defaults.get(extension)
        planned_default = defaults_to_add.get(extension)
        if existing_default is None and planned_default in {None, content_type}:
            defaults_to_add[extension] = content_type
        else:
            overrides_to_add[part_name] = content_type

    first_override = next(
        (index for index, child in enumerate(root) if isinstance(child.tag, str) and child.tag == f"{{{_CONTENT_TYPES_NS}}}Override"),
        len(root),
    )
    for extension, content_type in sorted(defaults_to_add.items()):
        element = etree.Element(etree.QName(_CONTENT_TYPES_NS, "Default"))
        element.set("Extension", extension)
        element.set("ContentType", content_type)
        root.insert(first_override, element)
        first_override += 1
    for part_name, content_type in sorted(overrides_to_add.items()):
        element = etree.Element(etree.QName(_CONTENT_TYPES_NS, "Override"))
        element.set("PartName", f"/{part_name}")
        element.set("ContentType", content_type)
        root.append(element)
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )


def _shape_image_mutation_request(
    target: _PptxFormattingTarget,
    formatting: PptxShapeFillFormatting,
) -> _PptxImageMutationRequest:
    if formatting.image_path is None or formatting.rotate_with_shape is None:
        raise OfficeOperationError("PPTX shape image formatting is incomplete")
    properties = _shape_properties(target.element)
    fills = _direct_fill_children(properties, _SHAPE_FILL_CHILDREN)
    mode, tile_signature = _requested_image_framing_signature(formatting)
    return _PptxImageMutationRequest(
        target_path=target.ref.path,
        slide=target.slide,
        context_element=target.element,
        current_fill=fills[0] if fills else None,
        image_path=formatting.image_path,
        rotate_with_shape=formatting.rotate_with_shape,
        normalize_missing_rotation=False,
        crop_signature=_requested_image_crop_signature(formatting),
        mode=mode,
        tile_signature=tile_signature,
        label="PPTX shape image fill",
    )


def _picture_image_mutation_request(
    target: _PptxFormattingTarget,
    operation: PptxPictureSourceReplacementOperation,
    package: _PackageInfo,
) -> _PptxPictureImageMutationRequest:
    binding = _picture_source_binding(
        target.element,
        slide=target.slide,
        package=package,
        label="PPTX picture replacement target",
        require_supported_content_type=True,
    )
    return _PptxPictureImageMutationRequest(
        target_path=target.ref.path,
        slide=target.slide,
        context_element=target.element,
        current_relationship_id=binding.relationship_id,
        image_path=operation.image_path,
        label="PPTX picture source",
    )


def _plan_pptx_image_mutations(
    data: bytes,
    package: _PackageInfo,
    requests: list[_PptxImageMutationRequest | _PptxPictureImageMutationRequest],
    image_assets: dict[str, bytes] | None,
) -> _PptxImageMutationPlan:
    required_paths = {request.image_path for request in requests}
    provided_assets = image_assets or {}
    if set(provided_assets) != required_paths:
        if required_paths - set(provided_assets):
            raise OfficeOperationError("PPTX image edit is missing a required image asset")
        raise OfficeOperationError("PPTX image edit received an unexpected image asset")
    if not requests:
        return _PptxImageMutationPlan(
            targets={},
            replacements={},
            additions={},
        )
    total_asset_bytes = sum(len(payload) for payload in provided_assets.values())
    if total_asset_bytes > _MAX_TOTAL_IMAGE_ASSET_BYTES:
        raise OfficeOperationError("PPTX image assets exceed the 20 MiB transaction limit")

    asset_specs: dict[str, _ValidatedImageAsset] = {}
    asset_keys: dict[str, tuple[str, str]] = {}
    payload_by_key: dict[tuple[str, str], bytes] = {}
    for path, payload in provided_assets.items():
        spec = _validate_image_asset_for_path(
            payload,
            path=path,
            label="PPTX image asset",
        )
        key = (spec.content_type, spec.digest)
        existing_payload = payload_by_key.setdefault(key, payload)
        if existing_payload != payload:
            raise OfficeOperationError("PPTX image assets produced an unexpected digest collision")
        asset_specs[path] = spec
        asset_keys[path] = key

    targets: dict[str, _PlannedImageFill] = {}
    replacements: dict[str, bytes] = {}
    additions: dict[str, bytes] = {}
    required_content_types: dict[str, str] = {}
    relationship_roots: dict[str, Any] = {}
    relationship_records: dict[str, dict[str, _Relationship]] = {}
    changed_relationship_parts: set[str] = set()
    used_part_names = {name.lower() for name in package.part_names}

    with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
        payload_cache: dict[str, bytes] = {}

        def part_payload(part_name: str) -> bytes:
            payload = payload_cache.get(part_name)
            if payload is None:
                payload = archive.read(part_name)
                payload_cache[part_name] = payload
            return payload

        requested_keys = set(asset_keys.values())
        parts_by_key: dict[tuple[str, str], list[str]] = {}
        for part_name in sorted(package.part_names):
            content_type = package.content_types.for_part(part_name)
            if content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
                continue
            if package.part_sizes[part_name] > _MAX_IMAGE_ASSET_BYTES:
                continue
            payload = part_payload(part_name)
            digest = hashlib.sha256(payload).hexdigest()
            key = (content_type, digest)
            if key not in requested_keys or payload != payload_by_key[key]:
                continue
            existing_spec = _validate_image_asset_for_content_type(
                payload,
                content_type=content_type,
                label="Existing PPTX image asset",
            )
            if existing_spec.digest != digest:
                raise OfficeOperationError("PPTX image asset digest changed during validation")
            parts_by_key.setdefault(key, []).append(part_name)

        part_for_key = {key: part_names[0] for key, part_names in parts_by_key.items()}

        def new_media_part(
            payload: bytes,
            spec: _ValidatedImageAsset,
            key: tuple[str, str],
        ) -> str:
            index = 1
            while any(name.startswith(f"ppt/media/image{index}.") for name in used_part_names):
                index += 1
            part_name = f"ppt/media/image{index}{spec.extension}"
            used_part_names.add(part_name.lower())
            additions[part_name] = payload
            required_content_types[part_name] = spec.content_type
            part_for_key[key] = part_name
            return part_name

        def resolve_current_image(
            request: _PptxImageMutationRequest | _PptxPictureImageMutationRequest,
            relationship_id: str,
        ) -> tuple[str, tuple[str, str]]:
            relationship = request.slide.relationships.get(relationship_id)
            relationship_namespace = _document_relationship_namespace_for_context(request.context_element)
            if relationship is None or relationship.external or relationship.relationship_type != f"{relationship_namespace}/image":
                raise OfficeOperationError(f"{request.label} has an invalid embedded image relationship")
            part_name = _resolve_relationship_target(
                request.slide.part_name,
                relationship.target,
            )
            content_type = package.content_types.for_part(part_name)
            if content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
                raise OfficeOperationError(f"{request.label} does not resolve to a supported embedded image part")
            if isinstance(request, _PptxPictureImageMutationRequest):
                digest = package.part_sha256.get(part_name)
                if digest is None:
                    raise OfficeOperationError(f"{request.label} image source digest is unavailable")
                return part_name, (content_type, digest)
            payload = part_payload(part_name)
            spec = _validate_image_asset_for_content_type(
                payload,
                content_type=content_type,
                label=f"Existing {request.label}",
            )
            return part_name, (spec.content_type, spec.digest)

        def relationships_for_slide(
            slide: _Slide,
        ) -> dict[str, _Relationship]:
            return relationship_records.setdefault(
                slide.part_name,
                dict(slide.relationships),
            )

        def add_image_relationship(
            request: _PptxImageMutationRequest | _PptxPictureImageMutationRequest,
            part_name: str,
        ) -> str:
            records = relationships_for_slide(request.slide)
            relationship_namespace = _document_relationship_namespace_for_context(request.context_element)
            relationship_type = f"{relationship_namespace}/image"
            matches = [
                relationship.relationship_id
                for relationship in records.values()
                if not relationship.external
                and relationship.relationship_type == relationship_type
                and _resolve_relationship_target(
                    request.slide.part_name,
                    relationship.target,
                )
                == part_name
            ]
            if matches:
                return min(matches, key=_relationship_id_sort_key)

            relationship_part = _relationship_part_name(request.slide.part_name)
            root = relationship_roots.get(relationship_part)
            if root is None:
                if relationship_part in package.part_names:
                    root = _safe_xml_root(
                        archive.read(relationship_part),
                        label=relationship_part,
                        limit=_MAX_CONTROL_XML_BYTES,
                    )
                else:
                    root = etree.Element(
                        etree.QName(
                            _PACKAGE_RELATIONSHIPS_NS,
                            "Relationships",
                        ),
                        nsmap={None: _PACKAGE_RELATIONSHIPS_NS},
                    )
                    required_content_types[relationship_part] = _RELATIONSHIPS_CONTENT_TYPE
                relationship_roots[relationship_part] = root
            relationship_id = _next_relationship_id(records)
            target_path = posixpath.relpath(
                part_name,
                posixpath.dirname(request.slide.part_name),
            )
            element = etree.SubElement(
                root,
                etree.QName(
                    _PACKAGE_RELATIONSHIPS_NS,
                    "Relationship",
                ),
            )
            element.set("Id", relationship_id)
            element.set("Type", relationship_type)
            element.set("Target", target_path)
            records[relationship_id] = _Relationship(
                relationship_id=relationship_id,
                relationship_type=relationship_type,
                target=target_path,
                external=False,
            )
            changed_relationship_parts.add(relationship_part)
            return relationship_id

        for request in requests:
            image_path = request.image_path
            requested_spec = asset_specs[image_path]
            requested_key = asset_keys[image_path]
            requested_payload = provided_assets[image_path]
            current_relationship_id = None
            current_part = None
            current_key = None
            if isinstance(request, _PptxPictureImageMutationRequest):
                current_relationship_id = request.current_relationship_id
                current_part, current_key = resolve_current_image(
                    request,
                    current_relationship_id,
                )
                if current_key == requested_key:
                    targets[request.target_path] = _PlannedImageFill(
                        relationship_id=current_relationship_id,
                    )
                    continue
            elif request.current_fill is not None and _local_name(request.current_fill) == "blipFill":
                (
                    current_relationship_id,
                    current_rotate_with_shape,
                    current_crop,
                    current_mode,
                    current_tile,
                ) = _image_fill_signature(
                    request.current_fill,
                    label=request.label,
                )
                current_part, current_key = resolve_current_image(
                    request,
                    current_relationship_id,
                )
                normalized_rotation = False if request.normalize_missing_rotation and current_rotate_with_shape is None else current_rotate_with_shape
                if current_key == requested_key and normalized_rotation is request.rotate_with_shape and current_crop == request.crop_signature and current_mode == request.mode and current_tile == request.tile_signature:
                    targets[request.target_path] = _PlannedImageFill(
                        relationship_id=current_relationship_id,
                    )
                    continue

            if current_key == requested_key and current_part is not None:
                image_part = current_part
            else:
                image_part = part_for_key.get(requested_key)
                if image_part is None:
                    image_part = new_media_part(
                        requested_payload,
                        requested_spec,
                        requested_key,
                    )

            relationship_id = None
            if current_relationship_id is not None and current_part == image_part:
                relationship_id = current_relationship_id
            if relationship_id is None:
                relationship_id = add_image_relationship(
                    request,
                    image_part,
                )
            targets[request.target_path] = _PlannedImageFill(
                relationship_id=relationship_id,
            )

        for relationship_part in sorted(changed_relationship_parts):
            payload = etree.tostring(
                relationship_roots[relationship_part],
                encoding="UTF-8",
                xml_declaration=True,
                pretty_print=False,
            )
            if relationship_part in package.part_names:
                replacements[relationship_part] = payload
            else:
                additions[relationship_part] = payload

    content_types_payload = _content_types_replacement_for_additions(
        data,
        package,
        required_content_types,
    )
    if content_types_payload is not None:
        replacements[_CONTENT_TYPES_XML] = content_types_payload
    return _PptxImageMutationPlan(
        targets=targets,
        replacements=replacements,
        additions=additions,
    )


def _preflight_direct_fill(
    parent: Any,
    formatting: PptxShapeFillFormatting,
    *,
    fill_names: frozenset[str],
    label: str,
) -> None:
    fills = _require_supported_direct_fill(
        parent,
        fill_names,
        label=label,
        allow_gradient=formatting.type == "gradient",
        allow_pattern=formatting.type == "pattern",
        allow_image=formatting.type == "image",
    )
    if formatting.type == "solid" and fills and _local_name(fills[0]) == "solidFill":
        _require_supported_solid_fill_color(
            fills[0],
            label=f"{label} solid fill",
        )
    if formatting.type == "gradient" and fills and _local_name(fills[0]) == "gradFill":
        _gradient_signature(
            fills[0],
            label=f"{label} gradient fill",
        )
    if formatting.type == "pattern" and fills and _local_name(fills[0]) == "pattFill":
        _pattern_signature(
            fills[0],
            label=f"{label} pattern fill",
        )
    if formatting.type == "image" and fills and _local_name(fills[0]) == "blipFill":
        _image_fill_signature(
            fills[0],
            label=f"{label} image fill",
        )


def _set_direct_fill(
    parent: Any,
    formatting: PptxShapeFillFormatting,
    *,
    fill_names: frozenset[str],
    ranks: dict[str, int],
    label: str,
    image_relationship_id: str | None = None,
) -> None:
    fills = _require_supported_direct_fill(
        parent,
        fill_names,
        label=label,
        allow_gradient=formatting.type == "gradient",
        allow_pattern=formatting.type == "pattern",
        allow_image=formatting.type == "image",
    )
    current = fills[0] if fills else None
    if formatting.type == "none":
        if current is not None and _local_name(current) == "noFill":
            return
        _remove_drawing_children(parent, fill_names)
        no_fill = _new_drawing_child(parent, "noFill")
        _insert_ordered_drawing_child(parent, no_fill, ranks)
        return

    if formatting.type == "gradient":
        requested_signature = _requested_gradient_signature(formatting)
        if current is not None and _local_name(current) == "gradFill":
            current_signature = _gradient_signature(
                current,
                label=f"{label} gradient fill",
            )
            if current_signature == requested_signature:
                return
        gradient = _build_gradient_fill(parent, formatting)
        _remove_drawing_children(parent, fill_names)
        _insert_ordered_drawing_child(parent, gradient, ranks)
        return

    if formatting.type == "pattern":
        requested_signature = _requested_pattern_signature(formatting)
        if current is not None and _local_name(current) == "pattFill":
            current_signature = _pattern_signature(
                current,
                label=f"{label} pattern fill",
            )
            if current_signature == requested_signature:
                return
        pattern = _build_pattern_fill(parent, formatting)
        _remove_drawing_children(parent, fill_names)
        _insert_ordered_drawing_child(parent, pattern, ranks)
        return

    if formatting.type == "image":
        if image_relationship_id is None:
            raise OfficeOperationError("PPTX image formatting has no embedded image relationship")
        requested_signature = (
            image_relationship_id,
            formatting.rotate_with_shape,
            _requested_image_crop_signature(formatting),
            *_requested_image_framing_signature(formatting),
        )
        if current is not None and _local_name(current) == "blipFill":
            current_signature = _image_fill_signature(
                current,
                label=f"{label} image fill",
            )
            if current_signature == requested_signature:
                return
        image_fill = _build_image_fill(
            parent,
            formatting,
            relationship_id=image_relationship_id,
        )
        _remove_drawing_children(parent, fill_names)
        _insert_ordered_drawing_child(parent, image_fill, ranks)
        return

    if current is None or _local_name(current) == "noFill":
        _remove_drawing_children(parent, fill_names)
        solid_fill = _new_drawing_child(parent, "solidFill")
        _insert_ordered_drawing_child(parent, solid_fill, ranks)
    else:
        solid_fill = current
    _set_solid_fill_color(
        solid_fill,
        formatting.color or "",
        label=f"{label} solid fill",
    )


def _slide_background_shape_fill(
    formatting: PptxSlideBackgroundFormatting,
) -> PptxShapeFillFormatting:
    if formatting.type == "none":
        return PptxShapeFillFormatting(type="none")
    if formatting.type == "solid":
        return PptxShapeFillFormatting(
            type="solid",
            color=formatting.color,
        )
    if formatting.type == "gradient":
        return PptxShapeFillFormatting(
            type="gradient",
            stops=formatting.stops,
            geometry=formatting.geometry,
            rotate_with_shape=False,
        )
    return PptxShapeFillFormatting(
        type="image",
        image_path=formatting.image_path,
        rotate_with_shape=False,
        mode=formatting.mode,
        tile=formatting.tile,
    )


def _direct_slide_background_parts(
    target: _PptxSlideFormattingTarget,
) -> tuple[Any | None, Any | None, Any | None]:
    common_slide_data = target.element
    presentation_namespace = _qname(common_slide_data).namespace
    backgrounds = _children(common_slide_data, "bg")
    if any(_qname(background).namespace != presentation_namespace for background in backgrounds):
        raise OfficeOperationError("PPTX slide background mixes presentation namespaces")
    if len(backgrounds) > 1:
        raise OfficeOperationError("PPTX slide contains multiple direct backgrounds")
    if not backgrounds:
        return None, None, None

    background = backgrounds[0]
    if background.attrib or any(not isinstance(child.tag, str) for child in background):
        raise OfficeOperationError("PPTX slide background contains unsupported metadata")
    children = list(background)
    if len(children) != 1 or _qname(children[0]).namespace != presentation_namespace:
        raise OfficeOperationError("PPTX slide background must contain exactly one direct background definition")
    if _local_name(children[0]) == "bgRef":
        raise OfficeOperationError("PPTX theme-reference backgrounds are read-only")
    if _local_name(children[0]) != "bgPr":
        raise OfficeOperationError("PPTX slide background contains an unsupported definition")

    properties = children[0]
    if set(properties.attrib) - {"shadeToTitle"}:
        raise OfficeOperationError("PPTX slide background properties contain unsupported attributes")
    shade_to_title = _gradient_boolean_attribute(
        properties,
        "shadeToTitle",
        label="PPTX slide background properties",
    )
    if shade_to_title is True:
        raise OfficeOperationError("PPTX shade-to-title backgrounds are read-only")
    if any(not isinstance(child.tag, str) for child in properties):
        raise OfficeOperationError("PPTX slide background properties contain unsupported content")
    children = list(properties)
    drawing_namespace = _drawing_namespace_for_context(properties)
    if any(_qname(child).namespace != drawing_namespace for child in children):
        raise OfficeOperationError("PPTX slide background properties mix drawing namespaces")
    if len(children) == 2:
        effects = children[1]
        if _local_name(effects) != "effectLst" or effects.attrib or len(effects):
            raise OfficeOperationError("PPTX slide background effects are read-only")
    elif len(children) != 1:
        raise OfficeOperationError("PPTX slide background requires one direct fill and no authored effects")
    fill = children[0]
    fill_name = _local_name(fill)
    if fill_name not in {"noFill", "solidFill", "gradFill", "blipFill"}:
        raise OfficeOperationError("PPTX slide background fill is read-only")
    if fill_name == "solidFill":
        _require_supported_solid_fill_color(
            fill,
            label="PPTX slide background solid fill",
        )
    elif fill_name == "gradFill":
        _rotate, _stops, geometry = _gradient_signature(
            fill,
            label="PPTX slide background gradient fill",
        )
        if geometry[0] != "linear":
            raise OfficeOperationError("PPTX path-gradient slide backgrounds are read-only")
    elif fill_name == "blipFill":
        relationship_id, _rotate, _crop, _mode, _tile = _image_fill_signature(
            fill,
            label="PPTX slide background image fill",
        )
        relationship_namespace = _document_relationship_namespace_for_context(common_slide_data)
        relationship = target.slide.relationships.get(relationship_id)
        if relationship is None or relationship.external or relationship.relationship_type != f"{relationship_namespace}/image":
            raise OfficeOperationError("PPTX slide background image has an invalid embedded relationship")
    return background, properties, fill


def _preflight_pptx_slide_background(
    target: _PptxSlideFormattingTarget,
) -> None:
    name = _qname(target.element)
    if name.localname != "cSld" or name.namespace not in _PRESENTATION_NAMESPACES:
        raise OfficeOperationError("PPTX slide background formatting targets slides only")
    shape_trees = _children(target.element, "spTree")
    if len(shape_trees) != 1 or _qname(shape_trees[0]).namespace != name.namespace:
        raise OfficeOperationError("PPTX slide background formatting requires one shape tree")
    _direct_slide_background_parts(target)


def _slide_background_matches(
    target: _PptxSlideFormattingTarget,
    formatting: PptxSlideBackgroundFormatting,
    *,
    image_relationship_id: str | None,
) -> bool:
    background, _properties, fill = _direct_slide_background_parts(target)
    if formatting.type == "none":
        return background is None
    if fill is None:
        return False
    shape_fill = _slide_background_shape_fill(formatting)
    if formatting.type == "solid":
        if _local_name(fill) != "solidFill":
            return False
        colors = _require_supported_solid_fill_color(
            fill,
            label="PPTX slide background solid fill",
        )
        return len(colors) == 1 and _local_name(colors[0]) == "srgbClr" and set(colors[0].attrib) == {"val"} and not len(colors[0]) and colors[0].get("val", "").upper() == (formatting.color or "").removeprefix("#").upper()
    if formatting.type == "gradient":
        if _local_name(fill) != "gradFill":
            return False
        current_rotate, stops, geometry = _gradient_signature(
            fill,
            label="PPTX slide background gradient fill",
        )
        current_signature = (
            False if current_rotate is None else current_rotate,
            stops,
            geometry,
        )
        return current_signature == _requested_gradient_signature(shape_fill)
    if _local_name(fill) != "blipFill" or image_relationship_id is None:
        return False
    current_relationship, current_rotate, current_crop, current_mode, current_tile = _image_fill_signature(
        fill,
        label="PPTX slide background image fill",
    )
    requested_mode, requested_tile = _requested_image_framing_signature(shape_fill)
    return current_relationship == image_relationship_id and (False if current_rotate is None else current_rotate) is False and current_crop is None and current_mode == requested_mode and current_tile == requested_tile


def _background_image_mutation_request(
    target: _PptxSlideFormattingTarget,
    formatting: PptxSlideBackgroundFormatting,
) -> _PptxImageMutationRequest:
    shape_fill = _slide_background_shape_fill(formatting)
    if shape_fill.image_path is None:
        raise OfficeOperationError("PPTX slide background image formatting is incomplete")
    _background, _properties, current_fill = _direct_slide_background_parts(target)
    mode, tile_signature = _requested_image_framing_signature(shape_fill)
    return _PptxImageMutationRequest(
        target_path=target.path,
        slide=target.slide,
        context_element=target.element,
        current_fill=current_fill,
        image_path=shape_fill.image_path,
        rotate_with_shape=False,
        normalize_missing_rotation=True,
        crop_signature=None,
        mode=mode,
        tile_signature=tile_signature,
        label="PPTX slide background image fill",
    )


def _apply_pptx_slide_background(
    target: _PptxSlideFormattingTarget,
    formatting: PptxSlideBackgroundFormatting,
    *,
    image_relationship_id: str | None = None,
) -> bool:
    if _slide_background_matches(
        target,
        formatting,
        image_relationship_id=image_relationship_id,
    ):
        return False

    common_slide_data = target.element
    background, _properties, _fill = _direct_slide_background_parts(target)
    if formatting.type == "none":
        if background is not None:
            common_slide_data.remove(background)
        return background is not None

    presentation_namespace = _qname(common_slide_data).namespace
    new_background = etree.Element(etree.QName(presentation_namespace, "bg"))
    new_properties = etree.SubElement(
        new_background,
        etree.QName(presentation_namespace, "bgPr"),
    )
    shape_fill = _slide_background_shape_fill(formatting)
    if formatting.type == "solid":
        new_fill = _new_drawing_child(new_properties, "solidFill")
        _set_solid_fill_color(
            new_fill,
            formatting.color or "",
            label="PPTX slide background solid fill",
        )
    elif formatting.type == "gradient":
        new_fill = _build_gradient_fill(new_properties, shape_fill)
    else:
        if image_relationship_id is None:
            raise OfficeOperationError("PPTX slide background image has no embedded relationship")
        new_fill = _build_image_fill(
            new_properties,
            shape_fill,
            relationship_id=image_relationship_id,
            emit_rotate_with_shape=False,
        )
    new_properties.append(new_fill)

    if background is not None:
        common_slide_data.remove(background)
    shape_tree = _children(common_slide_data, "spTree")[0]
    common_slide_data.insert(
        common_slide_data.index(shape_tree),
        new_background,
    )
    return True


def _apply_pptx_picture_source(
    target: _PptxFormattingTarget,
    package: _PackageInfo,
    *,
    image_relationship_id: str,
) -> bool:
    binding = _picture_source_binding(
        target.element,
        slide=target.slide,
        package=package,
        label="PPTX picture replacement target",
        require_supported_content_type=True,
    )
    if binding.relationship_id == image_relationship_id:
        return False
    binding.blip.set(binding.embed_attribute, image_relationship_id)
    return True


def _shape_properties(shape: Any) -> Any:
    shape_namespace = _qname(shape).namespace
    properties = [child for child in shape if isinstance(child.tag, str) and _local_name(child) == "spPr" and _qname(child).namespace == shape_namespace]
    if len(properties) != 1:
        raise OfficeOperationError("PPTX shape formatting requires exactly one shape-properties element")
    return properties[0]


def _preflight_pptx_preset_geometry(
    properties: Any,
) -> Any:
    geometries = [child for child in _drawing_children(properties) if _local_name(child) in {"prstGeom", "custGeom"}]
    if len(geometries) != 1:
        raise OfficeOperationError("PPTX preset geometry formatting requires exactly one direct geometry")
    geometry = geometries[0]
    if _local_name(geometry) != "prstGeom":
        raise OfficeOperationError("PPTX preset geometry formatting cannot replace custom geometry")
    preset = geometry.get("prst")
    if set(geometry.attrib) != {"prst"} or preset is None or not 1 <= len(preset) <= 100 or not preset.isascii() or not preset.isalnum():
        raise OfficeOperationError("PPTX preset geometry contains unsupported metadata")
    if any(not isinstance(child.tag, str) for child in geometry):
        raise OfficeOperationError("PPTX preset geometry contains unsupported content")
    children = list(geometry)
    expected_namespace = _drawing_namespace_for_context(geometry)
    if children:
        if len(children) != 1 or _qname(children[0]).namespace != expected_namespace or _local_name(children[0]) != "avLst":
            raise OfficeOperationError("PPTX preset geometry contains unsupported child elements")
        adjustment_list = children[0]
        if adjustment_list.attrib or len(adjustment_list):
            raise OfficeOperationError("PPTX preset geometry with authored adjustments is not writable")
    return geometry


def _set_pptx_preset_geometry(
    properties: Any,
    formatting: PptxPresetGeometryFormatting,
) -> None:
    geometry = _preflight_pptx_preset_geometry(properties)
    if geometry.get("prst") != formatting.preset:
        geometry.set("prst", formatting.preset)


def _line_owner_properties(owner: Any) -> Any:
    owner_namespace = _qname(owner).namespace
    properties = [child for child in owner if isinstance(child.tag, str) and _local_name(child) == "spPr" and _qname(child).namespace == owner_namespace]
    if len(properties) != 1:
        raise OfficeOperationError("PPTX line formatting requires exactly one shape-properties element")
    return properties[0]


def _text_box_body_properties(shape: Any) -> Any:
    shape_namespace = _qname(shape).namespace
    text_bodies = [child for child in shape if isinstance(child.tag, str) and _local_name(child) == "txBody" and _qname(child).namespace == shape_namespace]
    if len(text_bodies) != 1:
        raise OfficeOperationError("PPTX text-box formatting requires exactly one text body")
    drawing_namespace = _drawing_namespace_for_context(shape)
    body_properties = [child for child in text_bodies[0] if isinstance(child.tag, str) and _local_name(child) == "bodyPr" and _qname(child).namespace == drawing_namespace]
    if len(body_properties) != 1:
        raise OfficeOperationError("PPTX text-box formatting requires exactly one body-properties element")
    return body_properties[0]


def _shape_line(properties: Any, *, create: bool) -> Any | None:
    lines = _drawing_children(properties, "ln")
    if len(lines) > 1:
        raise OfficeOperationError("PPTX shape properties contain multiple direct lines")
    if lines:
        return lines[0]
    if not create:
        return None
    line = _new_drawing_child(properties, "ln")
    _insert_ordered_drawing_child(
        properties,
        line,
        _SHAPE_PROPERTY_CHILD_RANK,
    )
    return line


def _line_choice_children(line: Any, names: frozenset[str]) -> list[Any]:
    return [child for child in _drawing_children(line) if _local_name(child) in names]


def _preflight_pptx_line_style(line: Any) -> None:
    raw_width = line.get("w")
    if raw_width is not None:
        try:
            width = int(raw_width)
        except ValueError as exc:
            raise OfficeOperationError("PPTX line width is invalid") from exc
        if not 0 <= width <= 100_000_000:
            raise OfficeOperationError("PPTX line width is out of range")
    for attribute, values, label in (
        ("cap", _LINE_CAP_FROM_OOXML, "cap"),
        ("cmpd", _LINE_COMPOUND_FROM_OOXML, "compound"),
        ("algn", _LINE_ALIGNMENT_FROM_OOXML, "alignment"),
    ):
        value = line.get(attribute)
        if value is not None and value not in values:
            raise OfficeOperationError(f"PPTX line {label} is invalid")
    dashes = _line_choice_children(line, _LINE_DASH_CHILDREN)
    if len(dashes) > 1:
        raise OfficeOperationError("PPTX line properties contain multiple dash choices")
    if dashes and _local_name(dashes[0]) == "prstDash" and dashes[0].get("val") not in _LINE_DASH_FROM_OOXML:
        raise OfficeOperationError("PPTX preset line dash is invalid")
    joins = _line_choice_children(line, _LINE_JOIN_CHILDREN)
    if len(joins) > 1:
        raise OfficeOperationError("PPTX line properties contain multiple join choices")
    if joins and _local_name(joins[0]) == "miter":
        raw_limit = joins[0].get("lim")
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except ValueError as exc:
                raise OfficeOperationError("PPTX line miter limit is invalid") from exc
            if not 0 <= limit <= 2_147_483_647:
                raise OfficeOperationError("PPTX line miter limit is out of range")
    for child_name in _LINE_END_CHILDREN:
        line_ends = _drawing_children(line, child_name)
        if len(line_ends) > 1:
            raise OfficeOperationError(f"PPTX line properties contain multiple {child_name} elements")
        if not line_ends:
            continue
        line_end = line_ends[0]
        if any(isinstance(child.tag, str) for child in line_end):
            raise OfficeOperationError(f"PPTX {child_name} contains unsupported child elements")
        for attribute, values, label in (
            ("type", _LINE_END_TYPE_FROM_OOXML, "type"),
            ("w", _LINE_END_SIZE_FROM_OOXML, "width"),
            ("len", _LINE_END_SIZE_FROM_OOXML, "length"),
        ):
            value = line_end.get(attribute)
            if value is not None and value not in values:
                raise OfficeOperationError(f"PPTX {child_name} {label} is invalid")


def _preflight_pptx_shape_formatting(
    target: _PptxFormattingTarget,
    formatting: PptxShapeFormatting,
) -> None:
    shape = target.element
    shape_name = _qname(shape)
    if shape_name.localname != "sp" or shape_name.namespace not in _PRESENTATION_NAMESPACES:
        raise OfficeOperationError("PPTX shape formatting targets authored shapes only")

    properties = None
    if formatting.fill is not None or formatting.geometry is not None or formatting.line is not None:
        properties = _shape_properties(shape)
        _require_consistent_drawing_children(
            properties,
            _SHAPE_PROPERTY_CHILD_RANK,
            label="PPTX shape properties",
        )
        _require_supported_child_order(
            properties,
            _SHAPE_PROPERTY_CHILD_RANK,
            label="PPTX shape properties",
        )
    if formatting.geometry is not None:
        _preflight_pptx_preset_geometry(
            properties,
        )
    if formatting.fill is not None:
        _preflight_direct_fill(
            properties,
            formatting.fill,
            fill_names=_SHAPE_FILL_CHILDREN,
            label="PPTX shape fill",
        )
    if formatting.line is not None:
        line = _shape_line(properties, create=False)
        if line is None and formatting.line.fill is None:
            raise OfficeOperationError("PPTX line width cannot create an implicit line; provide line.fill in the same operation")
        if line is not None:
            _require_consistent_drawing_children(
                line,
                _LINE_PROPERTY_CHILD_RANK,
                label="PPTX line properties",
            )
            _require_supported_child_order(
                line,
                _LINE_PROPERTY_CHILD_RANK,
                label="PPTX line properties",
            )
            _preflight_pptx_line_style(line)
            if formatting.line.fill is not None:
                _preflight_direct_fill(
                    line,
                    formatting.line.fill,
                    fill_names=_LINE_FILL_CHILDREN,
                    label="PPTX line fill",
                )
    if formatting.text_box is not None:
        _text_box_body_properties(shape)


def _preflight_pptx_line_formatting(
    target: _PptxFormattingTarget,
    formatting: PptxLineFormatting,
) -> None:
    owner = target.element
    owner_name = _qname(owner)
    if owner_name.localname not in {"sp", "cxnSp"} or owner_name.namespace not in _PRESENTATION_NAMESPACES:
        raise OfficeOperationError("PPTX line formatting targets authored shapes or connectors only")

    properties = _line_owner_properties(owner)
    _require_consistent_drawing_children(
        properties,
        _SHAPE_PROPERTY_CHILD_RANK,
        label="PPTX shape properties",
    )
    _require_supported_child_order(
        properties,
        _SHAPE_PROPERTY_CHILD_RANK,
        label="PPTX shape properties",
    )
    line = _shape_line(properties, create=False)
    if line is None and formatting.fill is None:
        raise OfficeOperationError("PPTX line formatting cannot create an implicit line; provide fill in the same operation")
    if line is not None:
        _require_consistent_drawing_children(
            line,
            _LINE_PROPERTY_CHILD_RANK,
            label="PPTX line properties",
        )
        _require_supported_child_order(
            line,
            _LINE_PROPERTY_CHILD_RANK,
            label="PPTX line properties",
        )
        _preflight_pptx_line_style(line)
        if formatting.fill is not None:
            _preflight_direct_fill(
                line,
                formatting.fill,
                fill_names=_LINE_FILL_CHILDREN,
                label="PPTX line fill",
            )
    for child_name, line_end in (
        ("headEnd", formatting.head_end),
        ("tailEnd", formatting.tail_end),
    ):
        if line_end is None or line_end.type is not None:
            continue
        existing = [] if line is None else _drawing_children(line, child_name)
        if not existing:
            raise OfficeOperationError(f"PPTX {child_name} size formatting requires an existing line end or an explicit type")


def _set_pptx_line_dash(line: Any, dash: str) -> None:
    dashes = _line_choice_children(line, _LINE_DASH_CHILDREN)
    wire_value = _LINE_DASH_TO_OOXML[dash]
    if dashes and _local_name(dashes[0]) == "prstDash":
        dashes[0].set("val", wire_value)
        return
    _remove_drawing_children(line, _LINE_DASH_CHILDREN)
    preset_dash = _new_drawing_child(line, "prstDash")
    preset_dash.set("val", wire_value)
    _insert_ordered_drawing_child(
        line,
        preset_dash,
        _LINE_PROPERTY_CHILD_RANK,
    )


def _set_pptx_line_join(
    line: Any,
    join: str,
    *,
    miter_limit_percent: float | None,
) -> None:
    joins = _line_choice_children(line, _LINE_JOIN_CHILDREN)
    current = joins[0] if joins else None
    if current is not None and _local_name(current) == join:
        if join == "miter" and miter_limit_percent is not None:
            current.set("lim", str(round(miter_limit_percent * 1_000)))
        return
    _remove_drawing_children(line, _LINE_JOIN_CHILDREN)
    join_element = _new_drawing_child(line, join)
    if join == "miter" and miter_limit_percent is not None:
        join_element.set("lim", str(round(miter_limit_percent * 1_000)))
    _insert_ordered_drawing_child(
        line,
        join_element,
        _LINE_PROPERTY_CHILD_RANK,
    )


def _set_pptx_line_end(
    line: Any,
    child_name: str,
    formatting: PptxLineEndFormatting,
) -> None:
    line_ends = _drawing_children(line, child_name)
    if len(line_ends) > 1:
        raise OfficeOperationError(f"PPTX line properties contain multiple {child_name} elements")
    if line_ends:
        line_end = line_ends[0]
    else:
        line_end = _new_drawing_child(line, child_name)
        _insert_ordered_drawing_child(
            line,
            line_end,
            _LINE_PROPERTY_CHILD_RANK,
        )
    if formatting.type is not None:
        line_end.set("type", _LINE_END_TYPE_TO_OOXML[formatting.type])
        if formatting.type == "none":
            line_end.attrib.pop("w", None)
            line_end.attrib.pop("len", None)
    if formatting.width is not None:
        line_end.set("w", _LINE_END_SIZE_TO_OOXML[formatting.width])
    if formatting.length is not None:
        line_end.set("len", _LINE_END_SIZE_TO_OOXML[formatting.length])


def _apply_pptx_direct_line_formatting(
    line: Any,
    formatting: PptxShapeLineFormatting | PptxLineFormatting,
) -> None:
    if formatting.fill is not None:
        _set_direct_fill(
            line,
            formatting.fill,
            fill_names=_LINE_FILL_CHILDREN,
            ranks=_LINE_PROPERTY_CHILD_RANK,
            label="PPTX line fill",
        )
    if formatting.width_points is not None:
        line.set("w", str(round(formatting.width_points * 12_700)))
    if formatting.cap is not None:
        line.set("cap", _LINE_CAP_TO_OOXML[formatting.cap])
    if formatting.dash is not None:
        _set_pptx_line_dash(line, formatting.dash)
    if formatting.join is not None:
        _set_pptx_line_join(
            line,
            formatting.join,
            miter_limit_percent=formatting.miter_limit_percent,
        )
    if isinstance(formatting, PptxLineFormatting):
        if formatting.compound is not None:
            line.set("cmpd", _LINE_COMPOUND_TO_OOXML[formatting.compound])
        if formatting.alignment is not None:
            line.set("algn", _LINE_ALIGNMENT_TO_OOXML[formatting.alignment])
        if formatting.head_end is not None:
            _set_pptx_line_end(line, "headEnd", formatting.head_end)
        if formatting.tail_end is not None:
            _set_pptx_line_end(line, "tailEnd", formatting.tail_end)


def _apply_pptx_shape_formatting(
    shape: Any,
    formatting: PptxShapeFormatting,
    *,
    image_relationship_id: str | None = None,
) -> bool:
    before = etree.tostring(shape, method="c14n", with_comments=True)
    if formatting.fill is not None or formatting.geometry is not None or formatting.line is not None:
        properties = _shape_properties(shape)
    if formatting.geometry is not None:
        _set_pptx_preset_geometry(
            properties,
            formatting.geometry,
        )
    if formatting.fill is not None:
        _set_direct_fill(
            properties,
            formatting.fill,
            fill_names=_SHAPE_FILL_CHILDREN,
            ranks=_SHAPE_PROPERTY_CHILD_RANK,
            label="PPTX shape fill",
            image_relationship_id=image_relationship_id,
        )
    if formatting.line is not None:
        line = _shape_line(
            properties,
            create=formatting.line.fill is not None,
        )
        if line is None:
            raise OfficeOperationError("PPTX shape has no direct line")
        _apply_pptx_direct_line_formatting(line, formatting.line)
    if formatting.text_box is not None:
        body_properties = _text_box_body_properties(shape)
        for field_name, attribute_name in (
            ("margin_left", "lIns"),
            ("margin_top", "tIns"),
            ("margin_right", "rIns"),
            ("margin_bottom", "bIns"),
        ):
            value = getattr(formatting.text_box, field_name)
            if value is not None:
                body_properties.set(attribute_name, str(round(value * 12_700)))
        if formatting.text_box.vertical_anchor is not None:
            body_properties.set(
                "anchor",
                {
                    "top": "t",
                    "middle": "ctr",
                    "bottom": "b",
                }[formatting.text_box.vertical_anchor],
            )
    return before != etree.tostring(shape, method="c14n", with_comments=True)


def _apply_pptx_line_formatting(
    owner: Any,
    formatting: PptxLineFormatting,
) -> bool:
    before = etree.tostring(owner, method="c14n", with_comments=True)
    properties = _line_owner_properties(owner)
    line = _shape_line(properties, create=formatting.fill is not None)
    if line is None:
        raise OfficeOperationError("PPTX object has no direct line")
    _apply_pptx_direct_line_formatting(line, formatting)
    return before != etree.tostring(owner, method="c14n", with_comments=True)


def _line_formatting_property_names(
    formatting: PptxShapeLineFormatting | PptxLineFormatting,
) -> set[str]:
    properties: set[str] = set()
    if formatting.fill is not None:
        properties.add(
            {
                "none": "line_none",
                "solid": "line_color",
                "gradient": "line_gradient",
            }[formatting.fill.type]
        )
    if formatting.width_points is not None:
        properties.add("line_width")
    if formatting.cap is not None:
        properties.add("line_cap")
    if formatting.dash is not None:
        properties.add("line_dash")
    if formatting.join is not None:
        properties.add("line_join")
    if isinstance(formatting, PptxLineFormatting):
        if formatting.compound is not None:
            properties.add("line_compound")
        if formatting.alignment is not None:
            properties.add("line_alignment")
        if formatting.head_end is not None:
            properties.add("line_head_end")
        if formatting.tail_end is not None:
            properties.add("line_tail_end")
    return properties


def _shape_formatting_property_names(
    formatting: PptxShapeFormatting,
) -> set[str]:
    properties: set[str] = set()
    if formatting.geometry is not None:
        properties.add("geometry_preset")
    if formatting.fill is not None:
        properties.add(
            {
                "none": "fill_none",
                "solid": "fill_color",
                "gradient": "fill_gradient",
                "pattern": "fill_pattern",
                "image": "fill_image",
            }[formatting.fill.type]
        )
    if formatting.line is not None:
        properties.update(_line_formatting_property_names(formatting.line))
    if formatting.text_box is not None:
        properties.update(name for name in type(formatting.text_box).model_fields if getattr(formatting.text_box, name) is not None)
    return properties


def _is_stable_shape_ref(ref: _ObjectRef) -> bool:
    return ref.path_kind == "shape" and ref.identity_source == "cNvPr.id" and all("[@id=" in segment for segment in ref.path.split("/")[2:])


def _is_stable_picture_ref(ref: _ObjectRef) -> bool:
    return ref.path_kind == "picture" and ref.kind == "picture" and ref.identity_source == "cNvPr.id" and all("[@id=" in segment for segment in ref.path.split("/")[2:])


def _is_stable_line_ref(ref: _ObjectRef) -> bool:
    return ref.path_kind in {"shape", "connector"} and ref.identity_source == "cNvPr.id" and all("[@id=" in segment for segment in ref.path.split("/")[2:])


def _pptx_slide_target_map(
    package: _PackageInfo,
) -> dict[str, _PptxSlideFormattingTarget]:
    targets: dict[str, _PptxSlideFormattingTarget] = {}
    for slide_index, slide in enumerate(package.slides, start=1):
        common_slide_data = _first_child(slide.root, "cSld")
        if common_slide_data is None:
            continue
        path = f"/slide[{slide_index}]"
        targets[path] = _PptxSlideFormattingTarget(
            slide=slide,
            path=path,
            element=common_slide_data,
        )
    return targets


def _resolve_pptx_slide_formatting_targets(
    requested: list[PptxSlideTarget],
    available: dict[str, _PptxSlideFormattingTarget],
) -> list[tuple[str, _PptxSlideFormattingTarget]]:
    missing = [target.path for target in requested if target.path not in available]
    if missing:
        raise OfficeOperationError("PPTX slide background formatting contains stale or missing paths: " + ", ".join(missing[:5]))
    resolved = [(target.path, available[target.path]) for target in requested]
    mismatched = [
        path
        for requested_target, (path, resolved_target) in zip(
            requested,
            resolved,
            strict=True,
        )
        if resolved_target.slide.part_name != requested_target.expected_part_name
    ]
    if mismatched:
        raise OfficeOperationError("PPTX slide background expected_part_name no longer matches: " + ", ".join(mismatched[:5]))
    return resolved


def _pptx_shape_target_map(
    package: _PackageInfo,
) -> dict[str, _PptxFormattingTarget]:
    targets: dict[str, _PptxFormattingTarget] = {}
    for slide_index, slide in enumerate(package.slides, start=1):
        for ref in _slide_object_refs(slide.root, slide_index=slide_index):
            if not _is_stable_shape_ref(ref):
                continue
            targets[ref.path] = _PptxFormattingTarget(
                slide=slide,
                ref=ref,
                element=ref.element,
            )
    return targets


def _pptx_line_target_map(
    package: _PackageInfo,
) -> dict[str, _PptxFormattingTarget]:
    targets: dict[str, _PptxFormattingTarget] = {}
    for slide_index, slide in enumerate(package.slides, start=1):
        for ref in _slide_object_refs(slide.root, slide_index=slide_index):
            if not _is_stable_line_ref(ref):
                continue
            targets[ref.path] = _PptxFormattingTarget(
                slide=slide,
                ref=ref,
                element=ref.element,
            )
    return targets


def _pptx_picture_target_map(
    package: _PackageInfo,
) -> dict[str, _PptxFormattingTarget]:
    targets: dict[str, _PptxFormattingTarget] = {}
    for slide_index, slide in enumerate(package.slides, start=1):
        for ref in _slide_object_refs(slide.root, slide_index=slide_index):
            if not _is_stable_picture_ref(ref):
                continue
            targets[ref.path] = _PptxFormattingTarget(
                slide=slide,
                ref=ref,
                element=ref.element,
            )
    return targets


def _resolve_pptx_shape_formatting_targets(
    requested: list[PptxShapeTarget],
    available: dict[str, _PptxFormattingTarget],
) -> list[tuple[str, _PptxFormattingTarget]]:
    missing = [target.path for target in requested if target.path not in available]
    if missing:
        raise OfficeOperationError("PPTX shape formatting contains stale or missing paths: " + ", ".join(missing[:5]))
    resolved = [(target.path, available[target.path]) for target in requested]
    mismatched = []
    for requested_target, (path, resolved_target) in zip(
        requested,
        resolved,
        strict=True,
    ):
        non_visual = _non_visual_drawing_properties(resolved_target.element)
        actual_name = None if non_visual is None else non_visual.get("name")
        if actual_name != requested_target.expected_name:
            mismatched.append(path)
    if mismatched:
        raise OfficeOperationError("PPTX shape formatting expected_name no longer matches: " + ", ".join(mismatched[:5]))
    return resolved


def _resolve_pptx_picture_targets(
    requested: list[PptxPictureTarget],
    available: dict[str, _PptxFormattingTarget],
    package: _PackageInfo,
) -> list[tuple[str, _PptxFormattingTarget]]:
    missing = [target.path for target in requested if target.path not in available]
    if missing:
        raise OfficeOperationError("PPTX picture replacement contains stale or missing paths: " + ", ".join(missing[:5]))
    resolved = [(target.path, available[target.path]) for target in requested]
    mismatched_names: list[str] = []
    mismatched_sources: list[str] = []
    for requested_target, (path, resolved_target) in zip(
        requested,
        resolved,
        strict=True,
    ):
        non_visual = _non_visual_drawing_properties(resolved_target.element)
        actual_name = None if non_visual is None else non_visual.get("name")
        if actual_name != requested_target.expected_name:
            mismatched_names.append(path)
            continue
        binding = _picture_source_binding(
            resolved_target.element,
            slide=resolved_target.slide,
            package=package,
            label="PPTX picture replacement target",
            require_supported_content_type=True,
        )
        if binding.sha256 != requested_target.expected_source_sha256:
            mismatched_sources.append(path)
    if mismatched_names:
        raise OfficeOperationError("PPTX picture replacement expected_name no longer matches: " + ", ".join(mismatched_names[:5]))
    if mismatched_sources:
        raise OfficeOperationError("PPTX picture replacement expected_source_sha256 no longer matches: " + ", ".join(mismatched_sources[:5]))
    return resolved


def _resolve_pptx_line_formatting_targets(
    requested: list[PptxLineTarget],
    available: dict[str, _PptxFormattingTarget],
) -> list[tuple[str, _PptxFormattingTarget]]:
    missing = [target.path for target in requested if target.path not in available]
    if missing:
        raise OfficeOperationError("PPTX line formatting contains stale or missing paths: " + ", ".join(missing[:5]))
    resolved = [(target.path, available[target.path]) for target in requested]
    mismatched = []
    for requested_target, (path, resolved_target) in zip(
        requested,
        resolved,
        strict=True,
    ):
        non_visual = _non_visual_drawing_properties(resolved_target.element)
        actual_name = None if non_visual is None else non_visual.get("name")
        if actual_name != requested_target.expected_name:
            mismatched.append(path)
    if mismatched:
        raise OfficeOperationError("PPTX line formatting expected_name no longer matches: " + ", ".join(mismatched[:5]))
    return resolved


def _pptx_formatting_target_maps(
    package: _PackageInfo,
) -> tuple[dict[str, _PptxFormattingTarget], dict[str, _PptxFormattingTarget]]:
    paragraph_targets: dict[str, _PptxFormattingTarget] = {}
    run_targets: dict[str, _PptxFormattingTarget] = {}
    for slide_index, slide in enumerate(package.slides, start=1):
        for ref in _slide_object_refs(slide.root, slide_index=slide_index):
            if not _is_stable_shape_ref(ref):
                continue
            text_body = _first_child(ref.element, "txBody")
            if text_body is None:
                continue
            for paragraph_index, paragraph in enumerate(_children(text_body, "p"), start=1):
                paragraph_path = f"{ref.path}/paragraph[{paragraph_index}]"
                paragraph_targets[paragraph_path] = _PptxFormattingTarget(
                    slide=slide,
                    ref=ref,
                    element=paragraph,
                )
                run_index = 0
                for child in paragraph:
                    if not isinstance(child.tag, str) or _qname(child).namespace not in _DRAWING_NAMESPACES or _local_name(child) != "r":
                        continue
                    run_index += 1
                    run_targets[f"{paragraph_path}/run[{run_index}]"] = _PptxFormattingTarget(
                        slide=slide,
                        ref=ref,
                        element=child,
                    )
    return paragraph_targets, run_targets


def _run_text(run: Any) -> str:
    text = _first_drawing_child(run, "t")
    return "" if text is None else text.text or ""


def _resolve_pptx_formatting_targets(
    requested: list[PptxParagraphTarget] | list[PptxRunTarget],
    available: dict[str, _PptxFormattingTarget],
    *,
    kind: str,
) -> list[tuple[str, _PptxFormattingTarget]]:
    missing = [target.path for target in requested if target.path not in available]
    if missing:
        raise OfficeOperationError(f"PPTX {kind} formatting contains stale or missing paths: {', '.join(missing[:5])}")
    resolved = [(target.path, available[target.path]) for target in requested]
    actual_text = {path: (_paragraph_text(resolved_target.element) if kind == "paragraph" else _run_text(resolved_target.element)) for path, resolved_target in resolved}
    oversized = [path for path, value in actual_text.items() if len(value) > _MAX_FORMATTING_EXPECTED_TEXT_CHARS]
    if oversized:
        raise OfficeOperationError(f"PPTX {kind} formatting targets text longer than the {_MAX_FORMATTING_EXPECTED_TEXT_CHARS:,}-character stale guard: {', '.join(oversized[:5])}")
    mismatched = [path for target, (path, _) in zip(requested, resolved, strict=True) if actual_text[path] != target.expected_text]
    if mismatched:
        raise OfficeOperationError(f"PPTX {kind} formatting expected_text no longer matches: {', '.join(mismatched[:5])}")
    return resolved


def _source_element_paths(root: Any) -> dict[Any, tuple[int, ...]]:
    paths: dict[Any, tuple[int, ...]] = {}
    stack = [(root, ())]
    while stack:
        element, path = stack.pop()
        paths[element] = path
        stack.extend((child, (*path, index)) for index, child in reversed(list(enumerate(element))))
    return paths


def _register_formatting_mutation(
    mutations: dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    *,
    source_paths: dict[Any, tuple[int, ...]],
    element: Any,
    properties: set[str],
) -> None:
    source_path = source_paths.get(element)
    if source_path is None:
        raise OfficeOperationError("PPTX formatting target was not present in the source slide")
    existing = mutations.get(source_path)
    if existing is None:
        mutations[source_path] = _PptxAllowedFormattingMutation(
            element=element,
            properties=set(properties),
        )
        return
    if existing.element is not element:
        raise OfficeOperationError("PPTX formatting target identity changed during editing")
    existing.properties.update(properties)


def _literal_match_ranges(
    text: str,
    needle: str,
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    while True:
        start = text.find(needle, cursor)
        if start < 0:
            return ranges
        end = start + len(needle)
        ranges.append((start, end))
        cursor = end


def _pptx_paragraph_segments(paragraph: Any) -> list[_PptxTextSegment]:
    segments: list[_PptxTextSegment] = []
    spans: list[_PptxTextSpan] = []
    chunks: list[str] = []
    offset = 0

    def flush() -> None:
        nonlocal offset
        if spans:
            segments.append(
                _PptxTextSegment(
                    text="".join(chunks),
                    spans=tuple(spans),
                )
            )
        spans.clear()
        chunks.clear()
        offset = 0

    for child in paragraph:
        if not isinstance(child.tag, str):
            flush()
            continue
        name = _qname(child)
        if name.namespace in _DRAWING_NAMESPACES and name.localname in {"endParaRPr", "pPr"}:
            continue
        if name.namespace not in _DRAWING_NAMESPACES or name.localname != "r":
            flush()
            continue
        linked_run = any(isinstance(candidate.tag, str) and _qname(candidate).namespace in _DRAWING_NAMESPACES and _local_name(candidate) in {"hlinkClick", "hlinkHover", "hlinkMouseOver"} for candidate in child.iter())
        if linked_run:
            flush()
        text_element = next(
            (candidate for candidate in child if isinstance(candidate.tag, str) and _qname(candidate).namespace in _DRAWING_NAMESPACES and _local_name(candidate) == "t"),
            None,
        )
        if text_element is None:
            flush()
            continue
        value = text_element.text or ""
        if not value:
            continue
        spans.append(
            _PptxTextSpan(
                text_element=text_element,
                start=offset,
                end=offset + len(value),
            )
        )
        chunks.append(value)
        offset += len(value)
        if linked_run:
            flush()
    flush()
    return segments


def _pptx_paragraph_visible_text(paragraph: Any) -> str:
    chunks: list[str] = []
    for child in paragraph:
        if not isinstance(child.tag, str):
            continue
        name = _qname(child)
        if name.namespace not in _DRAWING_NAMESPACES:
            continue
        if name.localname in {"r", "fld"}:
            chunks.extend(element.text or "" for element in child.iter() if isinstance(element.tag, str) and _qname(element).namespace in _DRAWING_NAMESPACES and _local_name(element) == "t")
        elif name.localname == "br":
            chunks.append("\n")
        elif name.localname == "tab":
            chunks.append("\t")
    return "".join(chunks)


def _element_index_path(root: Any, element: Any) -> tuple[int, ...]:
    indices: list[int] = []
    current = element
    while current is not root:
        parent = current.getparent()
        if parent is None:
            raise OfficeOperationError("PPTX text target escaped its owning slide")
        indices.append(parent.index(current))
        current = parent
    return tuple(reversed(indices))


def _element_at_index_path(root: Any, path: tuple[int, ...]) -> Any:
    current = root
    for index in path:
        if index >= len(current):
            raise OfficeOperationError("PPTX text-only preservation path changed during editing")
        current = current[index]
    return current


def _set_pptx_text(
    text_element: Any,
    value: str,
    *,
    source_paths: dict[Any, tuple[int, ...]],
    allowed_elements: dict[tuple[int, ...], Any],
) -> bool:
    if (text_element.text or "") == value:
        return False
    text_element.text = value
    if value and (value[0].isspace() or value[-1].isspace()):
        text_element.set(_XML_SPACE, "preserve")
    source_path = source_paths.get(text_element)
    if source_path is None:
        raise OfficeOperationError("PPTX text target was not present in the source slide")
    allowed_elements[source_path] = text_element
    return True


def _replace_pptx_segment(
    segment: _PptxTextSegment,
    *,
    ranges: list[tuple[int, int]],
    replacement: str,
    source_paths: dict[Any, tuple[int, ...]],
    allowed_elements: dict[tuple[int, ...], Any],
) -> bool:
    changed = False
    for match_start, match_end in reversed(ranges):
        first = True
        for span in segment.spans:
            if span.end <= match_start or span.start >= match_end:
                continue
            current = span.text_element.text or ""
            local_start = max(0, match_start - span.start)
            local_end = min(len(current), match_end - span.start)
            updated = current[:local_start] + (replacement if first else "") + current[local_end:]
            changed = (
                _set_pptx_text(
                    span.text_element,
                    updated,
                    source_paths=source_paths,
                    allowed_elements=allowed_elements,
                )
                or changed
            )
            first = False
    return changed


def _replace_pptx_shape_text(
    ref: _ObjectRef,
    *,
    find: str,
    replacement: str,
    first_only: bool,
    source_paths: dict[Any, tuple[int, ...]],
    allowed_elements: dict[tuple[int, ...], Any],
) -> tuple[int, bool]:
    text_body = _first_child(ref.element, "txBody")
    if text_body is None:
        return 0, False
    match_count = 0
    changed = False
    for paragraph in _children(text_body, "p"):
        segments = _pptx_paragraph_segments(paragraph)
        safe_ranges = [(segment, _literal_match_ranges(segment.text, find)) for segment in segments]
        safe_match_count = sum(len(ranges) for _, ranges in safe_ranges)
        visible_match_count = len(
            _literal_match_ranges(
                _pptx_paragraph_visible_text(paragraph),
                find,
            )
        )
        if visible_match_count > safe_match_count:
            raise OfficeOperationError(f"PPTX text replacement would cross or modify a hyperlink, field, break, tab, or unsupported text boundary at {ref.path}")
        for segment, ranges in safe_ranges:
            if not ranges:
                continue
            selected_ranges = ranges[:1] if first_only else ranges
            changed = (
                _replace_pptx_segment(
                    segment,
                    ranges=selected_ranges,
                    replacement=replacement,
                    source_paths=source_paths,
                    allowed_elements=allowed_elements,
                )
                or changed
            )
            match_count += len(selected_ranges)
            if first_only:
                return match_count, changed
    return match_count, changed


def _mask_run_formatting(run: Any, properties: set[str]) -> None:
    run_properties = _ensure_run_properties(run)
    attribute_names = {
        "bold": "b",
        "italic": "i",
        "font_size": "sz",
        "underline": "u",
        "underline_none": "u",
        "strike": "strike",
    }
    font_children = {
        "font_latin": ("latin",),
        "font_east_asia": ("ea",),
        "font_complex_script": ("cs",),
        "font": ("latin", "ea"),
    }
    for property_name in properties:
        attribute_name = attribute_names.get(property_name)
        if attribute_name is not None:
            run_properties.set(attribute_name, "__VASSILFLOW_FORMAT__")
            if property_name == "underline_none":
                _remove_drawing_children(
                    run_properties,
                    _RUN_UNDERLINE_CHILDREN,
                )
        elif property_name == "color":
            _set_run_color(run_properties, "__VASSILFLOW_COLOR__")
        elif property_name in font_children:
            for child_name in font_children[property_name]:
                _set_run_font(
                    run_properties,
                    child_name,
                    "__VASSILFLOW_FONT__",
                )
        else:
            raise OfficeOperationError(f"Unsupported PPTX run formatting invariant: {property_name}")


def _mask_paragraph_formatting(paragraph: Any, properties: set[str]) -> None:
    paragraph_properties = _ensure_paragraph_properties(paragraph)
    child_names = {
        "space_before": "spcBef",
        "space_after": "spcAft",
        "line_spacing_points": "lnSpc",
        "line_spacing_percent": "lnSpc",
    }
    for property_name in properties:
        if property_name == "alignment":
            paragraph_properties.set("algn", "__VASSILFLOW_FORMAT__")
        elif property_name in child_names:
            _remove_drawing_children(
                paragraph_properties,
                {child_names[property_name]},
            )
        else:
            raise OfficeOperationError(f"Unsupported PPTX paragraph formatting invariant: {property_name}")


def _mask_direct_fill_slot(
    parent: Any,
    *,
    fill_names: frozenset[str],
    ranks: dict[str, int],
    label: str,
    allow_gradient: bool = False,
    allow_pattern: bool = False,
    allow_image: bool = False,
) -> None:
    fills = _require_supported_direct_fill(
        parent,
        fill_names,
        label=label,
        allow_gradient=allow_gradient,
        allow_pattern=allow_pattern,
        allow_image=allow_image,
    )
    sentinel = _new_drawing_child(parent, "solidFill")
    color = _new_drawing_child(sentinel, "srgbClr")
    color.set("val", "000000")
    sentinel.append(color)
    if fills:
        parent.replace(fills[0], sentinel)
    else:
        _insert_ordered_drawing_child(parent, sentinel, ranks)


def _mask_line_choice_slot(
    line: Any,
    *,
    choice_names: frozenset[str],
    sentinel_name: str,
    sentinel_attribute: tuple[str, str] | None = None,
) -> None:
    choices = _line_choice_children(line, choice_names)
    if len(choices) > 1:
        raise OfficeOperationError("PPTX line formatting invariant found multiple choices")
    sentinel = _new_drawing_child(line, sentinel_name)
    if sentinel_attribute is not None:
        sentinel.set(*sentinel_attribute)
    if choices:
        line.replace(choices[0], sentinel)
    else:
        _insert_ordered_drawing_child(
            line,
            sentinel,
            _LINE_PROPERTY_CHILD_RANK,
        )


def _mask_line_formatting(owner: Any, properties: set[str]) -> None:
    supported = {
        "line_none",
        "line_color",
        "line_gradient",
        "line_width",
        "line_cap",
        "line_dash",
        "line_join",
        "line_compound",
        "line_alignment",
        "line_head_end",
        "line_tail_end",
    }
    unsupported = properties - supported
    if unsupported:
        raise OfficeOperationError("Unsupported PPTX line formatting invariant: " + ", ".join(sorted(unsupported)))
    if not properties:
        return

    shape_properties = _line_owner_properties(owner)
    line = _shape_line(shape_properties, create=True)
    if line is None:
        raise OfficeOperationError("PPTX line formatting invariant could not create a line")
    if "line_none" in properties or "line_gradient" in properties:
        _mask_direct_fill_slot(
            line,
            fill_names=_LINE_FILL_CHILDREN,
            ranks=_LINE_PROPERTY_CHILD_RANK,
            label="PPTX line fill",
            allow_gradient="line_gradient" in properties,
        )
    elif "line_color" in properties:
        _set_direct_fill(
            line,
            PptxShapeFillFormatting(type="solid", color="000000"),
            fill_names=_LINE_FILL_CHILDREN,
            ranks=_LINE_PROPERTY_CHILD_RANK,
            label="PPTX line fill",
        )
    if "line_width" in properties:
        line.set("w", "__VASSILFLOW_FORMAT__")
    if "line_cap" in properties:
        line.set("cap", "__VASSILFLOW_FORMAT__")
    if "line_dash" in properties:
        _mask_line_choice_slot(
            line,
            choice_names=_LINE_DASH_CHILDREN,
            sentinel_name="prstDash",
            sentinel_attribute=("val", "solid"),
        )
    if "line_join" in properties:
        _mask_line_choice_slot(
            line,
            choice_names=_LINE_JOIN_CHILDREN,
            sentinel_name="round",
        )
    if "line_compound" in properties:
        line.set("cmpd", "__VASSILFLOW_FORMAT__")
    if "line_alignment" in properties:
        line.set("algn", "__VASSILFLOW_FORMAT__")
    if "line_head_end" in properties:
        _mask_line_choice_slot(
            line,
            choice_names=frozenset({"headEnd"}),
            sentinel_name="headEnd",
            sentinel_attribute=("type", "none"),
        )
    if "line_tail_end" in properties:
        _mask_line_choice_slot(
            line,
            choice_names=frozenset({"tailEnd"}),
            sentinel_name="tailEnd",
            sentinel_attribute=("type", "none"),
        )


def _mask_shape_formatting(shape: Any, properties: set[str]) -> None:
    if "geometry_preset" in properties:
        geometry = _preflight_pptx_preset_geometry(
            _shape_properties(shape),
        )
        geometry.set("prst", "__VASSILFLOW_FORMAT__")

    if "fill_none" in properties or "fill_gradient" in properties or "fill_pattern" in properties or "fill_image" in properties:
        shape_properties = _shape_properties(shape)
        _mask_direct_fill_slot(
            shape_properties,
            fill_names=_SHAPE_FILL_CHILDREN,
            ranks=_SHAPE_PROPERTY_CHILD_RANK,
            label="PPTX shape fill",
            allow_gradient="fill_gradient" in properties,
            allow_pattern="fill_pattern" in properties,
            allow_image="fill_image" in properties,
        )
    elif "fill_color" in properties:
        shape_properties = _shape_properties(shape)
        _set_direct_fill(
            shape_properties,
            PptxShapeFillFormatting(type="solid", color="000000"),
            fill_names=_SHAPE_FILL_CHILDREN,
            ranks=_SHAPE_PROPERTY_CHILD_RANK,
            label="PPTX shape fill",
        )

    line_properties = {
        "line_none",
        "line_gradient",
        "line_color",
        "line_width",
        "line_cap",
        "line_dash",
        "line_join",
    } & properties
    _mask_line_formatting(shape, line_properties)

    text_box_attributes = {
        "margin_left": "lIns",
        "margin_top": "tIns",
        "margin_right": "rIns",
        "margin_bottom": "bIns",
        "vertical_anchor": "anchor",
    }
    requested_text_box = properties & text_box_attributes.keys()
    if requested_text_box:
        body_properties = _text_box_body_properties(shape)
        for property_name in requested_text_box:
            body_properties.set(
                text_box_attributes[property_name],
                "__VASSILFLOW_FORMAT__",
            )

    supported = {
        "geometry_preset",
        "fill_color",
        "fill_none",
        "fill_gradient",
        "fill_pattern",
        "fill_image",
        "line_color",
        "line_none",
        "line_gradient",
        "line_width",
        "line_cap",
        "line_dash",
        "line_join",
        *text_box_attributes.keys(),
    }
    unsupported = properties - supported
    if unsupported:
        raise OfficeOperationError("Unsupported PPTX shape formatting invariant: " + ", ".join(sorted(unsupported)))


def _mask_slide_background(root: Any) -> None:
    presentation_namespace = _qname(root).namespace
    if presentation_namespace not in _PRESENTATION_NAMESPACES:
        raise OfficeOperationError("PPTX slide background invariant has an unsupported namespace")
    common_slide_data = [child for child in root if isinstance(child.tag, str) and _qname(child).namespace == presentation_namespace and _local_name(child) == "cSld"]
    if len(common_slide_data) != 1:
        raise OfficeOperationError("PPTX slide background invariant requires one common slide data element")
    common = common_slide_data[0]
    backgrounds = [child for child in common if isinstance(child.tag, str) and _qname(child).namespace == presentation_namespace and _local_name(child) == "bg"]
    for background in backgrounds:
        common.remove(background)
    shape_trees = [child for child in common if isinstance(child.tag, str) and _qname(child).namespace == presentation_namespace and _local_name(child) == "spTree"]
    if len(shape_trees) != 1:
        raise OfficeOperationError("PPTX slide background invariant requires one shape tree")
    background = etree.Element(etree.QName(presentation_namespace, "bg"))
    properties = etree.SubElement(
        background,
        etree.QName(presentation_namespace, "bgPr"),
    )
    properties.append(_new_drawing_child(properties, "noFill"))
    shape_tree = shape_trees[0]
    common.insert(common.index(shape_tree), background)


def _mask_picture_source(picture: Any) -> None:
    name = _qname(picture)
    if name.namespace not in _PRESENTATION_NAMESPACES or name.localname != "pic":
        raise OfficeOperationError("PPTX picture replacement path no longer targets a picture")
    drawing_namespace = _drawing_namespace_for_context(picture)
    relationship_namespace = _document_relationship_namespace_for_context(picture)
    fills = [child for child in picture if isinstance(child.tag, str) and _qname(child).namespace == name.namespace and _local_name(child) == "blipFill"]
    if len(fills) != 1:
        raise OfficeOperationError("PPTX picture replacement invariant requires one direct blip fill")
    blips = [child for child in fills[0] if isinstance(child.tag, str) and _qname(child).namespace == drawing_namespace and _local_name(child) == "blip"]
    if len(blips) != 1:
        raise OfficeOperationError("PPTX picture replacement invariant requires one direct blip")
    embed_attribute = str(etree.QName(relationship_namespace, "embed"))
    if not blips[0].get(embed_attribute):
        raise OfficeOperationError("PPTX picture replacement invariant lost its embedded source")
    blips[0].set(embed_attribute, "__VASSILFLOW_PICTURE_SOURCE__")


def _enforce_pptx_allowed_change(
    original_tree: Any,
    edited_tree: Any,
    *,
    allowed_text: dict[tuple[int, ...], Any],
    allowed_runs: dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    allowed_paragraphs: dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    allowed_shapes: dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    allowed_lines: dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    allowed_pictures: dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    allow_background: bool,
    part_name: str,
) -> None:
    edited_root = edited_tree.getroot()
    text_paths = [(source_path, _element_index_path(edited_root, element)) for source_path, element in allowed_text.items()]
    run_paths = [
        (
            source_path,
            _element_index_path(edited_root, mutation.element),
            mutation.properties,
        )
        for source_path, mutation in allowed_runs.items()
    ]
    paragraph_paths = [
        (
            source_path,
            _element_index_path(edited_root, mutation.element),
            mutation.properties,
        )
        for source_path, mutation in allowed_paragraphs.items()
    ]
    shape_paths = [
        (
            source_path,
            _element_index_path(edited_root, mutation.element),
            mutation.properties,
        )
        for source_path, mutation in allowed_shapes.items()
    ]
    line_paths = [
        (
            source_path,
            _element_index_path(edited_root, mutation.element),
            mutation.properties,
        )
        for source_path, mutation in allowed_lines.items()
    ]
    picture_paths = [
        (
            source_path,
            _element_index_path(edited_root, mutation.element),
        )
        for source_path, mutation in allowed_pictures.items()
    ]
    original_document = copy.deepcopy(original_tree)
    edited_document = copy.deepcopy(edited_tree)
    original = original_document.getroot()
    edited = edited_document.getroot()
    if allow_background:
        _mask_slide_background(original)
        _mask_slide_background(edited)
    for source_path, edited_path in text_paths:
        original_text = _element_at_index_path(original, source_path)
        edited_text = _element_at_index_path(edited, edited_path)
        for element in (original_text, edited_text):
            name = _qname(element)
            if name.namespace not in _DRAWING_NAMESPACES or name.localname != "t":
                raise OfficeOperationError("PPTX text-only preservation path no longer targets text")
            element.text = "__VASSILFLOW_TEXT__"
            element.attrib.pop(_XML_SPACE, None)
    for source_path, edited_path, properties in run_paths:
        original_run = _element_at_index_path(original, source_path)
        edited_run = _element_at_index_path(edited, edited_path)
        for element in (original_run, edited_run):
            name = _qname(element)
            if name.namespace not in _DRAWING_NAMESPACES or name.localname != "r":
                raise OfficeOperationError("PPTX run formatting path no longer targets a run")
            _mask_run_formatting(element, properties)
    for source_path, edited_path, properties in paragraph_paths:
        original_paragraph = _element_at_index_path(original, source_path)
        edited_paragraph = _element_at_index_path(edited, edited_path)
        for element in (original_paragraph, edited_paragraph):
            name = _qname(element)
            if name.namespace not in _DRAWING_NAMESPACES or name.localname != "p":
                raise OfficeOperationError("PPTX paragraph formatting path no longer targets a paragraph")
            _mask_paragraph_formatting(element, properties)
    for source_path, edited_path, properties in shape_paths:
        original_shape = _element_at_index_path(original, source_path)
        edited_shape = _element_at_index_path(edited, edited_path)
        for element in (original_shape, edited_shape):
            name = _qname(element)
            if name.namespace not in _PRESENTATION_NAMESPACES or name.localname != "sp":
                raise OfficeOperationError("PPTX shape formatting path no longer targets a shape")
            _mask_shape_formatting(element, properties)
    for source_path, edited_path, properties in line_paths:
        original_owner = _element_at_index_path(original, source_path)
        edited_owner = _element_at_index_path(edited, edited_path)
        for element in (original_owner, edited_owner):
            name = _qname(element)
            if name.namespace not in _PRESENTATION_NAMESPACES or name.localname not in {"sp", "cxnSp"}:
                raise OfficeOperationError("PPTX line formatting path no longer targets a shape or connector")
            _mask_line_formatting(element, properties)
    for source_path, edited_path in picture_paths:
        original_picture = _element_at_index_path(original, source_path)
        edited_picture = _element_at_index_path(edited, edited_path)
        _mask_picture_source(original_picture)
        _mask_picture_source(edited_picture)
    original_c14n = etree.tostring(
        original_document,
        method="c14n",
        with_comments=True,
    )
    edited_c14n = etree.tostring(
        edited_document,
        method="c14n",
        with_comments=True,
    )
    if original_c14n != edited_c14n:
        raise OfficeOperationError(f"PPTX edit changed unsupported structure in {part_name}")


def _serialize_pptx_edit(
    data: bytes,
    replacements: dict[str, bytes],
    additions: dict[str, bytes] | None = None,
) -> bytes:
    added_parts = additions or {}
    if set(replacements) & set(added_parts):
        raise OfficePackageError("PPTX edit cannot both replace and add the same package part")
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as source:
            with zipfile.ZipFile(output, mode="w") as destination:
                destination.comment = source.comment
                for original_info in source.infolist():
                    info = copy.copy(original_info)
                    payload = replacements.get(
                        info.filename,
                        source.read(original_info),
                    )
                    destination.writestr(info, payload)
                for part_name in sorted(added_parts):
                    if part_name in source.NameToInfo:
                        raise OfficePackageError(f"PPTX edit tried to add an existing package part: {part_name}")
                    info = zipfile.ZipInfo(
                        filename=part_name,
                        date_time=(1980, 1, 1, 0, 0, 0),
                    )
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o600 << 16
                    destination.writestr(info, added_parts[part_name])
    except (KeyError, zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise OfficePackageError(f"Invalid PPTX package: {exc}") from exc
    result = output.getvalue()
    if len(result) > _MAX_PACKAGE_BYTES:
        raise OfficePackageError("Edited PPTX exceeds the 50 MiB package limit")
    enforce_package_preservation(
        data,
        result,
        changed_parts=replacements,
        added_parts=added_parts,
        label="PPTX",
    )
    _load_package_info(result)
    return result


def edit_pptx(
    data: bytes,
    operations: list[PptxEditOperation],
    *,
    image_assets: dict[str, bytes] | None = None,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Apply bounded text, formatting, and picture-source edits as one PPTX transaction."""
    if not operations:
        raise OfficeOperationError("At least one Office edit operation is required")
    package = _load_package_info(data)
    blocked = [feature for feature in package.risky_features if feature in _RENDER_BLOCKED_FEATURES]
    if blocked:
        raise OfficeOperationError(f"PPTX editing is disabled for presentations containing {', '.join(blocked)}")

    original_trees = {slide.part_name: copy.deepcopy(slide.root.getroottree()) for slide in package.slides}
    source_paths_by_part = {slide.part_name: _source_element_paths(slide.root) for slide in package.slides}
    refs_by_path: dict[str, tuple[int, _Slide, _ObjectRef]] = {}
    ordered_refs: list[tuple[int, _Slide, _ObjectRef]] = []
    for slide_index, slide in enumerate(package.slides, start=1):
        for ref in _slide_object_refs(slide.root, slide_index=slide_index):
            item = (slide_index, slide, ref)
            refs_by_path[ref.path] = item
            ordered_refs.append(item)
    slide_targets = _pptx_slide_target_map(package)
    shape_targets = _pptx_shape_target_map(package)
    line_targets = _pptx_line_target_map(package)
    picture_targets = _pptx_picture_target_map(package)
    paragraph_targets, run_targets = _pptx_formatting_target_maps(package)
    preflight_formatting_targets: dict[
        int,
        list[
            tuple[
                str,
                _PptxFormattingTarget | _PptxSlideFormattingTarget,
            ]
        ],
    ] = {}
    formatting_target_counts: dict[str, int] = {}
    image_requests: list[_PptxImageMutationRequest | _PptxPictureImageMutationRequest] = []
    image_target_paths: set[str] = set()
    for operation_index, operation in enumerate(operations, start=1):
        if isinstance(operation, PptxRunFormatOperation):
            preflight_formatting_targets[operation_index] = _resolve_pptx_formatting_targets(
                operation.runs.targets,
                run_targets,
                kind="run",
            )
        elif isinstance(operation, PptxParagraphFormatOperation):
            preflight_formatting_targets[operation_index] = _resolve_pptx_formatting_targets(
                operation.paragraphs.targets,
                paragraph_targets,
                kind="paragraph",
            )
        elif isinstance(operation, PptxShapeFormatOperation):
            resolved_shapes = _resolve_pptx_shape_formatting_targets(
                operation.shapes.targets,
                shape_targets,
            )
            for _, target in resolved_shapes:
                _preflight_pptx_shape_formatting(target, operation.formatting)
                formatting_target_counts[target.ref.path] = formatting_target_counts.get(target.ref.path, 0) + 1
                if operation.formatting.fill is not None and operation.formatting.fill.type == "image":
                    image_requests.append(
                        _shape_image_mutation_request(
                            target,
                            operation.formatting.fill,
                        )
                    )
                    image_target_paths.add(target.ref.path)
            preflight_formatting_targets[operation_index] = resolved_shapes
        elif isinstance(operation, PptxLineFormatOperation):
            resolved_lines = _resolve_pptx_line_formatting_targets(
                operation.lines.targets,
                line_targets,
            )
            for _, target in resolved_lines:
                _preflight_pptx_line_formatting(target, operation.formatting)
            preflight_formatting_targets[operation_index] = resolved_lines
        elif isinstance(operation, PptxSlideBackgroundFormatOperation):
            resolved_slides = _resolve_pptx_slide_formatting_targets(
                operation.slides.targets,
                slide_targets,
            )
            for _, target in resolved_slides:
                _preflight_pptx_slide_background(target)
                formatting_target_counts[target.path] = formatting_target_counts.get(target.path, 0) + 1
                if operation.formatting.type == "image":
                    image_requests.append(
                        _background_image_mutation_request(
                            target,
                            operation.formatting,
                        )
                    )
                    image_target_paths.add(target.path)
            preflight_formatting_targets[operation_index] = resolved_slides
        elif isinstance(operation, PptxPictureSourceReplacementOperation):
            resolved_pictures = _resolve_pptx_picture_targets(
                operation.pictures.targets,
                picture_targets,
                package,
            )
            for _, target in resolved_pictures:
                formatting_target_counts[target.ref.path] = formatting_target_counts.get(target.ref.path, 0) + 1
                image_requests.append(
                    _picture_image_mutation_request(
                        target,
                        operation,
                        package,
                    )
                )
                image_target_paths.add(target.ref.path)
            preflight_formatting_targets[operation_index] = resolved_pictures

    duplicate_image_targets = sorted(path for path in image_target_paths if formatting_target_counts.get(path, 0) != 1)
    if duplicate_image_targets:
        raise OfficeOperationError("PPTX image mutation targets may appear in only one operation")
    image_plan = _plan_pptx_image_mutations(
        data,
        package,
        image_requests,
        image_assets,
    )

    reports: list[dict[str, Any]] = []
    allowed_text_by_part: dict[str, dict[tuple[int, ...], Any]] = {}
    allowed_runs_by_part: dict[
        str,
        dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    ] = {}
    allowed_paragraphs_by_part: dict[
        str,
        dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    ] = {}
    allowed_shapes_by_part: dict[
        str,
        dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    ] = {}
    allowed_lines_by_part: dict[
        str,
        dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    ] = {}
    allowed_pictures_by_part: dict[
        str,
        dict[tuple[int, ...], _PptxAllowedFormattingMutation],
    ] = {}
    allowed_background_parts: set[str] = set()
    total_text_replacements = 0
    total_formatting_targets = 0
    changed_parts: set[str] = set()
    for operation_index, operation in enumerate(operations, start=1):
        if isinstance(operation, PptxTextReplacement):
            missing_paths = [path for path in operation.paths if path not in refs_by_path]
            if missing_paths:
                raise OfficeOperationError(f"PPTX text replacement contains stale or missing paths: {', '.join(missing_paths[:5])}")
            selected_paths = set(operation.paths)
            targets = [item for item in ordered_refs if item[2].path in selected_paths]
            match_count = 0
            matched_paths: list[str] = []
            for _, slide, ref in targets:
                if not _is_stable_shape_ref(ref):
                    raise OfficeOperationError("PPTX text replacement requires stable authored shape paths")
                allowed_text = allowed_text_by_part.setdefault(
                    slide.part_name,
                    {},
                )
                count, changed = _replace_pptx_shape_text(
                    ref,
                    find=operation.find,
                    replacement=operation.replace,
                    first_only=(operation.occurrence == "first" and match_count == 0),
                    source_paths=source_paths_by_part[slide.part_name],
                    allowed_elements=allowed_text,
                )
                if count:
                    matched_paths.append(ref.path)
                match_count += count
                total_text_replacements += count
                if total_text_replacements > _MAX_EDIT_TEXT_REPLACEMENTS:
                    raise OfficeOperationError("PPTX edit exceeds the supported replacement limit")
                if changed:
                    changed_parts.add(slide.part_name)
                if operation.occurrence == "first" and match_count:
                    break
            if operation.require_match and match_count == 0:
                raise OfficeOperationError(f"Operation {operation_index} matched no targets; no presentation changes were written")
            reports.append(
                {
                    "operation": operation_index,
                    "type": operation.type,
                    "occurrence": operation.occurrence,
                    "match_count": match_count,
                    "matched_paths": matched_paths[:20],
                    "matched_paths_truncated": len(matched_paths) > 20,
                }
            )
            continue

        if isinstance(operation, PptxRunFormatOperation):
            resolved = preflight_formatting_targets[operation_index]
            properties = _formatting_property_names(operation.formatting)
            if operation.formatting.underline == "none":
                properties.remove("underline")
                properties.add("underline_none")
            total_formatting_targets += len(resolved)
            if total_formatting_targets > _MAX_EDIT_FORMATTING_TARGETS:
                raise OfficeOperationError("PPTX edit exceeds the supported formatting target limit")
            for _, target in resolved:
                mutations = allowed_runs_by_part.setdefault(
                    target.slide.part_name,
                    {},
                )
                _register_formatting_mutation(
                    mutations,
                    source_paths=source_paths_by_part[target.slide.part_name],
                    element=target.element,
                    properties=properties,
                )
                if _apply_pptx_run_formatting(
                    target.element,
                    operation.formatting,
                ):
                    changed_parts.add(target.slide.part_name)
            matched_paths = [path for path, _ in resolved]
            reports.append(
                {
                    "operation": operation_index,
                    "type": operation.type,
                    "match_count": len(resolved),
                    "matched_paths": matched_paths[:20],
                    "matched_paths_truncated": len(matched_paths) > 20,
                }
            )
            continue

        if isinstance(operation, PptxParagraphFormatOperation):
            resolved = preflight_formatting_targets[operation_index]
            properties = _formatting_property_names(operation.formatting)
            total_formatting_targets += len(resolved)
            if total_formatting_targets > _MAX_EDIT_FORMATTING_TARGETS:
                raise OfficeOperationError("PPTX edit exceeds the supported formatting target limit")
            for _, target in resolved:
                mutations = allowed_paragraphs_by_part.setdefault(
                    target.slide.part_name,
                    {},
                )
                _register_formatting_mutation(
                    mutations,
                    source_paths=source_paths_by_part[target.slide.part_name],
                    element=target.element,
                    properties=properties,
                )
                if _apply_pptx_paragraph_formatting(
                    target.element,
                    operation.formatting,
                ):
                    changed_parts.add(target.slide.part_name)
            matched_paths = [path for path, _ in resolved]
            reports.append(
                {
                    "operation": operation_index,
                    "type": operation.type,
                    "match_count": len(resolved),
                    "matched_paths": matched_paths[:20],
                    "matched_paths_truncated": len(matched_paths) > 20,
                }
            )
            continue

        if isinstance(operation, PptxShapeFormatOperation):
            resolved = preflight_formatting_targets[operation_index]
            properties = _shape_formatting_property_names(operation.formatting)
            total_formatting_targets += len(resolved)
            if total_formatting_targets > _MAX_EDIT_FORMATTING_TARGETS:
                raise OfficeOperationError("PPTX edit exceeds the supported formatting target limit")
            for _, target in resolved:
                mutations = allowed_shapes_by_part.setdefault(
                    target.slide.part_name,
                    {},
                )
                _register_formatting_mutation(
                    mutations,
                    source_paths=source_paths_by_part[target.slide.part_name],
                    element=target.element,
                    properties=properties,
                )
                if operation.formatting.fill is not None and operation.formatting.fill.type == "image":
                    changed = _apply_pptx_shape_formatting(
                        target.element,
                        operation.formatting,
                        image_relationship_id=image_plan.targets[target.ref.path].relationship_id,
                    )
                else:
                    changed = _apply_pptx_shape_formatting(
                        target.element,
                        operation.formatting,
                    )
                _preflight_pptx_shape_formatting(
                    target,
                    operation.formatting,
                )
                if changed:
                    changed_parts.add(target.slide.part_name)
            matched_paths = [path for path, _ in resolved]
            reports.append(
                {
                    "operation": operation_index,
                    "type": operation.type,
                    "match_count": len(resolved),
                    "matched_paths": matched_paths[:20],
                    "matched_paths_truncated": len(matched_paths) > 20,
                }
            )
            continue

        if isinstance(operation, PptxLineFormatOperation):
            resolved = preflight_formatting_targets[operation_index]
            properties = _line_formatting_property_names(operation.formatting)
            total_formatting_targets += len(resolved)
            if total_formatting_targets > _MAX_EDIT_FORMATTING_TARGETS:
                raise OfficeOperationError("PPTX edit exceeds the supported formatting target limit")
            for _, target in resolved:
                mutations = allowed_lines_by_part.setdefault(
                    target.slide.part_name,
                    {},
                )
                _register_formatting_mutation(
                    mutations,
                    source_paths=source_paths_by_part[target.slide.part_name],
                    element=target.element,
                    properties=properties,
                )
                changed = _apply_pptx_line_formatting(
                    target.element,
                    operation.formatting,
                )
                _preflight_pptx_line_formatting(
                    target,
                    operation.formatting,
                )
                if changed:
                    changed_parts.add(target.slide.part_name)
            matched_paths = [path for path, _ in resolved]
            reports.append(
                {
                    "operation": operation_index,
                    "type": operation.type,
                    "match_count": len(resolved),
                    "matched_paths": matched_paths[:20],
                    "matched_paths_truncated": len(matched_paths) > 20,
                }
            )
            continue

        if isinstance(operation, PptxSlideBackgroundFormatOperation):
            resolved = preflight_formatting_targets[operation_index]
            total_formatting_targets += len(resolved)
            if total_formatting_targets > _MAX_EDIT_FORMATTING_TARGETS:
                raise OfficeOperationError("PPTX edit exceeds the supported formatting target limit")
            for _, raw_target in resolved:
                if not isinstance(raw_target, _PptxSlideFormattingTarget):
                    raise OfficeOperationError("PPTX slide background target invariant failed")
                allowed_background_parts.add(raw_target.slide.part_name)
                image_relationship_id = None
                if operation.formatting.type == "image":
                    image_relationship_id = image_plan.targets[raw_target.path].relationship_id
                changed = _apply_pptx_slide_background(
                    raw_target,
                    operation.formatting,
                    image_relationship_id=image_relationship_id,
                )
                if changed:
                    changed_parts.add(raw_target.slide.part_name)
            matched_paths = [path for path, _ in resolved]
            reports.append(
                {
                    "operation": operation_index,
                    "type": operation.type,
                    "match_count": len(resolved),
                    "matched_paths": matched_paths[:20],
                    "matched_paths_truncated": len(matched_paths) > 20,
                }
            )
            continue

        if isinstance(operation, PptxPictureSourceReplacementOperation):
            resolved = preflight_formatting_targets[operation_index]
            total_formatting_targets += len(resolved)
            if total_formatting_targets > _MAX_EDIT_FORMATTING_TARGETS:
                raise OfficeOperationError("PPTX edit exceeds the supported formatting target limit")
            for _, raw_target in resolved:
                if not isinstance(raw_target, _PptxFormattingTarget):
                    raise OfficeOperationError("PPTX picture replacement target invariant failed")
                mutations = allowed_pictures_by_part.setdefault(
                    raw_target.slide.part_name,
                    {},
                )
                _register_formatting_mutation(
                    mutations,
                    source_paths=source_paths_by_part[raw_target.slide.part_name],
                    element=raw_target.element,
                    properties={"source"},
                )
                if _apply_pptx_picture_source(
                    raw_target,
                    package,
                    image_relationship_id=image_plan.targets[raw_target.ref.path].relationship_id,
                ):
                    changed_parts.add(raw_target.slide.part_name)
            matched_paths = [path for path, _ in resolved]
            reports.append(
                {
                    "operation": operation_index,
                    "type": operation.type,
                    "match_count": len(resolved),
                    "matched_paths": matched_paths[:20],
                    "matched_paths_truncated": len(matched_paths) > 20,
                }
            )
            continue

        raise OfficeOperationError(f"Unsupported Office operation at position {operation_index}")

    if not changed_parts:
        return data, reports

    replacements: dict[str, bytes] = dict(image_plan.replacements)
    for slide in package.slides:
        if slide.part_name not in changed_parts:
            continue
        _enforce_pptx_allowed_change(
            original_trees[slide.part_name],
            slide.root.getroottree(),
            allowed_text=allowed_text_by_part.get(slide.part_name, {}),
            allowed_runs=allowed_runs_by_part.get(slide.part_name, {}),
            allowed_paragraphs=allowed_paragraphs_by_part.get(slide.part_name, {}),
            allowed_shapes=allowed_shapes_by_part.get(slide.part_name, {}),
            allowed_lines=allowed_lines_by_part.get(slide.part_name, {}),
            allowed_pictures=allowed_pictures_by_part.get(slide.part_name, {}),
            allow_background=slide.part_name in allowed_background_parts,
            part_name=slide.part_name,
        )
        replacements[slide.part_name] = etree.tostring(
            slide.root.getroottree(),
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    return _serialize_pptx_edit(
        data,
        replacements,
        image_plan.additions,
    ), reports


def inspect_pptx(
    data: bytes,
    *,
    start_slide: int = 1,
    max_slides: int = 20,
    include_formatting: bool = False,
    include_annotations: bool = False,
    include_dynamics: bool = False,
    include_media_gc_plan: bool = False,
    selector: PptxObjectSelector | None = None,
) -> dict[str, Any]:
    """Return a bounded slide-order-aware view of visible PPTX content."""
    if start_slide < 1:
        raise OfficeOperationError("start_slide must be at least 1")
    if not 1 <= max_slides <= 50:
        raise OfficeOperationError("max_slides must be between 1 and 50")

    package = _load_package_info(data)
    selected = package.slides[start_slide - 1 : start_slide - 1 + max_slides]
    slide_paths_by_part = {slide.part_name: f"/slide[{index}]" for index, slide in enumerate(package.slides, start=1)}
    slides: list[dict[str, Any]] = []
    totals = {
        "shapes": 0,
        "text_boxes": 0,
        "pictures": 0,
        "pictures_without_alt_text": 0,
        "tables": 0,
        "charts": 0,
        "groups": 0,
        "connectors": 0,
        "ole_objects": 0,
    }
    budget = {"characters": 0}
    object_budget = {"returned": 0}
    resource_budget = {"returned": 0}
    interaction_budget = {"returned": 0}
    animation_budget = {"returned": 0}
    formatting_budget = {
        "cells": 0,
        "paragraphs": 0,
        "segments": 0,
        "characters": 0,
    }
    selected_object_count = 0
    selected_matched_object_count = 0
    selected_interaction_count = 0
    selected_matched_interaction_count = 0
    selected_resource_count = 0
    selected_resources_truncated = False
    selected_formatting_truncated = False
    selected_animation_count = 0
    selected_animation_count_truncated = False
    selected_animations_truncated = False
    for slide_index, slide in enumerate(selected, start=start_slide):
        slide_path = f"/slide[{slide_index}]"
        object_refs = _slide_object_refs(slide.root, slide_index=slide_index)
        matched_object_refs = [ref for ref in object_refs if _matches_object_selector(ref, selector)]
        inventory = _slide_inventory(slide, object_refs)
        for key in totals:
            totals[key] += int(inventory[key])
        text_items, text_truncated = _slide_text_items(
            object_refs,
            budget=budget,
        )
        object_capacity = max(0, _MAX_INSPECT_OBJECTS - object_budget["returned"])
        returned_object_refs = matched_object_refs[:object_capacity]
        matched_paths = {ref.path for ref in matched_object_refs}
        returned_paths = {ref.path for ref in returned_object_refs}
        interaction_data: dict[
            str,
            tuple[list[dict[str, Any]], int],
        ] = {}
        slide_interaction_count = 0
        slide_matched_interaction_count = 0
        slide_interactions_returned = 0
        for ref in object_refs:
            record_limit = 0
            if ref.path in returned_paths:
                record_limit = min(
                    _MAX_INTERACTIONS_PER_OBJECT,
                    max(
                        0,
                        _MAX_INSPECT_INTERACTIONS - interaction_budget["returned"],
                    ),
                )
            interactions, interaction_count = _object_interactions(
                ref,
                slide=slide,
                slide_paths_by_part=slide_paths_by_part,
                record_limit=record_limit,
            )
            slide_interaction_count += interaction_count
            if ref.path in matched_paths:
                slide_matched_interaction_count += interaction_count
            if ref.path in returned_paths:
                interaction_data[ref.path] = (
                    interactions,
                    interaction_count,
                )
                interaction_budget["returned"] += len(interactions)
                slide_interactions_returned += len(interactions)
        objects = [
            _object_metadata(
                ref,
                slide=slide,
                package=package,
                interactions=interaction_data[ref.path][0],
                interaction_count=interaction_data[ref.path][1],
                include_formatting=include_formatting,
                formatting_budget=formatting_budget,
            )
            for ref in returned_object_refs
        ]
        object_budget["returned"] += len(objects)
        selected_object_count += len(object_refs)
        selected_matched_object_count += len(matched_object_refs)
        selected_interaction_count += slide_interaction_count
        selected_matched_interaction_count += slide_matched_interaction_count
        selected_formatting_truncated = selected_formatting_truncated or any(item.get("formatting_truncated") is True for item in objects)

        animations: list[dict[str, Any]] = []
        slide_animation_count = 0
        slide_animation_count_truncated = False
        slide_animations_truncated = False
        if include_dynamics:
            animation_capacity = max(
                0,
                _MAX_INSPECT_ANIMATIONS - animation_budget["returned"],
            )
            animations, slide_animation_count, animation_scan_truncated = _slide_animations(
                slide.root,
                slide_path=slide_path,
                object_refs=object_refs,
                record_limit=animation_capacity,
            )
            animation_budget["returned"] += len(animations)
            selected_animation_count += slide_animation_count
            slide_animation_count_truncated = animation_scan_truncated
            selected_animation_count_truncated = selected_animation_count_truncated or slide_animation_count_truncated
            slide_animations_truncated = animation_scan_truncated or len(animations) < slide_animation_count
            selected_animations_truncated = selected_animations_truncated or slide_animations_truncated

        resource_records, resource_graph_truncated = _slide_resources(
            slide,
            slide_index=slide_index,
            object_refs=object_refs,
            package=package,
        )
        resource_capacity = max(
            0,
            _MAX_INSPECT_RESOURCES - resource_budget["returned"],
        )
        resources = resource_records[:resource_capacity]
        resource_budget["returned"] += len(resources)
        selected_resource_count += len(resource_records)
        resources_truncated = resource_graph_truncated or len(resources) < len(resource_records)
        selected_resources_truncated = selected_resources_truncated or resources_truncated
        title = next(
            (item["text"] for item in text_items if item["type"] == "title" and item["text"].strip()),
            None,
        )
        slides.append(
            {
                "index": slide_index,
                "path": slide_path,
                "part_name": slide.part_name,
                **_slide_metadata(slide, path=slide_path),
                "title": title,
                "hidden": (slide.root.get("show") or "1").lower() in {"0", "false", "off"},
                "inventory": inventory,
                "object_count": len(object_refs),
                "matched_object_count": len(matched_object_refs),
                "objects_returned": len(objects),
                "objects_truncated": len(objects) < len(matched_object_refs),
                "objects": objects,
                "interaction_count": slide_interaction_count,
                "matched_interaction_count": (slide_matched_interaction_count),
                "interactions_returned": slide_interactions_returned,
                "interactions_truncated": (slide_interactions_returned < slide_matched_interaction_count),
                "resource_count": len(resource_records),
                "resources_returned": len(resources),
                "resources_truncated": resources_truncated,
                "resources": resources,
                "text": text_items,
                "text_truncated": text_truncated,
                **(
                    {
                        "animation_count": slide_animation_count,
                        "animation_count_truncated": (slide_animation_count_truncated),
                        "animations_returned": len(animations),
                        "animations_truncated": slide_animations_truncated,
                        "animations": animations,
                    }
                    if include_dynamics
                    else {}
                ),
            }
        )

    selected_annotation_count = 0
    selected_annotations_returned = 0
    selected_annotations_truncated = False
    selected_annotation_count_truncated = False
    selected_annotation_authors_truncated = False
    if include_annotations:
        annotations = _inspect_annotations(
            data,
            package=package,
            selected=selected,
            start_slide=start_slide,
            include_formatting=include_formatting,
            formatting_budget=formatting_budget,
        )
        for slide_record in slides:
            slide_annotations = annotations[slide_record["index"]]
            slide_record.update(slide_annotations)
            notes = slide_annotations["notes"]
            comments = slide_annotations["comments"]
            selected_annotation_count += int(notes is not None) + comments["legacy_count"] + comments["modern_thread_count"] + comments["modern_reply_count"]
            selected_annotations_returned += int(notes is not None) + comments["returned"]
            selected_annotations_truncated = selected_annotations_truncated or comments["truncated"] or (notes is not None and notes.get("text_truncated") is True)
            selected_annotation_count_truncated = selected_annotation_count_truncated or comments["count_truncated"]
            selected_annotation_authors_truncated = selected_annotation_authors_truncated or comments["authors_truncated"]
            selected_formatting_truncated = selected_formatting_truncated or (notes is not None and notes.get("formatting_truncated") is True)

    return {
        "format": "pptx",
        "slide_count": len(package.slides),
        "slide_size": {
            "width_emu": package.width_emu,
            "height_emu": package.height_emu,
            "width_inches": round(package.width_emu / 914_400, 4),
            "height_inches": round(package.height_emu / 914_400, 4),
        },
        "start_slide": start_slide,
        "returned": len(slides),
        "has_more": start_slide - 1 + len(slides) < len(package.slides),
        "risky_features": list(package.risky_features),
        "selector_applied": selector is not None,
        "formatting_included": include_formatting,
        "annotations_included": include_annotations,
        "dynamics_included": include_dynamics,
        "media_gc_plan_included": include_media_gc_plan,
        "selected_totals": totals,
        "selected_object_count": selected_object_count,
        "selected_matched_object_count": selected_matched_object_count,
        "selected_objects_returned": object_budget["returned"],
        "selected_objects_truncated": (object_budget["returned"] < selected_matched_object_count),
        "selected_interaction_count": selected_interaction_count,
        "selected_matched_interaction_count": (selected_matched_interaction_count),
        "selected_interactions_returned": interaction_budget["returned"],
        "selected_interactions_truncated": (interaction_budget["returned"] < selected_matched_interaction_count),
        "selected_formatting_truncated": selected_formatting_truncated,
        "selected_annotation_count": selected_annotation_count,
        "selected_annotation_count_truncated": (selected_annotation_count_truncated),
        "selected_annotation_authors_truncated": (selected_annotation_authors_truncated),
        "selected_annotations_returned": selected_annotations_returned,
        "selected_annotations_truncated": selected_annotations_truncated,
        "selected_animation_count": selected_animation_count,
        "selected_animation_count_truncated": (selected_animation_count_truncated),
        "selected_animations_returned": animation_budget["returned"],
        "selected_animations_truncated": selected_animations_truncated,
        "selected_resource_count": selected_resource_count,
        "selected_resources_returned": resource_budget["returned"],
        "selected_resources_truncated": selected_resources_truncated,
        "image_asset_inventory": _image_asset_inventory(package),
        **(
            {
                "media_gc_plan": _pptx_media_gc_plan(
                    data,
                    package=package,
                )
            }
            if include_media_gc_plan
            else {}
        ),
        "slides": slides,
    }


def validate_pptx(data: bytes) -> dict[str, Any]:
    """Validate the supported macro-free PPTX package and relationship graph."""
    package = _load_package_info(data)
    return {
        "valid": True,
        "format": "pptx",
        "entry_count": package.entry_count,
        "slide_count": len(package.slides),
        "risky_features": list(package.risky_features),
    }


def validate_pptx_renderable(data: bytes) -> dict[str, Any]:
    """Validate PPTX and reject active or externally linked content before conversion."""
    validation = validate_pptx(data)
    blocked = [feature for feature in validation["risky_features"] if feature in _RENDER_BLOCKED_FEATURES]
    if blocked:
        raise OfficeOperationError(f"PPTX rendering is disabled for presentations containing {', '.join(blocked)}")
    return validation
