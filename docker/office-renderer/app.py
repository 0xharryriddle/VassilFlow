"""Isolated Office-to-PNG renderer for VassilFlow visual QA."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import math
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import pypdfium2 as pdfium
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("vassilflow.office_renderer")

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_REQUEST_BYTES = 50 * 1024 * 1024
_MAX_ENTRY_COUNT = 5_000
_MAX_ENTRY_BYTES = 50 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 250
_MAX_WORKSHEET_XML_BYTES = 35 * 1024 * 1024
_MAX_DECLARED_CELLS_PER_SHEET = 100_000
_MAX_DECLARED_CELLS = 200_000
_MAX_PPTX_SLIDE_XML_BYTES = 20 * 1024 * 1024
_MAX_PPTX_SLIDES = 1_000
_MAX_PPTX_OBJECTS_PER_SLIDE = 5_000
_MAX_PPTX_OBJECTS = 100_000
_MAX_PPTX_TEXT_NODES = 100_000
_MAX_PPTX_TEXT_CHARS = 5_000_000
_MAX_PAGE_BYTES = 12 * 1024 * 1024
_MAX_TOTAL_PAGE_BYTES = 48 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_MAX_PAGES_PER_REQUEST = 12
_CONVERSION_TIMEOUT_SECONDS = 60
_RASTER_TIMEOUT_SECONDS = 45
_RASTER_WORK_TIMEOUT_SECONDS = 40
_QUEUE_TIMEOUT_SECONDS = 5
_MAX_RASTER_DIMENSION = 10_000
_MAX_RASTER_PIXELS = 40_000_000
_CONTENT_TYPES_XML = "[Content_Types].xml"
_ROOT_RELATIONSHIPS_XML = "_rels/.rels"
_DOCUMENT_XML = "word/document.xml"
_REQUIRED_ENTRIES = frozenset({_CONTENT_TYPES_XML, _ROOT_RELATIONSHIPS_XML, _DOCUMENT_XML})
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAIN_DOCUMENT_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_WORKBOOK_XML = "xl/workbook.xml"
_WORKBOOK_RELATIONSHIPS_XML = "xl/_rels/workbook.xml.rels"
_STYLES_XML = "xl/styles.xml"
_XLSX_REQUIRED_ENTRIES = frozenset(
    {
        _CONTENT_TYPES_XML,
        _ROOT_RELATIONSHIPS_XML,
        _WORKBOOK_XML,
        _WORKBOOK_RELATIONSHIPS_XML,
    }
)
_MAIN_WORKBOOK_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
_SPREADSHEET_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "http://purl.oclc.org/ooxml/spreadsheetml/main",
    }
)
_OFFICE_DOCUMENT_RELATIONSHIP_TYPES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument",
    }
)
_WORKSHEET_RELATIONSHIP_TYPES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
        "http://purl.oclc.org/ooxml/officeDocument/relationships/worksheet",
    }
)
_PRESENTATION_XML = "ppt/presentation.xml"
_PRESENTATION_RELATIONSHIPS_XML = "ppt/_rels/presentation.xml.rels"
_PPTX_REQUIRED_ENTRIES = frozenset(
    {
        _CONTENT_TYPES_XML,
        _ROOT_RELATIONSHIPS_XML,
        _PRESENTATION_XML,
        _PRESENTATION_RELATIONSHIPS_XML,
    }
)
_PRESENTATION_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/presentationml/2006/main",
        "http://purl.oclc.org/ooxml/presentationml/main",
    }
)
_DRAWING_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/drawingml/2006/main",
        "http://purl.oclc.org/ooxml/drawingml/main",
    }
)
_DOCUMENT_RELATIONSHIPS_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    }
)
_SLIDE_RELATIONSHIP_TYPES = frozenset(f"{namespace}/slide" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
_HYPERLINK_RELATIONSHIP_TYPES = frozenset(f"{namespace}/hyperlink" for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES)
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
_SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")
_RENDER_SLOTS = asyncio.Semaphore(1)
_RASTER_WORKER_FLAG = "--raster-worker"
_XLSX_RENDER_BLOCKED_FEATURES = frozenset(
    {
        "digital signatures",
        "macros",
        "external workbook links",
        "data connections",
        "embedded or ActiveX objects",
    }
)
_PPTX_RENDER_BLOCKED_FEATURES = frozenset(
    {
        "digital signatures",
        "embedded or ActiveX objects",
        "external relationships",
        "macros",
        "unsafe actions",
    }
)
_PIPELINE_CONTRACT_VERSION = "2"
_CONVERSION_FILTERS = {
    "docx": "pdf:writer_pdf_Export",
    "pptx": ('pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}'),
    "xlsx": "pdf:calc_pdf_Export",
}

app = FastAPI(
    title="VassilFlow Office Renderer",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@dataclass(frozen=True, slots=True)
class _RenderedPage:
    page: int
    filename: str
    width: int
    height: int
    sha256: str
    data: bytes


def _validate_package_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if name != normalized or normalized.startswith("/") or ".." in path.parts:
        raise ValueError("DOCX contains an unsafe package entry")


def _control_xml_root(payload: bytes, *, label: str) -> ET.Element:
    if len(payload) > 1024 * 1024:
        raise ValueError(f"DOCX {label} exceeds the supported size limit")
    if b"<!DOCTYPE" in payload.upper():
        raise ValueError(f"DOCX {label} must not contain a document type declaration")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"DOCX {label} is malformed") from exc


def _validate_package_controls(archive: zipfile.ZipFile) -> None:
    content_types = _control_xml_root(archive.read(_CONTENT_TYPES_XML), label=_CONTENT_TYPES_XML)
    if content_types.tag != f"{{{_CONTENT_TYPES_NS}}}Types":
        raise ValueError("DOCX [Content_Types].xml has an unexpected root element")
    overrides = [element for element in content_types.findall(f"{{{_CONTENT_TYPES_NS}}}Override") if element.get("PartName") == "/word/document.xml"]
    if overrides:
        valid = len(overrides) == 1 and overrides[0].get("ContentType") == _MAIN_DOCUMENT_CONTENT_TYPE
    else:
        defaults = [element for element in content_types.findall(f"{{{_CONTENT_TYPES_NS}}}Default") if (element.get("Extension") or "").lower() == "xml"]
        valid = len(defaults) == 1 and defaults[0].get("ContentType") == _MAIN_DOCUMENT_CONTENT_TYPE
    if not valid:
        raise ValueError("DOCX content types do not resolve the main Word document part")

    relationships = _control_xml_root(
        archive.read(_ROOT_RELATIONSHIPS_XML),
        label=_ROOT_RELATIONSHIPS_XML,
    )
    if relationships.tag != f"{{{_RELATIONSHIPS_NS}}}Relationships":
        raise ValueError("DOCX root relationships have an unexpected root element")
    matches = []
    for relationship in relationships.findall(f"{{{_RELATIONSHIPS_NS}}}Relationship"):
        if relationship.get("Type") not in _OFFICE_DOCUMENT_RELATIONSHIP_TYPES:
            continue
        if relationship.get("TargetMode", "Internal").lower() == "external":
            raise ValueError("DOCX main document relationship must be internal")
        target = (relationship.get("Target") or "").replace("\\", "/").lstrip("/")
        if target == _DOCUMENT_XML:
            matches.append(relationship)
    if len(matches) != 1:
        raise ValueError("DOCX root relationships do not target one main Word document part")


def _validate_docx(document: bytes) -> None:
    if not document:
        raise ValueError("DOCX input is empty")
    if len(document) > _MAX_REQUEST_BYTES:
        raise ValueError("DOCX input exceeds the 50 MiB package limit")

    try:
        with zipfile.ZipFile(io.BytesIO(document), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ENTRY_COUNT:
                raise ValueError("DOCX contains too many package entries")

            names: set[str] = set()
            total_uncompressed = 0
            for info in infos:
                _validate_package_name(info.filename)
                if info.filename in names:
                    raise ValueError("DOCX contains duplicate package entries")
                names.add(info.filename)
                if info.flag_bits & 0x1:
                    raise ValueError("Encrypted DOCX package entries are not supported")
                if info.file_size > _MAX_ENTRY_BYTES:
                    raise ValueError("DOCX contains an oversized package entry")
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("DOCX uncompressed content exceeds the supported limit")
                if info.file_size and info.compress_size == 0:
                    raise ValueError("DOCX contains an invalid compressed package entry")
                if info.compress_size and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO:
                    raise ValueError("DOCX contains a suspiciously compressed package entry")

            if _REQUIRED_ENTRIES - names:
                raise ValueError("DOCX is missing required package entries")
            _validate_package_controls(archive)
    except zipfile.BadZipFile as exc:
        raise ValueError("DOCX input is not a valid ZIP package") from exc


def _validate_xlsx_package_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if name != normalized or normalized.startswith("/") or ".." in path.parts:
        raise ValueError("XLSX contains an unsafe package entry")


def _xlsx_relationship_target(target: str) -> str:
    normalized_target = target.replace("\\", "/")
    if normalized_target.startswith("/"):
        normalized = posixpath.normpath(normalized_target.lstrip("/"))
    else:
        normalized = posixpath.normpath(posixpath.join("xl", normalized_target))
    if normalized.startswith("../") or normalized in {"", ".", ".."}:
        raise ValueError("XLSX workbook contains an unsafe worksheet relationship")
    return normalized


def _validate_xlsx_controls(
    archive: zipfile.ZipFile,
    names: set[str],
) -> set[str]:
    content_types_payload = archive.read(_CONTENT_TYPES_XML)
    if len(content_types_payload) > 2 * 1024 * 1024 or b"<!DOCTYPE" in content_types_payload.upper():
        raise ValueError("XLSX content types exceed the supported contract")
    try:
        content_types = ET.fromstring(content_types_payload)
    except ET.ParseError as exc:
        raise ValueError("XLSX content types are malformed") from exc
    if content_types.tag != f"{{{_CONTENT_TYPES_NS}}}Types":
        raise ValueError("XLSX [Content_Types].xml has an unexpected root element")
    overrides = [element for element in content_types.findall(f"{{{_CONTENT_TYPES_NS}}}Override") if element.get("PartName") == "/xl/workbook.xml"]
    if overrides:
        valid = len(overrides) == 1 and overrides[0].get("ContentType") == _MAIN_WORKBOOK_CONTENT_TYPE
    else:
        defaults = [element for element in content_types.findall(f"{{{_CONTENT_TYPES_NS}}}Default") if (element.get("Extension") or "").lower() == "xml"]
        valid = len(defaults) == 1 and defaults[0].get("ContentType") == _MAIN_WORKBOOK_CONTENT_TYPE
    if not valid:
        raise ValueError("XLSX content types do not resolve a standard macro-free workbook part")

    relationships_payload = archive.read(_ROOT_RELATIONSHIPS_XML)
    if len(relationships_payload) > 1024 * 1024 or b"<!DOCTYPE" in relationships_payload.upper():
        raise ValueError("XLSX root relationships exceed the supported contract")
    try:
        relationships = ET.fromstring(relationships_payload)
    except ET.ParseError as exc:
        raise ValueError("XLSX root relationships are malformed") from exc
    if relationships.tag != f"{{{_RELATIONSHIPS_NS}}}Relationships":
        raise ValueError("XLSX root relationships have an unexpected root element")
    matches = []
    for relationship in relationships.findall(f"{{{_RELATIONSHIPS_NS}}}Relationship"):
        if relationship.get("Type") not in _OFFICE_DOCUMENT_RELATIONSHIP_TYPES:
            continue
        if relationship.get("TargetMode", "Internal").lower() == "external":
            raise ValueError("XLSX workbook relationship must be internal")
        target = (relationship.get("Target") or "").replace("\\", "/").lstrip("/")
        if target == _WORKBOOK_XML:
            matches.append(relationship)
    if len(matches) != 1:
        raise ValueError("XLSX root relationships do not target one workbook part")

    workbook_payload = archive.read(_WORKBOOK_XML)
    if len(workbook_payload) > 2 * 1024 * 1024 or b"<!DOCTYPE" in workbook_payload.upper():
        raise ValueError("XLSX workbook.xml exceeds the supported contract")
    try:
        workbook = ET.fromstring(workbook_payload)
    except ET.ParseError as exc:
        raise ValueError("XLSX workbook.xml is malformed") from exc
    namespace, _, local_name = workbook.tag[1:].partition("}") if workbook.tag.startswith("{") else ("", "", workbook.tag)
    if local_name != "workbook" or namespace not in _SPREADSHEET_NAMESPACES:
        raise ValueError("XLSX workbook.xml has an unexpected root element")
    if not any(child.tag.endswith("}sheets") and len(child) for child in workbook):
        raise ValueError("XLSX workbook.xml does not contain a worksheet")

    workbook_relationships_payload = archive.read(_WORKBOOK_RELATIONSHIPS_XML)
    if len(workbook_relationships_payload) > 2 * 1024 * 1024 or b"<!DOCTYPE" in workbook_relationships_payload.upper():
        raise ValueError("XLSX workbook relationships exceed the supported contract")
    try:
        workbook_relationships = ET.fromstring(workbook_relationships_payload)
    except ET.ParseError as exc:
        raise ValueError("XLSX workbook relationships are malformed") from exc
    if workbook_relationships.tag != f"{{{_RELATIONSHIPS_NS}}}Relationships":
        raise ValueError("XLSX workbook relationships have an unexpected root element")

    relationships_by_id: dict[str, ET.Element] = {}
    for relationship in workbook_relationships:
        if relationship.tag.rpartition("}")[2] != "Relationship":
            continue
        relationship_id = relationship.get("Id")
        if not relationship_id or relationship_id in relationships_by_id:
            raise ValueError("XLSX workbook relationships contain a missing or duplicate ID")
        relationships_by_id[relationship_id] = relationship

    worksheet_parts: set[str] = set()
    sheet_names: set[str] = set()
    for sheet in workbook.iter():
        if sheet.tag.rpartition("}")[2] != "sheet":
            continue
        sheet_name = sheet.get("name")
        relationship_id = next(
            (value for key, value in sheet.attrib.items() if key.rpartition("}")[2] == "id"),
            None,
        )
        if not sheet_name or not relationship_id or relationship_id not in relationships_by_id:
            raise ValueError("XLSX workbook contains a sheet without one relationship")
        folded_name = sheet_name.casefold()
        if folded_name in sheet_names:
            raise ValueError("XLSX workbook contains duplicate worksheet names")
        sheet_names.add(folded_name)

        relationship = relationships_by_id[relationship_id]
        if relationship.get("TargetMode", "Internal").lower() == "external":
            raise ValueError("XLSX worksheet relationship must be internal")
        target = relationship.get("Target")
        if not target:
            raise ValueError("XLSX worksheet relationship is missing a target")
        part_name = _xlsx_relationship_target(target)
        if part_name not in names:
            raise ValueError("XLSX worksheet relationship targets a missing package part")
        if relationship.get("Type") not in _WORKSHEET_RELATIONSHIP_TYPES:
            continue
        if part_name in worksheet_parts:
            raise ValueError("XLSX worksheets must not share one package part")
        worksheet_parts.add(part_name)
    return worksheet_parts


def _xlsx_risk_labels_for_token(token: str) -> set[str]:
    normalized = token.lower()
    labels: set[str] = set()
    if "digital-signature" in normalized or "xmlsignature" in normalized:
        labels.add("digital signatures")
    if "vbaproject" in normalized or "macroenabled" in normalized or "macrosheet" in normalized:
        labels.add("macros")
    if "externallink" in normalized:
        labels.add("external workbook links")
    if "connections" in normalized or "querytable" in normalized:
        labels.add("data connections")
    if "oleobject" in normalized or "activex" in normalized or normalized.endswith("/control"):
        labels.add("embedded or ActiveX objects")
    return labels


def _detect_xlsx_render_risks(
    archive: zipfile.ZipFile,
    names: set[str],
) -> set[str]:
    normalized_names = {name.lower() for name in names}
    labels: set[str] = set()
    if any(name.startswith("_xmlsignatures/") for name in normalized_names):
        labels.add("digital signatures")
    if any(name.endswith("vbaproject.bin") or name.startswith("xl/macrosheets/") for name in normalized_names):
        labels.add("macros")
    if any(name.startswith("xl/externallinks/") for name in normalized_names):
        labels.add("external workbook links")
    if any(name == "xl/connections.xml" or name.startswith("xl/querytables/") for name in normalized_names):
        labels.add("data connections")
    if any(name.startswith("xl/embeddings/") or name.startswith("xl/activex/") for name in normalized_names):
        labels.add("embedded or ActiveX objects")

    content_types = ET.fromstring(archive.read(_CONTENT_TYPES_XML))
    for element in content_types:
        content_type = element.get("ContentType")
        if content_type:
            labels.update(_xlsx_risk_labels_for_token(content_type))

    for name in sorted(candidate for candidate in names if candidate.lower().endswith(".rels")):
        payload = archive.read(name)
        if len(payload) > 2 * 1024 * 1024 or b"<!DOCTYPE" in payload.upper():
            raise ValueError(f"XLSX {name} exceeds the supported contract")
        try:
            relationships = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ValueError(f"XLSX {name} is malformed") from exc
        if relationships.tag != f"{{{_RELATIONSHIPS_NS}}}Relationships":
            raise ValueError(f"XLSX {name} has an unexpected relationships root element")
        for relationship in relationships:
            relationship_type = relationship.get("Type")
            if relationship_type:
                labels.update(_xlsx_risk_labels_for_token(relationship_type))
    return labels & _XLSX_RENDER_BLOCKED_FEATURES


def _count_xlsx_declared_cells(payload: bytes, *, label: str) -> int:
    if len(payload) > _MAX_WORKSHEET_XML_BYTES or b"<!DOCTYPE" in payload.upper():
        raise ValueError(f"XLSX {label} exceeds the supported contract")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"XLSX {label} is malformed") from exc

    namespace, _, local_name = root.tag[1:].partition("}") if root.tag.startswith("{") else ("", "", root.tag)
    if local_name != "worksheet" or namespace not in _SPREADSHEET_NAMESPACES:
        raise ValueError(f"XLSX {label} has an unexpected worksheet root element")

    count = 0
    for element in root.iter():
        local_name = element.tag.rpartition("}")[2]
        if local_name != "c":
            continue
        count += 1
        if count > _MAX_DECLARED_CELLS_PER_SHEET:
            raise ValueError(f"XLSX {label} declares more than {_MAX_DECLARED_CELLS_PER_SHEET:,} cells")
    return count


def _validate_xlsx_number_format(format_code: str) -> None:
    if len(format_code) > 255 or any(ord(char) < 32 for char in format_code):
        raise ValueError("XLSX number format exceeds the supported contract")
    in_quote = False
    bracket_depth = 0
    section_count = 1
    index = 0
    while index < len(format_code):
        char = format_code[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            in_quote = not in_quote
        elif not in_quote and char == "[":
            bracket_depth += 1
        elif not in_quote and char == "]":
            bracket_depth -= 1
            if bracket_depth < 0:
                raise ValueError("XLSX number format has unbalanced square brackets")
        elif not in_quote and bracket_depth == 0 and char == ";":
            section_count += 1
        index += 1
    if in_quote:
        raise ValueError("XLSX number format has unbalanced double quotes")
    if bracket_depth:
        raise ValueError("XLSX number format has unbalanced square brackets")
    if section_count > 4:
        raise ValueError("XLSX number format has more than four sections")


def _validate_xlsx_styles(archive: zipfile.ZipFile, names: set[str]) -> None:
    if _STYLES_XML not in names:
        return
    payload = archive.read(_STYLES_XML)
    if len(payload) > 8 * 1024 * 1024 or b"<!DOCTYPE" in payload.upper():
        raise ValueError("XLSX styles.xml exceeds the supported contract")
    try:
        styles = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("XLSX styles.xml is malformed") from exc
    namespace, _, local_name = styles.tag[1:].partition("}") if styles.tag.startswith("{") else ("", "", styles.tag)
    if local_name != "styleSheet" or namespace not in _SPREADSHEET_NAMESPACES:
        raise ValueError("XLSX styles.xml has an unexpected root element")
    for element in styles.iter():
        if element.tag.rpartition("}")[2] != "numFmt":
            continue
        format_code = element.get("formatCode")
        if format_code is None:
            raise ValueError("XLSX custom number format is missing formatCode")
        _validate_xlsx_number_format(format_code)


def _validate_xlsx(document: bytes) -> None:
    if not document:
        raise ValueError("XLSX input is empty")
    if len(document) > _MAX_REQUEST_BYTES:
        raise ValueError("XLSX input exceeds the 50 MiB package limit")

    try:
        with zipfile.ZipFile(io.BytesIO(document), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ENTRY_COUNT:
                raise ValueError("XLSX contains too many package entries")

            names: set[str] = set()
            total_uncompressed = 0
            for info in infos:
                _validate_xlsx_package_name(info.filename)
                if info.filename in names:
                    raise ValueError("XLSX contains duplicate package entries")
                names.add(info.filename)
                if info.flag_bits & 0x1:
                    raise ValueError("Encrypted XLSX package entries are not supported")
                if info.file_size > _MAX_ENTRY_BYTES:
                    raise ValueError("XLSX contains an oversized package entry")
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("XLSX uncompressed content exceeds the supported limit")
                if info.file_size and info.compress_size == 0:
                    raise ValueError("XLSX contains an invalid compressed package entry")
                if info.compress_size and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO:
                    raise ValueError("XLSX contains a suspiciously compressed package entry")

            if _XLSX_REQUIRED_ENTRIES - names:
                raise ValueError("XLSX is missing required package entries")
            worksheet_parts = _validate_xlsx_controls(archive, names)
            render_risks = _detect_xlsx_render_risks(archive, names)
            if render_risks:
                raise ValueError(f"XLSX rendering is disabled for workbooks containing {', '.join(sorted(render_risks))}")
            _validate_xlsx_styles(archive, names)
            declared_cells = 0
            for name in sorted(worksheet_parts):
                declared_cells += _count_xlsx_declared_cells(
                    archive.read(name),
                    label=name,
                )
                if declared_cells > _MAX_DECLARED_CELLS:
                    raise ValueError(f"XLSX worksheets declare more than {_MAX_DECLARED_CELLS:,} cells in total")
    except zipfile.BadZipFile as exc:
        raise ValueError("XLSX input is not a valid ZIP package") from exc


def _pptx_xml_root(payload: bytes, *, label: str, limit: int = 2 * 1024 * 1024) -> ET.Element:
    if len(payload) > limit:
        raise ValueError(f"PPTX {label} exceeds the supported size limit")
    if b"<!DOCTYPE" in payload.upper():
        raise ValueError(f"PPTX {label} must not contain a document type declaration")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"PPTX {label} is malformed") from exc


def _pptx_xml_name(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        namespace, _, local_name = tag[1:].partition("}")
        return namespace, local_name
    return "", tag


def _pptx_relationship_part_name(part_name: str) -> str:
    parent, filename = posixpath.split(part_name)
    return posixpath.join(parent, "_rels", f"{filename}.rels")


def _pptx_relationship_source_part(relationship_part: str) -> str:
    if relationship_part == _ROOT_RELATIONSHIPS_XML:
        return ""
    parent, filename = posixpath.split(relationship_part)
    if posixpath.basename(parent) != "_rels" or not filename.endswith(".rels"):
        raise ValueError(f"PPTX contains an invalid relationship part: {relationship_part}")
    source_filename = filename[: -len(".rels")]
    if not source_filename:
        raise ValueError(f"PPTX contains an invalid relationship part: {relationship_part}")
    return posixpath.join(posixpath.dirname(parent), source_filename)


def _pptx_relationship_target(source_part: str, target: str) -> str:
    if not target or "\\" in target or "\x00" in target:
        raise ValueError(f"PPTX {source_part} has an unsafe relationship target")
    target_path = target.split("#", 1)[0]
    if not target_path:
        raise ValueError(f"PPTX {source_part} has an empty internal relationship target")
    if target_path.startswith("/"):
        resolved = posixpath.normpath(target_path.lstrip("/"))
    else:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target_path))
    if resolved in {"", ".", ".."} or resolved.startswith("../"):
        raise ValueError(f"PPTX {source_part} has a relationship outside the package")
    return resolved


def _pptx_relationships(
    payload: bytes,
    *,
    label: str,
) -> dict[str, tuple[str, str, bool]]:
    root = _pptx_xml_root(payload, label=label)
    if root.tag != f"{{{_RELATIONSHIPS_NS}}}Relationships":
        raise ValueError(f"PPTX {label} has an unexpected relationships root element")
    relationships: dict[str, tuple[str, str, bool]] = {}
    for element in root:
        if _pptx_xml_name(element.tag)[1] != "Relationship":
            continue
        relationship_id = element.get("Id") or ""
        relationship_type = element.get("Type") or ""
        target = element.get("Target") or ""
        if not relationship_id or relationship_id in relationships:
            raise ValueError(f"PPTX {label} contains a missing or duplicate relationship ID")
        if not relationship_type or not target:
            raise ValueError(f"PPTX {label} contains an incomplete relationship")
        relationships[relationship_id] = (
            relationship_type,
            target,
            element.get("TargetMode", "Internal").lower() == "external",
        )
    return relationships


def _pptx_risk_labels(token: str) -> set[str]:
    normalized = token.lower().replace("-", "").replace("_", "")
    labels: set[str] = set()
    if "vba" in normalized or "macroenabled" in normalized:
        labels.add("macros")
    if "digitalsignature" in normalized or "xmlsignatures" in normalized or "originsigs" in normalized:
        labels.add("digital signatures")
    if any(marker in normalized for marker in ("activex", "oleobject", "embeddedobject", "embeddedpackage", "embeddings/")):
        labels.add("embedded or ActiveX objects")
    return labels


def _pptx_relationship_risks(
    relationships: dict[str, tuple[str, str, bool]],
) -> set[str]:
    labels: set[str] = set()
    for relationship_type, target, external in relationships.values():
        labels.update(_pptx_risk_labels(relationship_type))
        labels.update(_pptx_risk_labels(target))
        if external:
            labels.add("external hyperlinks" if _pptx_is_safe_external_hyperlink(relationship_type, target) else "external relationships")
    return labels


def _pptx_is_safe_external_hyperlink(relationship_type: str, target: str) -> bool:
    if relationship_type not in _HYPERLINK_RELATIONSHIP_TYPES:
        return False
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


def _pptx_validate_internal_targets(
    source_part: str,
    relationships: dict[str, tuple[str, str, bool]],
    names: set[str],
) -> None:
    for relationship_id, (_, target, external) in relationships.items():
        if external:
            continue
        if _pptx_relationship_target(source_part, target) not in names:
            source_label = source_part or "package root"
            raise ValueError(f"PPTX {source_label} relationship {relationship_id} targets a missing part")


def _pptx_slide_relationship_id(element: ET.Element) -> str | None:
    for namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES:
        value = element.get(f"{{{namespace}}}id")
        if value is not None:
            return value
    return None


def _pptx_validate_references(
    slide: ET.Element,
    relationships: dict[str, tuple[str, str, bool]],
    *,
    label: str,
) -> None:
    for element in slide.iter():
        for attribute_name, relationship_id in element.attrib.items():
            namespace, local_name = _pptx_xml_name(attribute_name)
            if namespace in _DOCUMENT_RELATIONSHIPS_NAMESPACES and local_name in {"embed", "id", "link"} and relationship_id and relationship_id not in relationships:
                raise ValueError(f"PPTX {label} references missing relationship {relationship_id}")


def _pptx_action_risks(
    slide: ET.Element,
    relationships: dict[str, tuple[str, str, bool]],
    *,
    label: str,
) -> set[str]:
    labels: set[str] = set()
    for element in slide.iter():
        action = element.get("action")
        if action is None:
            continue
        normalized = action.strip().lower()
        relationship_id = _pptx_slide_relationship_id(element)
        if normalized == _SLIDE_JUMP_ACTION:
            relationship = relationships.get(relationship_id or "")
            if relationship is None or relationship[2] or relationship[0] not in _SLIDE_RELATIONSHIP_TYPES:
                raise ValueError(f"PPTX {label} contains an invalid slide-jump action relationship")
        elif normalized not in _RELATIONSHIP_FREE_ACTIONS or relationship_id:
            labels.add("unsafe actions")
    return labels


def _validate_pptx(document: bytes) -> int:
    if not document:
        raise ValueError("PPTX input is empty")
    if len(document) > _MAX_REQUEST_BYTES:
        raise ValueError("PPTX input exceeds the 50 MiB package limit")

    try:
        with zipfile.ZipFile(io.BytesIO(document), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ENTRY_COUNT:
                raise ValueError("PPTX contains too many package entries")
            names: set[str] = set()
            risky_features: set[str] = set()
            total_uncompressed = 0
            for info in infos:
                normalized = info.filename.replace("\\", "/")
                path = PurePosixPath(normalized)
                if info.filename != normalized or normalized.startswith("/") or ".." in path.parts:
                    raise ValueError("PPTX contains an unsafe package entry")
                if info.filename in names:
                    raise ValueError("PPTX contains duplicate package entries")
                names.add(info.filename)
                risky_features.update(_pptx_risk_labels(info.filename))
                if info.flag_bits & 0x1:
                    raise ValueError("Encrypted PPTX package entries are not supported")
                if info.file_size > _MAX_ENTRY_BYTES:
                    raise ValueError("PPTX contains an oversized package entry")
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("PPTX uncompressed content exceeds the supported limit")
                if info.file_size and info.compress_size == 0:
                    raise ValueError("PPTX contains an invalid compressed package entry")
                if info.compress_size and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO:
                    raise ValueError("PPTX contains a suspiciously compressed package entry")

            if _PPTX_REQUIRED_ENTRIES - names:
                raise ValueError("PPTX is missing required package entries")

            content_types_payload = archive.read(_CONTENT_TYPES_XML)
            content_types = _pptx_xml_root(
                content_types_payload,
                label=_CONTENT_TYPES_XML,
            )
            if content_types.tag != f"{{{_CONTENT_TYPES_NS}}}Types":
                raise ValueError("PPTX [Content_Types].xml has an unexpected root element")
            defaults: dict[str, str] = {}
            overrides: dict[str, str] = {}
            for element in content_types:
                local_name = _pptx_xml_name(element.tag)[1]
                if local_name == "Default":
                    key = (element.get("Extension") or "").lower()
                    value = element.get("ContentType") or ""
                    if not key or not value or key in defaults:
                        raise ValueError("PPTX [Content_Types].xml contains an invalid default")
                    defaults[key] = value
                elif local_name == "Override":
                    key = (element.get("PartName") or "").lstrip("/")
                    value = element.get("ContentType") or ""
                    if not key or not value or key in overrides:
                        raise ValueError("PPTX [Content_Types].xml contains an invalid override")
                    overrides[key] = value
            if overrides.get(_PRESENTATION_XML, defaults.get("xml")) != _MAIN_PRESENTATION_CONTENT_TYPE:
                raise ValueError("PPTX content types do not resolve a standard macro-free presentation part")
            risky_features.update(_pptx_risk_labels(content_types_payload.decode("utf-8", "ignore")))

            root_relationships = _pptx_relationships(
                archive.read(_ROOT_RELATIONSHIPS_XML),
                label=_ROOT_RELATIONSHIPS_XML,
            )
            matches = [relationship for relationship in root_relationships.values() if relationship[0] in _OFFICE_DOCUMENT_RELATIONSHIP_TYPES and not relationship[2] and _pptx_relationship_target("", relationship[1]) == _PRESENTATION_XML]
            if len(matches) != 1:
                raise ValueError("PPTX root relationships do not target one main presentation part")

            for relationships_name in sorted(name for name in names if name.endswith(".rels")):
                relationships = _pptx_relationships(
                    archive.read(relationships_name),
                    label=relationships_name,
                )
                risky_features.update(_pptx_relationship_risks(relationships))
                _pptx_validate_internal_targets(
                    _pptx_relationship_source_part(relationships_name),
                    relationships,
                    names,
                )

            presentation = _pptx_xml_root(
                archive.read(_PRESENTATION_XML),
                label=_PRESENTATION_XML,
                limit=4 * 1024 * 1024,
            )
            presentation_namespace, presentation_name = _pptx_xml_name(presentation.tag)
            if presentation_name != "presentation" or presentation_namespace not in _PRESENTATION_NAMESPACES:
                raise ValueError("PPTX presentation.xml has an unexpected root element")
            presentation_relationships = _pptx_relationships(
                archive.read(_PRESENTATION_RELATIONSHIPS_XML),
                label=_PRESENTATION_RELATIONSHIPS_XML,
            )
            _pptx_validate_internal_targets(
                _PRESENTATION_XML,
                presentation_relationships,
                names,
            )

            slide_id_list = next(
                (child for child in presentation if _pptx_xml_name(child.tag)[1] == "sldIdLst"),
                None,
            )
            slide_ids = [] if slide_id_list is None else [child for child in slide_id_list if _pptx_xml_name(child.tag)[1] == "sldId"]
            if len(slide_ids) > _MAX_PPTX_SLIDES:
                raise ValueError(f"PPTX declares more than {_MAX_PPTX_SLIDES:,} slides")

            seen_slide_ids: set[str] = set()
            seen_relationship_ids: set[str] = set()
            total_objects = 0
            total_text_nodes = 0
            total_text_chars = 0
            for slide_index, slide_id in enumerate(slide_ids, start=1):
                numeric_id = slide_id.get("id") or ""
                relationship_id = _pptx_slide_relationship_id(slide_id)
                if not numeric_id or numeric_id in seen_slide_ids:
                    raise ValueError("PPTX slide list contains a missing or duplicate slide ID")
                if not relationship_id or relationship_id in seen_relationship_ids:
                    raise ValueError("PPTX slide list contains a missing or duplicate slide relationship ID")
                seen_slide_ids.add(numeric_id)
                seen_relationship_ids.add(relationship_id)
                relationship = presentation_relationships.get(relationship_id)
                if relationship is None:
                    raise ValueError(f"PPTX slide {slide_index} references missing relationship {relationship_id}")
                relationship_type, target, external = relationship
                if external or relationship_type not in _SLIDE_RELATIONSHIP_TYPES:
                    raise ValueError(f"PPTX slide {slide_index} does not resolve to an internal slide part")
                part_name = _pptx_relationship_target(_PRESENTATION_XML, target)
                if overrides.get(part_name) != _SLIDE_CONTENT_TYPE:
                    raise ValueError(f"PPTX slide {slide_index} does not resolve to a standard slide content type")
                slide = _pptx_xml_root(
                    archive.read(part_name),
                    label=part_name,
                    limit=_MAX_PPTX_SLIDE_XML_BYTES,
                )
                slide_namespace, slide_name = _pptx_xml_name(slide.tag)
                if slide_name != "sld" or slide_namespace not in _PRESENTATION_NAMESPACES:
                    raise ValueError(f"PPTX {part_name} has an unexpected root element")
                relationships_name = _pptx_relationship_part_name(part_name)
                slide_relationships = (
                    _pptx_relationships(
                        archive.read(relationships_name),
                        label=relationships_name,
                    )
                    if relationships_name in names
                    else {}
                )
                _pptx_validate_internal_targets(part_name, slide_relationships, names)
                _pptx_validate_references(
                    slide,
                    slide_relationships,
                    label=part_name,
                )
                risky_features.update(
                    _pptx_action_risks(
                        slide,
                        slide_relationships,
                        label=part_name,
                    )
                )

                object_count = 0
                for element in slide.iter():
                    namespace, local_name = _pptx_xml_name(element.tag)
                    if namespace in _PRESENTATION_NAMESPACES and local_name in {
                        "sp",
                        "pic",
                        "graphicFrame",
                        "grpSp",
                        "cxnSp",
                    }:
                        object_count += 1
                    if namespace in _DRAWING_NAMESPACES and local_name == "t":
                        total_text_nodes += 1
                        total_text_chars += len(element.text or "")
                if object_count > _MAX_PPTX_OBJECTS_PER_SLIDE:
                    raise ValueError(f"PPTX slide {slide_index} contains more than {_MAX_PPTX_OBJECTS_PER_SLIDE:,} objects")
                total_objects += object_count
                if total_objects > _MAX_PPTX_OBJECTS:
                    raise ValueError(f"PPTX contains more than {_MAX_PPTX_OBJECTS:,} objects")
                if total_text_nodes > _MAX_PPTX_TEXT_NODES or total_text_chars > _MAX_PPTX_TEXT_CHARS:
                    raise ValueError("PPTX visible text exceeds the supported contract")

            blocked = sorted(risky_features & _PPTX_RENDER_BLOCKED_FEATURES)
            if blocked:
                raise ValueError(f"PPTX rendering is disabled for presentations containing {', '.join(blocked)}")
            return len(slide_ids)
    except zipfile.BadZipFile as exc:
        raise ValueError("PPTX input is not a valid ZIP package") from exc


@lru_cache(maxsize=1)
def _renderer_version() -> str:
    if not _SOFFICE:
        return "unavailable"
    try:
        result = subprocess.run(
            [_SOFFICE, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    first_line = (result.stdout or result.stderr or "unknown").splitlines()[0].strip()
    return first_line[:200] or "unknown"


@lru_cache(maxsize=1)
def _pdfium_version() -> str:
    return version("pypdfium2")


@lru_cache(maxsize=1)
def _font_fingerprint() -> str:
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return "unavailable"
    try:
        result = subprocess.run(
            [fc_list, "--format=%{file}\n"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    font_paths = sorted({os.fsdecode(line.strip()) for line in result.stdout.splitlines() if line.strip()})
    digest = hashlib.sha256()
    for font_path in font_paths:
        digest.update(font_path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        try:
            with open(font_path, "rb") as font_file:
                while chunk := font_file.read(1024 * 1024):
                    digest.update(chunk)
        except OSError:
            digest.update(b"unreadable")
        digest.update(b"\0")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _pipeline_fingerprint() -> str:
    identity = {
        "pipeline_contract_version": _PIPELINE_CONTRACT_VERSION,
        "renderer": "libreoffice-pdfium",
        "renderer_version": _renderer_version(),
        "pdfium_version": _pdfium_version(),
        "font_fingerprint": _font_fingerprint(),
        "conversion_filters": _CONVERSION_FILTERS,
    }
    payload = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _convert_to_pdf(document: bytes, job_dir: Path, *, format_name: str = "docx") -> Path:
    if not _SOFFICE:
        raise RuntimeError("LibreOffice is not available in the renderer image")
    if format_name not in {"docx", "pptx", "xlsx"}:
        raise ValueError("Unsupported Office conversion format")

    input_path = job_dir / f"document.{format_name}"
    output_dir = job_dir / "output"
    profile_dir = job_dir / "profile"
    output_dir.mkdir()
    profile_dir.mkdir()
    input_path.write_bytes(document)

    env = {
        **os.environ,
        "HOME": str(profile_dir),
        "TMPDIR": str(job_dir),
    }
    command = [
        _SOFFICE,
        "--headless",
        "--invisible",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--nolockcheck",
        "--nofirststartwizard",
        f"-env:UserInstallation={profile_dir.as_uri()}",
        "--convert-to",
        _CONVERSION_FILTERS[format_name],
        "--outdir",
        str(output_dir),
        str(input_path),
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=_CONVERSION_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Office conversion exceeded the 60 second limit") from exc
    except OSError as exc:
        raise RuntimeError("LibreOffice could not be started") from exc

    output_path = output_dir / "document.pdf"
    if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        logger.warning("LibreOffice conversion failed with exit code %s", result.returncode)
        raise ValueError(f"LibreOffice could not convert this {format_name.upper()} to PDF")
    return output_path


def _render_pages(
    pdf_path: Path,
    *,
    start_page: int,
    max_pages: int,
    dpi: int,
) -> tuple[int, tuple[_RenderedPage, ...]]:
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
    except Exception as exc:
        raise ValueError("Converted PDF could not be opened for rasterization") from exc

    try:
        page_count = len(pdf)
        if page_count < 1:
            raise ValueError("Converted PDF contains no pages")
        if start_page > page_count:
            raise ValueError(f"start_page {start_page} exceeds the document page count {page_count}")

        end_page = min(page_count, start_page + max_pages - 1)
        pages: list[_RenderedPage] = []
        total_page_bytes = 0
        deadline = time.monotonic() + _RASTER_WORK_TIMEOUT_SECONDS
        for page_number in range(start_page, end_page + 1):
            if time.monotonic() > deadline:
                raise TimeoutError("PDF rasterization exceeded the 40 second worker deadline")
            page = pdf[page_number - 1]
            bitmap = None
            image = None
            try:
                width_points, height_points = page.get_size()
                expected_width = math.ceil(width_points * dpi / 72.0)
                expected_height = math.ceil(height_points * dpi / 72.0)
                if expected_width < 1 or expected_height < 1 or expected_width > _MAX_RASTER_DIMENSION or expected_height > _MAX_RASTER_DIMENSION or expected_width * expected_height > _MAX_RASTER_PIXELS:
                    raise ValueError("A PDF page exceeds the supported raster dimensions")
                bitmap = page.render(scale=dpi / 72.0)
                image = bitmap.to_pil()
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=True)
                payload = output.getvalue()
                width, height = image.size
            finally:
                if image is not None:
                    image.close()
                if bitmap is not None:
                    bitmap.close()
                page.close()

            if time.monotonic() > deadline:
                raise TimeoutError("PDF rasterization exceeded the 40 second worker deadline")

            if not payload or len(payload) > _MAX_PAGE_BYTES:
                raise ValueError("A rendered page exceeds the 12 MiB page limit")
            total_page_bytes += len(payload)
            if total_page_bytes > _MAX_TOTAL_PAGE_BYTES:
                raise ValueError("Rendered pages exceed the supported total size limit")
            filename = f"page-{page_number:03d}.png"
            pages.append(
                _RenderedPage(
                    page=page_number,
                    filename=filename,
                    width=width,
                    height=height,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    data=payload,
                )
            )
        return page_count, tuple(pages)
    finally:
        pdf.close()


def _build_archive(
    *,
    format_name: str = "docx",
    page_count: int,
    start_page: int,
    max_pages: int,
    dpi: int,
    pages: tuple[_RenderedPage, ...],
    source_sha256: str,
) -> bytes:
    manifest = {
        "complete": True,
        "format": format_name,
        "renderer": "libreoffice-pdfium",
        "renderer_version": _renderer_version(),
        "pdfium_version": _pdfium_version(),
        "source_sha256": source_sha256,
        "pipeline_contract_version": _PIPELINE_CONTRACT_VERSION,
        "pipeline_fingerprint": _pipeline_fingerprint(),
        "page_count": page_count,
        "start_page": start_page,
        "end_page": pages[-1].page,
        "requested_max_pages": max_pages,
        "dpi": dpi,
        "pages": [
            {
                "page": page.page,
                **({"source_slide": page.page} if format_name == "pptx" else {}),
                "file": page.filename,
                "width": page.width,
                "height": page.height,
                "sha256": page.sha256,
            }
            for page in pages
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=True, separators=(",", ":")),
        )
        for page in pages:
            archive.writestr(page.filename, page.data)
    return output.getvalue()


def _write_raster_worker_output(
    pdf_path: Path,
    output_dir: Path,
    *,
    start_page: int,
    max_pages: int,
    dpi: int,
) -> None:
    page_count, pages = _render_pages(
        pdf_path,
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    for page in pages:
        (output_dir / page.filename).write_bytes(page.data)
    metadata = {
        "page_count": page_count,
        "pages": [
            {
                "page": page.page,
                "file": page.filename,
                "width": page.width,
                "height": page.height,
                "sha256": page.sha256,
            }
            for page in pages
        ],
    }
    (output_dir / "pages.json").write_text(
        json.dumps(metadata, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _load_raster_worker_output(
    output_dir: Path,
    *,
    start_page: int,
    max_pages: int,
) -> tuple[int, tuple[_RenderedPage, ...]]:
    metadata_path = output_dir / "pages.json"
    if not metadata_path.is_file() or metadata_path.stat().st_size > 64 * 1024:
        raise ValueError("PDF rasterization worker returned invalid metadata")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("PDF rasterization worker returned invalid metadata") from exc
    page_count = metadata.get("page_count") if isinstance(metadata, dict) else None
    raw_pages = metadata.get("pages") if isinstance(metadata, dict) else None
    expected_count = min(max_pages, page_count - start_page + 1) if isinstance(page_count, int) else 0
    if expected_count < 1 or not isinstance(raw_pages, list) or len(raw_pages) != expected_count:
        raise ValueError("PDF rasterization worker returned an incomplete page window")

    pages: list[_RenderedPage] = []
    total_size = 0
    for expected_page, raw_page in zip(
        range(start_page, start_page + expected_count),
        raw_pages,
        strict=True,
    ):
        if not isinstance(raw_page, dict) or raw_page.get("page") != expected_page:
            raise ValueError("PDF rasterization worker returned invalid page metadata")
        filename = f"page-{expected_page:03d}.png"
        if raw_page.get("file") != filename:
            raise ValueError("PDF rasterization worker returned an invalid page name")
        page_path = output_dir / filename
        try:
            payload = page_path.read_bytes()
        except OSError as exc:
            raise ValueError("PDF rasterization worker omitted a page") from exc
        if not payload or len(payload) > _MAX_PAGE_BYTES:
            raise ValueError("PDF rasterization worker returned an oversized page")
        total_size += len(payload)
        if total_size > _MAX_TOTAL_PAGE_BYTES:
            raise ValueError("PDF rasterization worker returned too much page data")
        digest = hashlib.sha256(payload).hexdigest()
        if raw_page.get("sha256") != digest:
            raise ValueError("PDF rasterization worker page digest mismatch")
        width = raw_page.get("width")
        height = raw_page.get("height")
        if not isinstance(width, int) or not isinstance(height, int):
            raise ValueError("PDF rasterization worker returned invalid dimensions")
        pages.append(
            _RenderedPage(
                page=expected_page,
                filename=filename,
                width=width,
                height=height,
                sha256=digest,
                data=payload,
            )
        )
    return page_count, tuple(pages)


def _render_pages_isolated(
    pdf_path: Path,
    job_dir: Path,
    *,
    start_page: int,
    max_pages: int,
    dpi: int,
) -> tuple[int, tuple[_RenderedPage, ...]]:
    output_dir = job_dir / "raster"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        _RASTER_WORKER_FLAG,
        str(pdf_path),
        str(output_dir),
        str(start_page),
        str(max_pages),
        str(dpi),
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_RASTER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("PDF rasterization exceeded the 45 second limit") from exc
    except OSError as exc:
        raise RuntimeError("PDF rasterization worker could not be started") from exc
    if result.returncode != 0:
        detail = (result.stderr or "PDF rasterization failed").strip()[:500]
        if result.returncode == 3:
            raise TimeoutError(detail)
        raise ValueError(detail)
    return _load_raster_worker_output(
        output_dir,
        start_page=start_page,
        max_pages=max_pages,
    )


def _render_office(
    document: bytes,
    *,
    format_name: str,
    start_page: int,
    max_pages: int,
    dpi: int,
) -> bytes:
    expected_pptx_slide_count: int | None = None
    if format_name == "docx":
        _validate_docx(document)
    elif format_name == "pptx":
        expected_pptx_slide_count = _validate_pptx(document)
    elif format_name == "xlsx":
        _validate_xlsx(document)
    else:
        raise ValueError("Unsupported Office render format")
    source_sha256 = hashlib.sha256(document).hexdigest()
    with tempfile.TemporaryDirectory(
        prefix="vassilflow-office-",
        dir=tempfile.gettempdir(),
    ) as tmp:
        pdf_path = _convert_to_pdf(document, Path(tmp), format_name=format_name)
        page_count, pages = _render_pages_isolated(
            pdf_path,
            Path(tmp),
            start_page=start_page,
            max_pages=max_pages,
            dpi=dpi,
        )
        if expected_pptx_slide_count is not None and page_count != expected_pptx_slide_count:
            raise ValueError("PPTX conversion did not preserve the declared slide-to-page mapping")
        archive = _build_archive(
            format_name=format_name,
            page_count=page_count,
            start_page=start_page,
            max_pages=max_pages,
            dpi=dpi,
            pages=pages,
            source_sha256=source_sha256,
        )
        if len(archive) > _MAX_ARCHIVE_BYTES:
            raise ValueError("Rendered archive exceeds the supported size limit")
        return archive


def _render_docx(document: bytes, *, start_page: int, max_pages: int, dpi: int) -> bytes:
    return _render_office(
        document,
        format_name="docx",
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )


def _render_xlsx(document: bytes, *, start_page: int, max_pages: int, dpi: int) -> bytes:
    return _render_office(
        document,
        format_name="xlsx",
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )


def _render_pptx(document: bytes, *, start_page: int, max_pages: int, dpi: int) -> bytes:
    return _render_office(
        document,
        format_name="pptx",
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )


async def _read_request_body(request: Request) -> bytes:
    raw_length = request.headers.get("content-length")
    if raw_length:
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc
        if content_length > _MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="Office input exceeds the 50 MiB package limit")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="Office input exceeds the 50 MiB package limit")
    return bytes(body)


@app.get("/health")
def health() -> dict[str, str]:
    if not _SOFFICE:
        raise HTTPException(status_code=503, detail="LibreOffice is unavailable")
    return {
        "status": "ok",
        "renderer": "libreoffice-pdfium",
        "renderer_version": _renderer_version(),
        "pipeline_contract_version": _PIPELINE_CONTRACT_VERSION,
        "pipeline_fingerprint": _pipeline_fingerprint(),
    }


async def _render_request(
    request: Request,
    *,
    format_name: str,
    start_page: int,
    max_pages: int,
    dpi: int,
) -> Response:
    mime_type = {
        "docx": _DOCX_MIME,
        "pptx": _PPTX_MIME,
        "xlsx": _XLSX_MIME,
    }[format_name]
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in {mime_type, "application/octet-stream"}:
        raise HTTPException(status_code=415, detail=f"Expected an {format_name.upper()} request body")
    try:
        await asyncio.wait_for(_RENDER_SLOTS.acquire(), timeout=_QUEUE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=429,
            detail="Office renderer is busy; retry shortly",
            headers={"Retry-After": "5"},
        ) from exc

    try:
        document = await _read_request_body(request)
        archive = await run_in_threadpool(
            {
                "docx": _render_docx,
                "pptx": _render_pptx,
                "xlsx": _render_xlsx,
            }[format_name],
            document,
            start_page=start_page,
            max_pages=max_pages,
            dpi=dpi,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _RENDER_SLOTS.release()

    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="render.zip"'},
    )


@app.post("/v1/render/docx")
async def render_docx(
    request: Request,
    start_page: int = Query(default=1, ge=1),
    max_pages: int = Query(default=1, ge=1, le=_MAX_PAGES_PER_REQUEST),
    dpi: int = Query(default=120, ge=96, le=200),
) -> Response:
    return await _render_request(
        request,
        format_name="docx",
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )


@app.post("/v1/render/xlsx")
async def render_xlsx(
    request: Request,
    start_page: int = Query(default=1, ge=1),
    max_pages: int = Query(default=1, ge=1, le=_MAX_PAGES_PER_REQUEST),
    dpi: int = Query(default=120, ge=96, le=200),
) -> Response:
    return await _render_request(
        request,
        format_name="xlsx",
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )


@app.post("/v1/render/pptx")
async def render_pptx(
    request: Request,
    start_page: int = Query(default=1, ge=1),
    max_pages: int = Query(default=1, ge=1, le=_MAX_PAGES_PER_REQUEST),
    dpi: int = Query(default=120, ge=96, le=200),
) -> Response:
    return await _render_request(
        request,
        format_name="pptx",
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )


def _raster_worker_main(arguments: list[str]) -> int:
    if len(arguments) != 6 or arguments[0] != _RASTER_WORKER_FLAG:
        return 64
    try:
        pdf_path = Path(arguments[1])
        output_dir = Path(arguments[2])
        start_page = int(arguments[3])
        max_pages = int(arguments[4])
        dpi = int(arguments[5])
        if not pdf_path.is_file() or start_page < 1 or not 1 <= max_pages <= _MAX_PAGES_PER_REQUEST or not 96 <= dpi <= 200:
            raise ValueError("Invalid rasterization worker arguments")
        _write_raster_worker_output(
            pdf_path,
            output_dir,
            start_page=start_page,
            max_pages=max_pages,
            dpi=dpi,
        )
        return 0
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print("PDF rasterization worker failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_raster_worker_main(sys.argv[1:]))
