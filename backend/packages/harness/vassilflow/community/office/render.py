"""Bounded client for the isolated VassilFlow Office renderer."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import struct
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx

from .errors import OfficePackageError, OfficeRenderError, OfficeRenderUnavailableError

_RENDERER_URL_ENV = "VASSILFLOW_OFFICE_RENDERER_URL"
_DEFAULT_RENDERER_URL = "http://127.0.0.1:8003"
_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_MAX_ARCHIVE_ENTRIES = 16
_MAX_PAGE_BYTES = 12 * 1024 * 1024
_MAX_TOTAL_PAGE_BYTES = 48 * 1024 * 1024
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_PAGES_PER_REQUEST = 12
_PIPELINE_CONTRACT_VERSION = "2"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True, slots=True)
class RenderedOfficePage:
    """One renderer-produced page image."""

    page: int
    filename: str
    width: int
    height: int
    sha256: str
    data: bytes
    source_slide: int | None = None


@dataclass(frozen=True, slots=True)
class OfficeRenderResult:
    """Validated renderer response returned to the tool layer."""

    format: str
    renderer: str
    renderer_version: str
    pdfium_version: str
    source_sha256: str
    pipeline_fingerprint: str
    page_count: int
    start_page: int
    dpi: int
    pages: tuple[RenderedOfficePage, ...]

    @property
    def has_more(self) -> bool:
        return self.pages[-1].page < self.page_count


def _renderer_url() -> str:
    raw = os.getenv(_RENDERER_URL_ENV, _DEFAULT_RENDERER_URL).strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OfficeRenderUnavailableError(f"{_RENDERER_URL_ENV} must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OfficeRenderUnavailableError(f"{_RENDERER_URL_ENV} must not contain credentials, a query, or a fragment")
    return raw


def _read_limited_response(response: httpx.Response, limit: int) -> bytes:
    output = bytearray()
    for chunk in response.iter_bytes():
        output.extend(chunk)
        if len(output) > limit:
            raise OfficeRenderError("Office renderer response exceeds the supported size limit")
    return bytes(output)


def _renderer_error(response: httpx.Response) -> OfficeRenderError:
    try:
        payload = _read_limited_response(response, _MAX_MANIFEST_BYTES)
        decoded = json.loads(payload)
        detail = decoded.get("detail") if isinstance(decoded, dict) else None
    except (OfficeRenderError, UnicodeDecodeError, json.JSONDecodeError):
        detail = None
    if not isinstance(detail, str) or not detail.strip():
        detail = f"renderer returned HTTP {response.status_code}"
    return OfficeRenderError(f"Office render failed: {detail.strip()}")


def _validate_archive_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if name != normalized or normalized.startswith("/") or ".." in path.parts:
        raise OfficePackageError(f"Office renderer returned an unsafe archive entry: {name}")


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or not payload.startswith(_PNG_SIGNATURE) or payload[12:16] != b"IHDR":
        raise OfficePackageError("Office renderer returned an invalid PNG page")
    width, height = struct.unpack(">II", payload[16:24])
    if width < 1 or height < 1 or width > 10_000 or height > 10_000:
        raise OfficePackageError("Office renderer returned unsupported PNG dimensions")
    return width, height


def _require_manifest_int(manifest: dict[str, Any], key: str, *, minimum: int) -> int:
    value = manifest.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise OfficePackageError(f"Office renderer manifest has an invalid {key}")
    return value


def _require_manifest_digest(manifest: dict[str, Any], key: str) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or len(value) != 64:
        raise OfficePackageError(f"Office renderer manifest has an invalid {key}")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise OfficePackageError(f"Office renderer manifest has an invalid {key}") from exc
    return value.lower()


def _parse_render_archive(
    payload: bytes,
    *,
    expected_start_page: int,
    expected_max_pages: int,
    expected_dpi: int,
    expected_source_sha256: str,
    expected_format: str = "docx",
) -> OfficeRenderResult:
    try:
        with zipfile.ZipFile(io.BytesIO(payload), mode="r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > _MAX_ARCHIVE_ENTRIES:
                raise OfficePackageError("Office renderer returned an invalid archive entry count")

            names: set[str] = set()
            total_size = 0
            for info in infos:
                _validate_archive_name(info.filename)
                if info.filename in names:
                    raise OfficePackageError(f"Office renderer returned a duplicate archive entry: {info.filename}")
                names.add(info.filename)
                if info.flag_bits & 0x1:
                    raise OfficePackageError("Office renderer returned an encrypted archive entry")
                total_size += info.file_size
                if total_size > _MAX_ARCHIVE_BYTES:
                    raise OfficePackageError("Office renderer archive expands beyond the supported limit")
                if info.compress_size and info.file_size / info.compress_size > 250:
                    raise OfficePackageError("Office renderer archive is suspiciously compressed")

            if "manifest.json" not in names:
                raise OfficePackageError("Office renderer archive is missing manifest.json")
            manifest_payload = archive.read("manifest.json")
            if len(manifest_payload) > _MAX_MANIFEST_BYTES:
                raise OfficePackageError("Office renderer manifest exceeds the supported size limit")
            manifest = json.loads(manifest_payload)
            if not isinstance(manifest, dict):
                raise OfficePackageError("Office renderer manifest must be an object")

            if manifest.get("format") != expected_format:
                raise OfficePackageError("Office renderer manifest has an unexpected format")
            if manifest.get("complete") is not True:
                raise OfficePackageError("Office renderer did not mark the render as complete")
            if manifest.get("pipeline_contract_version") != _PIPELINE_CONTRACT_VERSION:
                raise OfficePackageError("Office renderer manifest has an incompatible pipeline contract")
            renderer = manifest.get("renderer")
            renderer_version = manifest.get("renderer_version")
            pdfium_version = manifest.get("pdfium_version")
            if not isinstance(renderer, str) or not renderer or len(renderer) > 100:
                raise OfficePackageError("Office renderer manifest has an invalid renderer")
            if not isinstance(renderer_version, str) or len(renderer_version) > 200:
                raise OfficePackageError("Office renderer manifest has an invalid renderer_version")
            if not isinstance(pdfium_version, str) or not pdfium_version or len(pdfium_version) > 100:
                raise OfficePackageError("Office renderer manifest has an invalid pdfium_version")
            source_sha256 = _require_manifest_digest(manifest, "source_sha256")
            pipeline_fingerprint = _require_manifest_digest(manifest, "pipeline_fingerprint")
            if not hmac.compare_digest(source_sha256, expected_source_sha256):
                raise OfficePackageError("Office renderer manifest does not match the source document")

            page_count = _require_manifest_int(manifest, "page_count", minimum=1)
            start_page = _require_manifest_int(manifest, "start_page", minimum=1)
            end_page = _require_manifest_int(manifest, "end_page", minimum=1)
            requested_max_pages = _require_manifest_int(manifest, "requested_max_pages", minimum=1)
            dpi = _require_manifest_int(manifest, "dpi", minimum=1)
            if start_page != expected_start_page or requested_max_pages != expected_max_pages or dpi != expected_dpi:
                raise OfficePackageError("Office renderer manifest does not match the request")

            raw_pages = manifest.get("pages")
            expected_page_count = min(expected_max_pages, page_count - start_page + 1)
            if expected_page_count < 1 or not isinstance(raw_pages, list) or len(raw_pages) != expected_page_count:
                raise OfficePackageError("Office renderer manifest has an invalid pages list")
            if end_page != start_page + len(raw_pages) - 1:
                raise OfficePackageError("Office renderer manifest has an invalid end_page")

            expected_page_numbers = list(range(start_page, start_page + len(raw_pages)))
            pages: list[RenderedOfficePage] = []
            total_page_bytes = 0
            page_names: set[str] = set()
            for expected_page, raw_page in zip(expected_page_numbers, raw_pages, strict=True):
                if not isinstance(raw_page, dict):
                    raise OfficePackageError("Office renderer page metadata must be an object")
                page = raw_page.get("page")
                filename = raw_page.get("file")
                expected_hash = raw_page.get("sha256")
                if page != expected_page or page > page_count:
                    raise OfficePackageError("Office renderer returned non-contiguous page numbers")
                if filename != f"page-{page:03d}.png" or filename not in names:
                    raise OfficePackageError("Office renderer page filename does not match its page number")
                if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                    raise OfficePackageError("Office renderer page has an invalid SHA-256 digest")
                source_slide = raw_page.get("source_slide")
                if expected_format == "pptx":
                    if not isinstance(source_slide, int) or isinstance(source_slide, bool) or source_slide != page:
                        raise OfficePackageError("Office renderer page does not preserve its PPTX source slide")
                elif "source_slide" in raw_page:
                    raise OfficePackageError("Office renderer page has unexpected PPTX source-slide metadata")

                page_payload = archive.read(filename)
                if not page_payload or len(page_payload) > _MAX_PAGE_BYTES:
                    raise OfficePackageError("Office renderer page exceeds the supported size limit")
                total_page_bytes += len(page_payload)
                if total_page_bytes > _MAX_TOTAL_PAGE_BYTES:
                    raise OfficePackageError("Office renderer pages exceed the supported total size limit")
                width, height = _png_dimensions(page_payload)
                if raw_page.get("width") != width or raw_page.get("height") != height:
                    raise OfficePackageError("Office renderer page dimensions do not match the PNG")
                digest = hashlib.sha256(page_payload).hexdigest()
                if not hmac.compare_digest(digest, expected_hash.lower()):
                    raise OfficePackageError("Office renderer page digest does not match its content")

                page_names.add(filename)
                pages.append(
                    RenderedOfficePage(
                        page=page,
                        filename=filename,
                        width=width,
                        height=height,
                        sha256=digest,
                        data=page_payload,
                        source_slide=source_slide,
                    )
                )

            if names != {"manifest.json", *page_names}:
                raise OfficePackageError("Office renderer archive contains unexpected entries")
    except OfficePackageError:
        raise
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficePackageError(f"Office renderer returned a malformed archive: {exc}") from exc

    return OfficeRenderResult(
        format=expected_format,
        renderer=renderer,
        renderer_version=renderer_version,
        pdfium_version=pdfium_version,
        source_sha256=source_sha256,
        pipeline_fingerprint=pipeline_fingerprint,
        page_count=page_count,
        start_page=start_page,
        dpi=dpi,
        pages=tuple(pages),
    )


def _render_office_pages(
    document: bytes,
    *,
    format_name: str,
    start_page: int = 1,
    max_pages: int = 1,
    dpi: int = 120,
) -> OfficeRenderResult:
    """Render a bounded Office page window through the isolated renderer service."""
    if format_name not in _MIME_TYPES:
        raise OfficeRenderError(f"Unsupported Office render format: {format_name}")
    if start_page < 1:
        raise OfficeRenderError("start_page must be at least 1")
    if not 1 <= max_pages <= _MAX_PAGES_PER_REQUEST:
        raise OfficeRenderError(f"max_pages must be between 1 and {_MAX_PAGES_PER_REQUEST}")
    if not 96 <= dpi <= 200:
        raise OfficeRenderError("dpi must be between 96 and 200")

    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=125.0, write=30.0, pool=5.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            with client.stream(
                "POST",
                f"{_renderer_url()}/v1/render/{format_name}",
                params={"start_page": start_page, "max_pages": max_pages, "dpi": dpi},
                headers={
                    "Content-Type": _MIME_TYPES[format_name],
                    "Accept": "application/zip",
                },
                content=document,
            ) as response:
                if response.status_code != 200:
                    raise _renderer_error(response)
                if response.headers.get("content-type", "").split(";", 1)[0].strip() != "application/zip":
                    raise OfficeRenderError("Office renderer returned an unexpected content type")
                archive = _read_limited_response(response, _MAX_ARCHIVE_BYTES)
    except OfficeRenderError:
        raise
    except httpx.RequestError as exc:
        raise OfficeRenderUnavailableError(f"Office renderer is unavailable. Start the Docker renderer or set {_RENDERER_URL_ENV} to a reachable renderer service.") from exc

    source_sha256 = hashlib.sha256(document).hexdigest()
    return _parse_render_archive(
        archive,
        expected_start_page=start_page,
        expected_max_pages=max_pages,
        expected_dpi=dpi,
        expected_source_sha256=source_sha256,
        expected_format=format_name,
    )


def render_docx_pages(
    document: bytes,
    *,
    start_page: int = 1,
    max_pages: int = 1,
    dpi: int = 120,
) -> OfficeRenderResult:
    """Render a bounded DOCX page window through the isolated renderer service."""
    return _render_office_pages(
        document,
        format_name="docx",
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )


def render_xlsx_pages(
    document: bytes,
    *,
    start_page: int = 1,
    max_pages: int = 1,
    dpi: int = 120,
) -> OfficeRenderResult:
    """Render a bounded XLSX page window through the isolated renderer service."""
    return _render_office_pages(
        document,
        format_name="xlsx",
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )


def render_pptx_pages(
    document: bytes,
    *,
    start_page: int = 1,
    max_pages: int = 1,
    dpi: int = 120,
) -> OfficeRenderResult:
    """Render a bounded PPTX slide window through the isolated renderer service."""
    return _render_office_pages(
        document,
        format_name="pptx",
        start_page=start_page,
        max_pages=max_pages,
        dpi=dpi,
    )
