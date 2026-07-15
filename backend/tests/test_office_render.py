from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile

import httpx
import pytest

from vassilflow.community.office import render
from vassilflow.community.office.errors import (
    OfficePackageError,
    OfficeRenderError,
    OfficeRenderUnavailableError,
)

_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def _render_archive(
    *,
    document: bytes = b"docx",
    format_name: str = "docx",
    extra_entry: bool = False,
    digest: str | None = None,
    source_digest: str | None = None,
    page_count: int = 1,
    requested_max_pages: int = 1,
    pptx_source_slide: int = 1,
    omit_pptx_source_slide: bool = False,
) -> bytes:
    page_metadata = {
        "page": 1,
        "file": "page-001.png",
        "width": 1,
        "height": 1,
        "sha256": digest or hashlib.sha256(_PNG).hexdigest(),
    }
    if format_name == "pptx" and not omit_pptx_source_slide:
        page_metadata["source_slide"] = pptx_source_slide
    manifest = {
        "complete": True,
        "format": format_name,
        "renderer": "test-renderer",
        "renderer_version": "1.0",
        "pdfium_version": "5.11.0",
        "source_sha256": source_digest or hashlib.sha256(document).hexdigest(),
        "pipeline_contract_version": "2",
        "pipeline_fingerprint": "a" * 64,
        "page_count": page_count,
        "start_page": 1,
        "end_page": 1,
        "requested_max_pages": requested_max_pages,
        "dpi": 120,
        "pages": [page_metadata],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("page-001.png", _PNG)
        if extra_entry:
            archive.writestr("unexpected.txt", "no")
    return output.getvalue()


def test_parse_render_archive_validates_manifest_png_and_digest() -> None:
    result = render._parse_render_archive(
        _render_archive(),
        expected_start_page=1,
        expected_max_pages=1,
        expected_dpi=120,
        expected_source_sha256=hashlib.sha256(b"docx").hexdigest(),
    )

    assert result.page_count == 1
    assert result.has_more is False
    assert result.source_sha256 == hashlib.sha256(b"docx").hexdigest()
    assert result.pipeline_fingerprint == "a" * 64
    assert result.pages[0].data == _PNG
    assert result.pages[0].width == 1
    assert result.pages[0].height == 1


def test_parse_render_archive_rejects_digest_mismatch() -> None:
    with pytest.raises(OfficePackageError, match="digest"):
        render._parse_render_archive(
            _render_archive(digest="0" * 64),
            expected_start_page=1,
            expected_max_pages=1,
            expected_dpi=120,
            expected_source_sha256=hashlib.sha256(b"docx").hexdigest(),
        )


def test_parse_render_archive_rejects_unexpected_entries() -> None:
    with pytest.raises(OfficePackageError, match="unexpected entries"):
        render._parse_render_archive(
            _render_archive(extra_entry=True),
            expected_start_page=1,
            expected_max_pages=1,
            expected_dpi=120,
            expected_source_sha256=hashlib.sha256(b"docx").hexdigest(),
        )


def test_parse_render_archive_rejects_source_mismatch() -> None:
    with pytest.raises(OfficePackageError, match="source document"):
        render._parse_render_archive(
            _render_archive(source_digest="b" * 64),
            expected_start_page=1,
            expected_max_pages=1,
            expected_dpi=120,
            expected_source_sha256=hashlib.sha256(b"docx").hexdigest(),
        )


def test_parse_render_archive_rejects_truncated_page_window() -> None:
    with pytest.raises(OfficePackageError, match="pages list"):
        render._parse_render_archive(
            _render_archive(page_count=2, requested_max_pages=2),
            expected_start_page=1,
            expected_max_pages=2,
            expected_dpi=120,
            expected_source_sha256=hashlib.sha256(b"docx").hexdigest(),
        )


def test_render_docx_pages_uses_bounded_http_contract(monkeypatch) -> None:
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/render/docx"
        assert request.url.params["start_page"] == "1"
        assert request.url.params["max_pages"] == "1"
        assert request.url.params["dpi"] == "120"
        assert request.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")
        assert request.content == b"docx"
        return httpx.Response(
            200,
            headers={"Content-Type": "application/zip"},
            content=_render_archive(),
        )

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setenv("VASSILFLOW_OFFICE_RENDERER_URL", "http://renderer.test:8003")
    monkeypatch.setattr(render.httpx, "Client", client_factory)

    result = render.render_docx_pages(b"docx")

    assert result.renderer == "test-renderer"
    assert [page.page for page in result.pages] == [1]


def test_render_docx_pages_reports_unavailable_renderer(monkeypatch) -> None:
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setenv("VASSILFLOW_OFFICE_RENDERER_URL", "http://renderer.test:8003")
    monkeypatch.setattr(render.httpx, "Client", client_factory)

    with pytest.raises(OfficeRenderUnavailableError, match="renderer is unavailable"):
        render.render_docx_pages(b"docx")


def test_render_xlsx_pages_uses_xlsx_route_mime_and_manifest(monkeypatch) -> None:
    real_client = httpx.Client
    document = b"xlsx"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/render/xlsx"
        assert request.headers["content-type"] == ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/zip"},
            content=_render_archive(document=document, format_name="xlsx"),
        )

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setenv("VASSILFLOW_OFFICE_RENDERER_URL", "http://renderer.test:8003")
    monkeypatch.setattr(render.httpx, "Client", client_factory)

    result = render.render_xlsx_pages(document)

    assert result.format == "xlsx"


def test_render_pptx_pages_uses_pptx_route_mime_and_manifest(monkeypatch) -> None:
    real_client = httpx.Client
    document = b"pptx"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/render/pptx"
        assert request.headers["content-type"] == ("application/vnd.openxmlformats-officedocument.presentationml.presentation")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/zip"},
            content=_render_archive(document=document, format_name="pptx"),
        )

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setenv("VASSILFLOW_OFFICE_RENDERER_URL", "http://renderer.test:8003")
    monkeypatch.setattr(render.httpx, "Client", client_factory)

    result = render.render_pptx_pages(document)

    assert result.format == "pptx"
    assert result.pages[0].source_slide == 1


@pytest.mark.parametrize(
    "archive",
    [
        _render_archive(
            document=b"pptx",
            format_name="pptx",
            omit_pptx_source_slide=True,
        ),
        _render_archive(
            document=b"pptx",
            format_name="pptx",
            pptx_source_slide=2,
        ),
    ],
)
def test_parse_render_archive_rejects_missing_or_mismatched_pptx_source_slide(
    archive: bytes,
) -> None:
    with pytest.raises(OfficePackageError, match="source slide"):
        render._parse_render_archive(
            archive,
            expected_start_page=1,
            expected_max_pages=1,
            expected_dpi=120,
            expected_source_sha256=hashlib.sha256(b"pptx").hexdigest(),
            expected_format="pptx",
        )


@pytest.mark.parametrize(
    ("start_page", "max_pages", "dpi", "message"),
    [
        (0, 1, 120, "start_page"),
        (1, 13, 120, "max_pages"),
        (1, 1, 300, "dpi"),
    ],
)
def test_render_docx_pages_rejects_unbounded_requests(
    start_page: int,
    max_pages: int,
    dpi: int,
    message: str,
) -> None:
    with pytest.raises(OfficeRenderError, match=message):
        render.render_docx_pages(
            b"docx",
            start_page=start_page,
            max_pages=max_pages,
            dpi=dpi,
        )
