# SPDX-License-Identifier: Apache-2.0
# The run-aware replacement, selector, and formatting designs are adapted from
# OfficeCLI's Word handler.
# See LICENSE.officecli and NOTICE.officecli bundled with this package.
"""Safe, transactional DOCX inspection and literal text replacement."""

from __future__ import annotations

import copy
import io
import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from lxml import etree

from .errors import OfficeOperationError, OfficePackageError
from .models import (
    DocxEditOperation,
    DocxParagraphFormatOperation,
    DocxParagraphFormatting,
    DocxParagraphSelector,
    DocxRunFormatOperation,
    DocxRunFormatting,
    DocxRunSelector,
    DocxTextReplacement,
)
from .opc import enforce_package_preservation

_DOCUMENT_XML = "word/document.xml"
_CONTENT_TYPES_XML = "[Content_Types].xml"
_ROOT_RELATIONSHIPS_XML = "_rels/.rels"
_REQUIRED_ENTRIES = frozenset({_CONTENT_TYPES_XML, _ROOT_RELATIONSHIPS_XML, _DOCUMENT_XML})
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD_2010_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
_NS = {"w": _WORD_NS}
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAIN_DOCUMENT_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_OFFICE_DOCUMENT_RELATIONSHIP_TYPES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument",
    }
)
_DOCUMENT_RELATIONSHIPS_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    }
)

_MAX_PACKAGE_BYTES = 50 * 1024 * 1024
_MAX_ENTRY_COUNT = 5_000
_MAX_ENTRY_BYTES = 50 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 250
_MAX_DOCUMENT_XML_BYTES = 25 * 1024 * 1024
_MAX_CONTROL_XML_BYTES = 1 * 1024 * 1024
_MAX_DOCUMENT_XML_ELEMENTS = 500_000
_MAX_DOCUMENT_PARAGRAPHS = 100_000
_MAX_DOCUMENT_RUNS = 500_000
_MAX_DOCUMENT_TEXT_CHARS = 5_000_000
_MAX_PARAGRAPH_CHARS = 4_000
_MAX_INSPECT_RUNS = 200
_MAX_RUN_CHARS = 500
_RISK_LABEL_ORDER = (
    "digital signatures",
    "macros",
    "external relationships",
    "embedded or ActiveX objects",
)
_RENDER_BLOCKED_FEATURES = frozenset(_RISK_LABEL_ORDER)

_TEXT_BARRIER_TAGS = frozenset(
    {
        "br",
        "commentReference",
        "continuationSeparator",
        "cr",
        "delText",
        "drawing",
        "endnoteReference",
        "fldChar",
        "footnoteReference",
        "instrText",
        "lastRenderedPageBreak",
        "noBreakHyphen",
        "object",
        "pict",
        "ptab",
        "separator",
        "softHyphen",
        "sym",
        "tab",
    }
)
_PROTECTED_TEXT_ANCESTORS = {
    "del": "tracked deletion",
    "fldSimple": "field",
    "ins": "tracked insertion",
    "moveFrom": "tracked move",
    "moveTo": "tracked move",
    "ruby": "ruby annotation",
}


@dataclass(slots=True)
class _Package:
    entries: list[tuple[zipfile.ZipInfo, bytes]]
    comment: bytes
    document: Any
    risky_features: tuple[str, ...]


@dataclass(slots=True)
class _TextSpan:
    element: Any
    start: int
    end: int
    hyperlink_id: int | None
    segment: int
    protected_reason: str | None


def _preflight_document_xml(payload: bytes) -> None:
    parser = etree.XMLPullParser(
        events=("start", "end"),
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    element_count = 0
    paragraph_count = 0
    run_count = 0
    text_characters = 0
    try:
        for offset in range(0, len(payload), 64 * 1024):
            parser.feed(payload[offset : offset + 64 * 1024])
            for event, element in parser.read_events():
                if event == "start":
                    element_count += 1
                    if element.tag == f"{{{_WORD_NS}}}p":
                        paragraph_count += 1
                    elif element.tag == f"{{{_WORD_NS}}}r":
                        run_count += 1
                    if element_count > _MAX_DOCUMENT_XML_ELEMENTS:
                        raise OfficePackageError("DOCX document.xml exceeds the supported element limit")
                    if paragraph_count > _MAX_DOCUMENT_PARAGRAPHS:
                        raise OfficePackageError("DOCX document.xml exceeds the supported paragraph limit")
                    if run_count > _MAX_DOCUMENT_RUNS:
                        raise OfficePackageError("DOCX document.xml exceeds the supported run limit")
                else:
                    text_characters += len(element.text or "") + len(element.tail or "")
                    if text_characters > _MAX_DOCUMENT_TEXT_CHARS:
                        raise OfficePackageError("DOCX document.xml exceeds the supported text limit")
                    element.clear(keep_tail=True)
                    parent = element.getparent()
                    if parent is not None:
                        while element.getprevious() is not None:
                            del parent[0]
        parser.close()
    except OfficePackageError:
        raise
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise OfficePackageError(f"DOCX document.xml is malformed: {exc}") from exc


def _safe_xml_root(payload: bytes) -> Any:
    if len(payload) > _MAX_DOCUMENT_XML_BYTES:
        raise OfficePackageError("DOCX document.xml exceeds the supported size limit")
    if b"<!DOCTYPE" in payload.upper():
        raise OfficePackageError("DOCX document.xml must not contain a document type declaration")
    _preflight_document_xml(payload)
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_blank_text=False,
    )
    try:
        root = etree.fromstring(payload, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise OfficePackageError(f"DOCX document.xml is malformed: {exc}") from exc
    if root.tag != f"{{{_WORD_NS}}}document":
        raise OfficePackageError("DOCX document.xml has an unexpected root element")
    if not root.xpath("./w:body", namespaces=_NS):
        raise OfficePackageError("DOCX document.xml does not contain a body")
    return root


def _safe_control_xml_root(payload: bytes, *, label: str) -> Any:
    if len(payload) > _MAX_CONTROL_XML_BYTES:
        raise OfficePackageError(f"DOCX {label} exceeds the supported size limit")
    if b"<!DOCTYPE" in payload.upper():
        raise OfficePackageError(f"DOCX {label} must not contain a document type declaration")
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
        raise OfficePackageError(f"DOCX {label} is malformed: {exc}") from exc


def _validate_content_types(payload: bytes) -> None:
    root = _safe_control_xml_root(payload, label=_CONTENT_TYPES_XML)
    if root.tag != f"{{{_CONTENT_TYPES_NS}}}Types":
        raise OfficePackageError("DOCX [Content_Types].xml has an unexpected root element")

    overrides = [element for element in root.findall(f"{{{_CONTENT_TYPES_NS}}}Override") if element.get("PartName") == "/word/document.xml"]
    if overrides:
        valid = len(overrides) == 1 and overrides[0].get("ContentType") == _MAIN_DOCUMENT_CONTENT_TYPE
    else:
        defaults = [element for element in root.findall(f"{{{_CONTENT_TYPES_NS}}}Default") if (element.get("Extension") or "").lower() == "xml"]
        valid = len(defaults) == 1 and defaults[0].get("ContentType") == _MAIN_DOCUMENT_CONTENT_TYPE
    if not valid:
        raise OfficePackageError("DOCX content types do not resolve the main Word document part")


def _validate_root_relationships(payload: bytes) -> None:
    root = _safe_control_xml_root(payload, label=_ROOT_RELATIONSHIPS_XML)
    if root.tag != f"{{{_RELATIONSHIPS_NS}}}Relationships":
        raise OfficePackageError("DOCX root relationships have an unexpected root element")
    matches = []
    for relationship in root.findall(f"{{{_RELATIONSHIPS_NS}}}Relationship"):
        if relationship.get("Type") not in _OFFICE_DOCUMENT_RELATIONSHIP_TYPES:
            continue
        if relationship.get("TargetMode", "Internal").lower() == "external":
            raise OfficePackageError("DOCX main document relationship must be internal")
        target = (relationship.get("Target") or "").replace("\\", "/").lstrip("/")
        if target == _DOCUMENT_XML:
            matches.append(relationship)
    if len(matches) != 1:
        raise OfficePackageError("DOCX root relationships do not target one main Word document part")


def _validate_zip_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if name != normalized or normalized.startswith("/") or ".." in path.parts:
        raise OfficePackageError(f"DOCX contains an unsafe package entry: {name}")


def _relationship_source_part(relationship_part: str) -> str | None:
    if relationship_part == _ROOT_RELATIONSHIPS_XML:
        return None
    directory = posixpath.dirname(relationship_part)
    if posixpath.basename(directory) != "_rels":
        raise OfficePackageError(f"DOCX contains an invalid relationships part path: {relationship_part}")
    filename = posixpath.basename(relationship_part)
    if not filename.endswith(".rels") or filename == ".rels":
        raise OfficePackageError(f"DOCX contains an invalid relationships part path: {relationship_part}")
    source_directory = posixpath.dirname(directory)
    return posixpath.join(source_directory, filename[: -len(".rels")])


def _resolve_relationship_target(
    source_part: str | None,
    target: str,
) -> str:
    normalized_target = target.replace("\\", "/")
    if normalized_target.startswith("/"):
        resolved = posixpath.normpath(normalized_target.lstrip("/"))
    else:
        source_directory = "" if source_part is None else posixpath.dirname(source_part)
        resolved = posixpath.normpath(posixpath.join(source_directory, normalized_target))
    if resolved.startswith("../") or resolved in {"", ".", ".."}:
        raise OfficePackageError("DOCX contains an unsafe internal relationship target")
    return resolved


def _risk_labels_for_token(token: str) -> set[str]:
    normalized = token.lower()
    labels: set[str] = set()
    if "digital-signature" in normalized or "xmlsignature" in normalized:
        labels.add("digital signatures")
    if "vbaproject" in normalized or "macroenabled" in normalized:
        labels.add("macros")
    if "oleobject" in normalized or "activex" in normalized or normalized.endswith("/control") or normalized.endswith("/package"):
        labels.add("embedded or ActiveX objects")
    return labels


def _relationship_reference_ids(root: Any) -> set[str]:
    references: set[str] = set()
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        for attribute_name, value in element.attrib.items():
            name = etree.QName(attribute_name)
            if name.namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES and name.localname in {"embed", "id", "link"} and value:
                references.add(value)
    return references


def _relationship_source_root(payload: bytes, *, label: str) -> Any:
    if len(payload) > _MAX_DOCUMENT_XML_BYTES:
        raise OfficePackageError(f"DOCX relationship source {label} exceeds the supported size limit")
    if b"<!DOCTYPE" in payload.upper():
        raise OfficePackageError(f"DOCX relationship source {label} must not contain a document type declaration")
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
        raise OfficePackageError(f"DOCX relationship source {label} is malformed: {exc}") from exc


def _validate_relationship_graph(
    payloads: dict[str, bytes],
    *,
    document: Any,
) -> tuple[str, ...]:
    names = set(payloads)
    normalized_names = {name.lower() for name in names}
    risky_features: set[str] = set()
    if any(name.startswith("_xmlsignatures/") for name in normalized_names):
        risky_features.add("digital signatures")
    if any(name.endswith("vbaproject.bin") for name in normalized_names):
        risky_features.add("macros")
    if any(name.startswith("word/embeddings/") or name.startswith("word/activex/") for name in normalized_names):
        risky_features.add("embedded or ActiveX objects")
    risky_features.update(_risk_labels_for_token(payloads[_CONTENT_TYPES_XML].decode("utf-8", "ignore")))

    relationships_by_source: dict[str | None, dict[str, Any]] = {}
    relationship_parts = sorted(name for name in names if name.lower().endswith(".rels"))
    for relationship_part in relationship_parts:
        source_part = _relationship_source_part(relationship_part)
        if source_part is not None and source_part not in names:
            raise OfficePackageError(f"DOCX relationships part has a missing source: {relationship_part}")
        root = _safe_control_xml_root(
            payloads[relationship_part],
            label=relationship_part,
        )
        if root.tag != f"{{{_RELATIONSHIPS_NS}}}Relationships":
            raise OfficePackageError(f"DOCX {relationship_part} has an unexpected relationships root element")
        by_id: dict[str, Any] = {}
        for relationship in root:
            if not isinstance(relationship.tag, str) or etree.QName(relationship).localname != "Relationship":
                continue
            relationship_id = relationship.get("Id")
            relationship_type = relationship.get("Type")
            target = relationship.get("Target")
            if not relationship_id or relationship_id in by_id:
                raise OfficePackageError(f"DOCX {relationship_part} contains a missing or duplicate relationship ID")
            if not relationship_type or not target:
                raise OfficePackageError(f"DOCX {relationship_part} contains an incomplete relationship")
            by_id[relationship_id] = relationship
            risky_features.update(_risk_labels_for_token(relationship_type))
            target_mode = relationship.get("TargetMode", "Internal").lower()
            if target_mode == "external":
                risky_features.add("external relationships")
            elif target_mode == "internal":
                resolved = _resolve_relationship_target(source_part, target)
                if resolved not in names:
                    raise OfficePackageError(f"DOCX relationship targets a missing package part: {resolved}")
            else:
                raise OfficePackageError(f"DOCX {relationship_part} has an invalid relationship target mode")
        relationships_by_source[source_part] = by_id

    relationship_sources = {name for name in names if name.lower().endswith(".xml")}
    for source_part in sorted(relationship_sources):
        relationships = relationships_by_source.get(source_part, {})
        source_root = (
            document
            if source_part == _DOCUMENT_XML
            else _relationship_source_root(
                payloads[source_part],
                label=source_part,
            )
        )
        missing_references = _relationship_reference_ids(source_root) - relationships.keys()
        if missing_references:
            raise OfficePackageError(f"DOCX {source_part} references missing relationships: {', '.join(sorted(missing_references))}")
    return tuple(label for label in _RISK_LABEL_ORDER if label in risky_features)


def _load_package(data: bytes, *, editable: bool = False) -> _Package:
    if not data:
        raise OfficePackageError("DOCX input is empty")
    if len(data) > _MAX_PACKAGE_BYTES:
        raise OfficePackageError("DOCX input exceeds the 50 MiB package limit")

    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ENTRY_COUNT:
                raise OfficePackageError("DOCX contains too many package entries")

            names: set[str] = set()
            total_uncompressed = 0
            entries: list[tuple[zipfile.ZipInfo, bytes]] = []
            for info in infos:
                _validate_zip_name(info.filename)
                if info.filename in names:
                    raise OfficePackageError(f"DOCX contains a duplicate package entry: {info.filename}")
                names.add(info.filename)
                if info.flag_bits & 0x1:
                    raise OfficePackageError("Encrypted DOCX package entries are not supported")
                if info.file_size > _MAX_ENTRY_BYTES:
                    raise OfficePackageError(f"DOCX package entry is too large: {info.filename}")
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise OfficePackageError("DOCX uncompressed content exceeds the supported limit")
                if info.file_size and info.compress_size == 0:
                    raise OfficePackageError(f"DOCX package entry has an invalid compression ratio: {info.filename}")
                if info.compress_size and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO:
                    raise OfficePackageError(f"DOCX package entry is suspiciously compressed: {info.filename}")
                entries.append((info, archive.read(info)))

            missing = _REQUIRED_ENTRIES - names
            if missing:
                raise OfficePackageError(f"DOCX is missing required package entries: {', '.join(sorted(missing))}")
            payloads = {info.filename: payload for info, payload in entries}
            _validate_content_types(payloads[_CONTENT_TYPES_XML])
            _validate_root_relationships(payloads[_ROOT_RELATIONSHIPS_XML])
            document_payload = payloads[_DOCUMENT_XML]
            document = _safe_xml_root(document_payload)
            risky_features = _validate_relationship_graph(
                payloads,
                document=document,
            )
            if editable and risky_features:
                raise OfficeOperationError(f"DOCX editing is disabled for documents containing {', '.join(risky_features)}")
            return _Package(
                entries=entries,
                comment=archive.comment,
                document=document,
                risky_features=risky_features,
            )
    except (OfficeOperationError, OfficePackageError):
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise OfficePackageError(f"Invalid DOCX package: {exc}") from exc


def _local_name(element: Any) -> str:
    return etree.QName(element).localname


def _body_paragraphs(document: Any) -> list[Any]:
    return [paragraph for paragraph in document.xpath("./w:body//w:p", namespaces=_NS) if not paragraph.xpath("ancestor::w:txbxContent", namespaces=_NS)]


def _is_inside_textbox(element: Any) -> bool:
    parent = element.getparent()
    while parent is not None:
        if parent.tag == f"{{{_WORD_NS}}}txbxContent":
            return True
        parent = parent.getparent()
    return False


def _paragraph_text(paragraph: Any) -> str:
    chunks: list[str] = []
    for node in paragraph.iter():
        if node.xpath("ancestor::w:rt", namespaces=_NS):
            continue
        if node.tag == f"{{{_WORD_NS}}}t" and not _is_inside_textbox(node):
            chunks.append(node.text or "")
        elif node.tag == f"{{{_WORD_NS}}}tab":
            chunks.append("\t")
        elif node.tag in {f"{{{_WORD_NS}}}br", f"{{{_WORD_NS}}}cr"}:
            chunks.append("\n")
    return "".join(chunks)


def _paragraph_context(paragraph: Any) -> str:
    return "table_cell" if paragraph.xpath("ancestor::w:tc", namespaces=_NS) else "body"


def _run_text(run: Any) -> str:
    ruby_base = run.xpath("./w:ruby/w:rubyBase//w:t", namespaces=_NS)
    if ruby_base:
        return "".join(node.text or "" for node in ruby_base)
    return "".join(node.text or "" for node in run.xpath("./w:t", namespaces=_NS))


def _run_is_inside_ruby(run: Any) -> bool:
    return bool(run.xpath("ancestor::w:ruby", namespaces=_NS))


def _run_contains_ruby(run: Any) -> bool:
    return bool(run.xpath("./w:ruby", namespaces=_NS))


def _text_runs(paragraph: Any) -> list[Any]:
    return [run for run in paragraph.xpath(".//w:r", namespaces=_NS) if not _is_inside_textbox(run) and not _run_is_inside_ruby(run) and _run_text(run)]


def _on_off_value(element: Any | None) -> bool | None:
    if element is None:
        return None
    raw = element.get(f"{{{_WORD_NS}}}val")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "off", "no"}


def _run_properties(run: Any) -> Any | None:
    values = run.xpath("./w:rPr", namespaces=_NS)
    return values[0] if values else None


def _run_format_snapshot(run: Any) -> dict[str, Any]:
    properties = _run_properties(run)
    if properties is None:
        return {
            "bold": None,
            "italic": None,
            "underline": None,
            "underline_color": None,
            "strike": None,
            "double_strike": None,
            "all_caps": None,
            "small_caps": None,
            "color": None,
            "highlight": None,
            "font": None,
            "font_ascii": None,
            "font_high_ansi": None,
            "font_east_asia": None,
            "font_complex_script": None,
            "font_size": None,
            "font_size_complex_script": None,
            "vertical_alignment": None,
        }

    def child(name: str) -> Any | None:
        values = properties.xpath(f"./w:{name}", namespaces=_NS)
        return values[0] if values else None

    fonts = child("rFonts")
    font_slots = {
        "font_ascii": fonts.get(f"{{{_WORD_NS}}}ascii") if fonts is not None else None,
        "font_high_ansi": fonts.get(f"{{{_WORD_NS}}}hAnsi") if fonts is not None else None,
        "font_east_asia": fonts.get(f"{{{_WORD_NS}}}eastAsia") if fonts is not None else None,
        "font_complex_script": fonts.get(f"{{{_WORD_NS}}}cs") if fonts is not None else None,
    }
    font = next((value for value in font_slots.values() if value), None)
    size = child("sz")
    raw_size = size.get(f"{{{_WORD_NS}}}val") if size is not None else None
    complex_size = child("szCs")
    raw_complex_size = complex_size.get(f"{{{_WORD_NS}}}val") if complex_size is not None else None
    try:
        font_size = int(raw_size) / 2 if raw_size is not None else None
    except ValueError:
        font_size = None
    try:
        font_size_complex_script = int(raw_complex_size) / 2 if raw_complex_size is not None else None
    except ValueError:
        font_size_complex_script = None
    color = child("color")
    raw_color = color.get(f"{{{_WORD_NS}}}val") if color is not None else None
    underline = child("u")
    raw_underline_color = underline.get(f"{{{_WORD_NS}}}color") if underline is not None else None
    highlight = child("highlight")
    vertical_alignment = child("vertAlign")
    return {
        "bold": _on_off_value(child("b")),
        "italic": _on_off_value(child("i")),
        "underline": underline.get(f"{{{_WORD_NS}}}val") if underline is not None else None,
        "underline_color": f"#{raw_underline_color.upper()}" if raw_underline_color and len(raw_underline_color) == 6 else raw_underline_color,
        "strike": _on_off_value(child("strike")),
        "double_strike": _on_off_value(child("dstrike")),
        "all_caps": _on_off_value(child("caps")),
        "small_caps": _on_off_value(child("smallCaps")),
        "color": f"#{raw_color.upper()}" if raw_color and len(raw_color) == 6 else raw_color,
        "highlight": highlight.get(f"{{{_WORD_NS}}}val") if highlight is not None else None,
        "font": font,
        **font_slots,
        "font_size": font_size,
        "font_size_complex_script": font_size_complex_script,
        "vertical_alignment": vertical_alignment.get(f"{{{_WORD_NS}}}val") if vertical_alignment is not None else None,
    }


def _paragraph_format_snapshot(paragraph: Any) -> dict[str, Any]:
    values = paragraph.xpath("./w:pPr", namespaces=_NS)
    properties = values[0] if values else None
    if properties is None:
        return {
            "alignment": None,
            "space_before": None,
            "space_after": None,
            "left_indent": None,
            "right_indent": None,
            "first_line_indent": None,
            "hanging_indent": None,
            "keep_with_next": None,
            "keep_lines": None,
            "page_break_before": None,
        }

    def child(name: str) -> Any | None:
        values = properties.xpath(f"./w:{name}", namespaces=_NS)
        return values[0] if values else None

    def points(element: Any | None, attribute: str) -> float | None:
        raw = element.get(f"{{{_WORD_NS}}}{attribute}") if element is not None else None
        try:
            return int(raw) / 20 if raw is not None else None
        except ValueError:
            return None

    alignment = child("jc")
    raw_alignment = alignment.get(f"{{{_WORD_NS}}}val") if alignment is not None else None
    spacing = child("spacing")
    indentation = child("ind")
    return {
        "alignment": "justify" if raw_alignment == "both" else raw_alignment,
        "space_before": points(spacing, "before"),
        "space_after": points(spacing, "after"),
        "left_indent": points(indentation, "left"),
        "right_indent": points(indentation, "right"),
        "first_line_indent": points(indentation, "firstLine"),
        "hanging_indent": points(indentation, "hanging"),
        "keep_with_next": _on_off_value(child("keepNext")),
        "keep_lines": _on_off_value(child("keepLines")),
        "page_break_before": _on_off_value(child("pageBreakBefore")),
    }


def inspect_docx(
    data: bytes,
    *,
    start_paragraph: int = 1,
    max_paragraphs: int = 100,
    include_runs: bool = False,
) -> dict[str, Any]:
    """Return a bounded, machine-readable view of DOCX body paragraphs."""
    if start_paragraph < 1:
        raise OfficeOperationError("start_paragraph must be at least 1")
    if not 1 <= max_paragraphs <= 200:
        raise OfficeOperationError("max_paragraphs must be between 1 and 200")

    package = _load_package(data)
    paragraphs = _body_paragraphs(package.document)
    selected = paragraphs[start_paragraph - 1 : start_paragraph - 1 + max_paragraphs]
    result: list[dict[str, Any]] = []
    remaining_runs = _MAX_INSPECT_RUNS
    for offset, paragraph in enumerate(selected, start=start_paragraph):
        text = _paragraph_text(paragraph)
        style_values = paragraph.xpath("./w:pPr/w:pStyle/@w:val", namespaces=_NS)
        paragraph_result = {
            "index": offset,
            "path": f"/document/paragraph[{offset}]",
            "context": _paragraph_context(paragraph),
            "style": style_values[0] if style_values else None,
            "text": text[:_MAX_PARAGRAPH_CHARS],
            "truncated": len(text) > _MAX_PARAGRAPH_CHARS,
            "formatting": _paragraph_format_snapshot(paragraph),
        }
        if include_runs:
            runs = _text_runs(paragraph)
            included = runs[:remaining_runs]
            paragraph_result["runs"] = [
                {
                    "index": run_index,
                    "path": f"/document/paragraph[{offset}]/run[{run_index}]",
                    "text": _run_text(run)[:_MAX_RUN_CHARS],
                    "truncated": len(_run_text(run)) > _MAX_RUN_CHARS,
                    "editable": not _run_contains_ruby(run) and not bool(_protected_text_reason(run)) and not bool(paragraph.xpath(".//w:fldChar | .//w:fldSimple", namespaces=_NS)),
                    "formatting": _run_format_snapshot(run),
                }
                for run_index, run in enumerate(included, start=1)
            ]
            paragraph_result["runs_truncated"] = len(included) < len(runs)
            remaining_runs -= len(included)
        result.append(paragraph_result)

    return {
        "format": "docx",
        "paragraph_count": len(paragraphs),
        "start_paragraph": start_paragraph,
        "returned": len(result),
        "has_more": start_paragraph - 1 + len(result) < len(paragraphs),
        "include_runs": include_runs,
        "risky_features": list(package.risky_features),
        "paragraphs": result,
    }


def _nearest_hyperlink_id(text_element: Any) -> int | None:
    parent = text_element.getparent()
    while parent is not None:
        if parent.tag == f"{{{_WORD_NS}}}hyperlink":
            return id(parent)
        parent = parent.getparent()
    return None


def _protected_text_reason(text_element: Any) -> str | None:
    parent = text_element.getparent()
    while parent is not None:
        reason = _PROTECTED_TEXT_ANCESTORS.get(_local_name(parent))
        if reason is not None:
            return reason
        parent = parent.getparent()
    return None


def _build_text_spans(paragraph: Any) -> tuple[str, list[_TextSpan]]:
    spans: list[_TextSpan] = []
    chunks: list[str] = []
    offset = 0
    segment = 0
    for element in paragraph.iter():
        if element.tag == f"{{{_WORD_NS}}}t" and not _is_inside_textbox(element):
            value = element.text or ""
            chunks.append(value)
            spans.append(
                _TextSpan(
                    element=element,
                    start=offset,
                    end=offset + len(value),
                    hyperlink_id=_nearest_hyperlink_id(element),
                    segment=segment,
                    protected_reason=_protected_text_reason(element),
                )
            )
            offset += len(value)
        elif element.tag.startswith(f"{{{_WORD_NS}}}") and _local_name(element) in _TEXT_BARRIER_TAGS:
            segment += 1
    return "".join(chunks), spans


def _match_ranges(text: str, needle: str, *, first_only: bool) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []
    cursor = 0
    while True:
        start = text.find(needle, cursor)
        if start < 0:
            break
        matches.append((start, start + len(needle)))
        if first_only:
            break
        cursor = start + len(needle)
    return matches


def _replace_in_paragraph(paragraph: Any, needle: str, replacement: str, *, first_only: bool) -> int:
    full_text, spans = _build_text_spans(paragraph)
    matches = _match_ranges(full_text, needle, first_only=first_only)
    if matches and paragraph.xpath(".//w:fldChar | .//w:fldSimple", namespaces=_NS):
        raise OfficeOperationError("Text replacement in a paragraph containing a field is outside the current Office contract")
    for match_start, match_end in reversed(matches):
        affected = [span for span in spans if span.end > match_start and span.start < match_end]
        protected_reasons = {span.protected_reason for span in affected if span.protected_reason is not None}
        if protected_reasons:
            reason = sorted(protected_reasons)[0]
            raise OfficeOperationError(f"Text replacement inside {reason} is outside the current Office contract")
        if len({span.segment for span in affected}) > 1:
            raise OfficeOperationError("Text replacement would cross a semantic document boundary such as a tab, break, field, or drawing")
        hyperlink_ids = {span.hyperlink_id for span in affected}
        if len(hyperlink_ids) > 1:
            raise OfficeOperationError("Text replacement would cross a hyperlink boundary; narrow the find text to one link scope")

        inserted = False
        for span in affected:
            current = span.element.text or ""
            local_start = max(0, match_start - span.start)
            local_end = min(len(current), match_end - span.start)
            prefix = current[:local_start]
            suffix = current[local_end:]
            span.element.text = prefix + (replacement if not inserted else "") + suffix
            span.element.set(_XML_SPACE, "preserve")
            inserted = True
    return len(matches)


def _matches_paragraph_selector(paragraph: Any, index: int, selector: DocxParagraphSelector) -> bool:
    if selector.paragraph_indices is not None and index not in selector.paragraph_indices:
        return False
    text = _paragraph_text(paragraph)
    if selector.contains_text is not None and selector.contains_text not in text:
        return False
    if selector.context is not None and selector.context != _paragraph_context(paragraph):
        return False
    if selector.style is not None:
        style_values = paragraph.xpath("./w:pPr/w:pStyle/@w:val", namespaces=_NS)
        style = style_values[0] if style_values else None
        if style is None or style.casefold() != selector.style.casefold():
            return False
    if selector.alignment is not None and _paragraph_format_snapshot(paragraph)["alignment"] != selector.alignment:
        return False
    return True


def _direct_run_bool(run: Any, name: str) -> bool:
    properties = _run_properties(run)
    if properties is None:
        return False
    values = properties.xpath(f"./w:{name}", namespaces=_NS)
    value = _on_off_value(values[0] if values else None)
    return value is True


def _matches_run_selector(run: Any, index: int, selector: DocxRunSelector | None) -> bool:
    if selector is None:
        return True
    if selector.run_indices is not None and index not in selector.run_indices:
        return False
    if selector.contains_text is not None and selector.contains_text not in _run_text(run):
        return False
    if selector.bold is not None and selector.bold != _direct_run_bool(run, "b"):
        return False
    if selector.italic is not None and selector.italic != _direct_run_bool(run, "i"):
        return False
    snapshot = _run_format_snapshot(run)
    for selector_name, snapshot_name in (
        ("strike", "strike"),
        ("double_strike", "double_strike"),
        ("all_caps", "all_caps"),
        ("small_caps", "small_caps"),
    ):
        expected = getattr(selector, selector_name)
        if expected is not None and expected != (snapshot[snapshot_name] is True):
            return False
    if selector.underline is not None and selector.underline != (snapshot["underline"] or "none"):
        return False
    if selector.highlight is not None and selector.highlight != (snapshot["highlight"] or "none"):
        return False
    if selector.color is not None:
        actual_color = snapshot["color"]
        if actual_color is None or actual_color.removeprefix("#").casefold() != selector.color.removeprefix("#").casefold():
            return False
    for name in ("font", "font_ascii", "font_high_ansi", "font_east_asia", "font_complex_script"):
        expected = getattr(selector, name)
        actual = snapshot[name]
        if expected is not None and (actual is None or actual.casefold() != expected.casefold()):
            return False
    for name in ("font_size", "font_size_complex_script"):
        expected = getattr(selector, name)
        if expected is not None and snapshot[name] != expected:
            return False
    if selector.vertical_alignment is not None and selector.vertical_alignment != (snapshot["vertical_alignment"] or "baseline"):
        return False
    return True


_RUN_PROPERTY_ORDER = {
    name: index
    for index, name in enumerate(
        (
            "rStyle",
            "rFonts",
            "b",
            "bCs",
            "i",
            "iCs",
            "caps",
            "smallCaps",
            "strike",
            "dstrike",
            "outline",
            "shadow",
            "emboss",
            "imprint",
            "noProof",
            "snapToGrid",
            "vanish",
            "webHidden",
            "color",
            "spacing",
            "w",
            "kern",
            "position",
            "sz",
            "szCs",
            "highlight",
            "u",
            "effect",
            "bdr",
            "shd",
            "fitText",
            "vertAlign",
            "rtl",
            "cs",
            "em",
            "lang",
            "eastAsianLayout",
            "specVanish",
            "oMath",
            "rPrChange",
        )
    )
}

_PARAGRAPH_PROPERTY_ORDER = {
    name: index
    for index, name in enumerate(
        (
            "pStyle",
            "keepNext",
            "keepLines",
            "pageBreakBefore",
            "framePr",
            "widowControl",
            "numPr",
            "suppressLineNumbers",
            "pBdr",
            "shd",
            "tabs",
            "suppressAutoHyphens",
            "kinsoku",
            "wordWrap",
            "overflowPunct",
            "topLinePunct",
            "autoSpaceDE",
            "autoSpaceDN",
            "bidi",
            "adjustRightInd",
            "snapToGrid",
            "spacing",
            "ind",
            "contextualSpacing",
            "mirrorIndents",
            "suppressOverlap",
            "jc",
            "textDirection",
            "textAlignment",
            "textboxTightWrap",
            "outlineLvl",
            "divId",
            "cnfStyle",
            "rPr",
            "sectPr",
            "pPrChange",
        )
    )
}


def _word_element(name: str, value: str | None = None) -> Any:
    element = etree.Element(f"{{{_WORD_NS}}}{name}")
    if value is not None:
        element.set(f"{{{_WORD_NS}}}val", value)
    return element


def _set_ordered_property(container: Any, element: Any, order: dict[str, int]) -> None:
    name = _local_name(element)
    for existing in list(container):
        if existing.tag == element.tag:
            container.remove(existing)
    position = order.get(name, len(order))
    first_word_2010_index: int | None = None
    for index, existing in enumerate(container):
        if etree.QName(existing).namespace == _WORD_2010_NS and first_word_2010_index is None:
            first_word_2010_index = index
        existing_name = _local_name(existing)
        if existing_name in order and order[existing_name] > position:
            container.insert(
                min(index, first_word_2010_index) if first_word_2010_index is not None else index,
                element,
            )
            return
    if first_word_2010_index is not None:
        container.insert(first_word_2010_index, element)
        return
    container.append(element)


def _property(container: Any, name: str) -> Any | None:
    values = container.xpath(f"./w:{name}", namespaces=_NS)
    return values[0] if values else None


def _get_or_create_run_properties(run: Any) -> Any:
    properties = _run_properties(run)
    if properties is None:
        properties = _word_element("rPr")
        run.insert(0, properties)
    return properties


def _get_or_create_paragraph_properties(paragraph: Any) -> Any:
    values = paragraph.xpath("./w:pPr", namespaces=_NS)
    if values:
        return values[0]
    properties = _word_element("pPr")
    paragraph.insert(0, properties)
    return properties


def _points_to_twips(value: float) -> str:
    return str(int(round(value * 20)))


def _apply_run_formatting(run: Any, formatting: DocxRunFormatting) -> None:
    properties = _get_or_create_run_properties(run)
    for name in ("bold", "italic", "strike", "double_strike", "all_caps", "small_caps"):
        value = getattr(formatting, name)
        if value is None:
            continue
        xml_name = {
            "bold": "b",
            "italic": "i",
            "strike": "strike",
            "double_strike": "dstrike",
            "all_caps": "caps",
            "small_caps": "smallCaps",
        }[name]
        _set_ordered_property(
            properties,
            _word_element(xml_name, "1" if value else "0"),
            _RUN_PROPERTY_ORDER,
        )
    if formatting.color is not None:
        _set_ordered_property(
            properties,
            _word_element("color", formatting.color.removeprefix("#").upper()),
            _RUN_PROPERTY_ORDER,
        )
    font_updates: dict[str, str] = {}
    if formatting.font is not None:
        font_updates.update(
            ascii=formatting.font,
            hAnsi=formatting.font,
            eastAsia=formatting.font,
        )
    for field_name, slot in (
        ("font_ascii", "ascii"),
        ("font_high_ansi", "hAnsi"),
        ("font_east_asia", "eastAsia"),
        ("font_complex_script", "cs"),
    ):
        if value := getattr(formatting, field_name):
            font_updates[slot] = value
    if font_updates:
        fonts = _property(properties, "rFonts")
        if fonts is None:
            fonts = _word_element("rFonts")
            _set_ordered_property(properties, fonts, _RUN_PROPERTY_ORDER)
        for slot, value in font_updates.items():
            fonts.set(f"{{{_WORD_NS}}}{slot}", value)
    if formatting.font_size is not None:
        half_points = str(int(formatting.font_size * 2))
        size = _property(properties, "sz")
        if size is None:
            size = _word_element("sz")
            _set_ordered_property(properties, size, _RUN_PROPERTY_ORDER)
        size.set(f"{{{_WORD_NS}}}val", half_points)
    if formatting.font_size_complex_script is not None:
        half_points = str(int(formatting.font_size_complex_script * 2))
        size = _property(properties, "szCs")
        if size is None:
            size = _word_element("szCs")
            _set_ordered_property(properties, size, _RUN_PROPERTY_ORDER)
        size.set(f"{{{_WORD_NS}}}val", half_points)
    if formatting.highlight is not None:
        highlight = _property(properties, "highlight")
        if highlight is None:
            highlight = _word_element("highlight")
            _set_ordered_property(properties, highlight, _RUN_PROPERTY_ORDER)
        highlight.set(f"{{{_WORD_NS}}}val", formatting.highlight)
    if formatting.underline is not None:
        underline = _property(properties, "u")
        if underline is None:
            underline = _word_element("u")
            _set_ordered_property(properties, underline, _RUN_PROPERTY_ORDER)
        underline.set(f"{{{_WORD_NS}}}val", formatting.underline)
    if formatting.underline_color is not None:
        underline = _property(properties, "u")
        if underline is None:
            underline = _word_element("u")
            _set_ordered_property(properties, underline, _RUN_PROPERTY_ORDER)
        underline.set(
            f"{{{_WORD_NS}}}color",
            formatting.underline_color.removeprefix("#").upper(),
        )
        for attribute in ("themeColor", "themeTint", "themeShade"):
            underline.attrib.pop(f"{{{_WORD_NS}}}{attribute}", None)
    if formatting.vertical_alignment is not None:
        _set_ordered_property(
            properties,
            _word_element("vertAlign", formatting.vertical_alignment),
            _RUN_PROPERTY_ORDER,
        )


def _apply_paragraph_formatting(paragraph: Any, formatting: DocxParagraphFormatting) -> None:
    properties = _get_or_create_paragraph_properties(paragraph)
    if formatting.alignment is not None:
        alignment = "both" if formatting.alignment == "justify" else formatting.alignment
        _set_ordered_property(properties, _word_element("jc", alignment), _PARAGRAPH_PROPERTY_ORDER)
    for field_name, xml_name in (
        ("keep_with_next", "keepNext"),
        ("keep_lines", "keepLines"),
        ("page_break_before", "pageBreakBefore"),
    ):
        value = getattr(formatting, field_name)
        if value is not None:
            _set_ordered_property(
                properties,
                _word_element(xml_name, "1" if value else "0"),
                _PARAGRAPH_PROPERTY_ORDER,
            )
    if formatting.space_before is not None or formatting.space_after is not None:
        spacing = _property(properties, "spacing")
        if spacing is None:
            spacing = _word_element("spacing")
            _set_ordered_property(properties, spacing, _PARAGRAPH_PROPERTY_ORDER)
        if formatting.space_before is not None:
            spacing.set(f"{{{_WORD_NS}}}before", _points_to_twips(formatting.space_before))
        if formatting.space_after is not None:
            spacing.set(f"{{{_WORD_NS}}}after", _points_to_twips(formatting.space_after))
    indent_values = {
        "left": formatting.left_indent,
        "right": formatting.right_indent,
        "firstLine": formatting.first_line_indent,
        "hanging": formatting.hanging_indent,
    }
    if any(value is not None for value in indent_values.values()):
        indentation = _property(properties, "ind")
        if indentation is None:
            indentation = _word_element("ind")
            _set_ordered_property(properties, indentation, _PARAGRAPH_PROPERTY_ORDER)
        for attribute, value in indent_values.items():
            if value is not None:
                indentation.set(f"{{{_WORD_NS}}}{attribute}", _points_to_twips(value))
        if formatting.first_line_indent is not None:
            indentation.attrib.pop(f"{{{_WORD_NS}}}hanging", None)
        elif formatting.hanging_indent is not None:
            indentation.attrib.pop(f"{{{_WORD_NS}}}firstLine", None)


def _format_runs(document: Any, operation: DocxRunFormatOperation) -> int:
    match_count = 0
    for paragraph_index, paragraph in enumerate(_body_paragraphs(document), start=1):
        if not _matches_paragraph_selector(paragraph, paragraph_index, operation.paragraphs):
            continue
        if paragraph.xpath(".//w:fldChar | .//w:fldSimple", namespaces=_NS):
            raise OfficeOperationError("Run formatting in a paragraph containing a field is outside the current Office contract")
        for run_index, run in enumerate(_text_runs(paragraph), start=1):
            if not _matches_run_selector(run, run_index, operation.runs):
                continue
            if _run_contains_ruby(run):
                raise OfficeOperationError("Run formatting inside a ruby annotation is outside the current Office contract")
            if reason := _protected_text_reason(run):
                raise OfficeOperationError(f"Run formatting inside {reason} is outside the current Office contract")
            _apply_run_formatting(run, operation.formatting)
            match_count += 1
            if operation.occurrence == "first":
                return match_count
    return match_count


def _format_paragraphs(document: Any, operation: DocxParagraphFormatOperation) -> int:
    match_count = 0
    for paragraph_index, paragraph in enumerate(_body_paragraphs(document), start=1):
        if not _matches_paragraph_selector(paragraph, paragraph_index, operation.paragraphs):
            continue
        _apply_paragraph_formatting(paragraph, operation.formatting)
        match_count += 1
        if operation.occurrence == "first":
            break
    return match_count


def _serialize_package(package: _Package) -> bytes:
    document_payload = etree.tostring(
        package.document,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        archive.comment = package.comment
        for original_info, payload in package.entries:
            info = copy.copy(original_info)
            archive.writestr(info, document_payload if info.filename == _DOCUMENT_XML else payload)
    result = output.getvalue()
    if len(result) > _MAX_PACKAGE_BYTES:
        raise OfficePackageError("Edited DOCX exceeds the 50 MiB package limit")
    _load_package(result)
    return result


def edit_docx(data: bytes, operations: list[DocxEditOperation]) -> tuple[bytes, list[dict[str, Any]]]:
    """Apply all operations in memory and serialize once when every operation succeeds."""
    if not operations:
        raise OfficeOperationError("At least one Office edit operation is required")

    package = _load_package(data, editable=True)
    reports: list[dict[str, Any]] = []
    total_match_count = 0
    for operation_index, operation in enumerate(operations, start=1):
        if isinstance(operation, DocxTextReplacement):
            match_count = 0
            for paragraph in _body_paragraphs(package.document):
                count = _replace_in_paragraph(
                    paragraph,
                    operation.find,
                    operation.replace,
                    first_only=operation.occurrence == "first",
                )
                match_count += count
                if operation.occurrence == "first" and count:
                    break
        elif isinstance(operation, DocxRunFormatOperation):
            match_count = _format_runs(package.document, operation)
        elif isinstance(operation, DocxParagraphFormatOperation):
            match_count = _format_paragraphs(package.document, operation)
        else:
            raise OfficeOperationError(f"Unsupported Office operation at position {operation_index}")
        if operation.require_match and match_count == 0:
            raise OfficeOperationError(f"Operation {operation_index} matched no targets; no document changes were written")
        total_match_count += match_count
        reports.append(
            {
                "operation": operation_index,
                "type": operation.type,
                "occurrence": operation.occurrence,
                "match_count": match_count,
            }
        )
    if total_match_count == 0:
        return data, reports
    result = _serialize_package(package)
    enforce_package_preservation(
        data,
        result,
        changed_parts={_DOCUMENT_XML},
        label="DOCX",
    )
    return result, reports


def validate_docx(data: bytes) -> dict[str, Any]:
    """Validate the supported DOCX package and XML invariants."""
    package = _load_package(data)
    return {
        "valid": True,
        "format": "docx",
        "entry_count": len(package.entries),
        "paragraph_count": len(_body_paragraphs(package.document)),
        "risky_features": list(package.risky_features),
    }


def validate_docx_renderable(data: bytes) -> dict[str, Any]:
    """Validate DOCX and reject active or externally linked content."""
    validation = validate_docx(data)
    blocked = [feature for feature in validation["risky_features"] if feature in _RENDER_BLOCKED_FEATURES]
    if blocked:
        raise OfficeOperationError(f"DOCX rendering is disabled for documents containing {', '.join(blocked)}")
    return validation
