"""Agent-facing VassilFlow Office tools backed by structured sandbox I/O."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from uuid import uuid4

from langchain.tools import tool

from vassilflow.sandbox.file_operation_lock import get_file_operation_lock
from vassilflow.sandbox.tools import (
    ensure_sandbox_initialized,
    ensure_sandbox_initialized_async,
    ensure_thread_directories_exist,
)
from vassilflow.tools.types import Runtime

from .engine import office_engine
from .errors import OfficeError, OfficeOperationError
from .models import (
    OfficeEditOperation,
    PptxObjectSelector,
    PptxPictureSourceReplacementOperation,
    PptxShapeFormatOperation,
    PptxSlideBackgroundFormatOperation,
)
from .policy import normalize_office_image_path, normalize_office_output_dir, normalize_office_path

logger = logging.getLogger(__name__)


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _known_error(exc: Exception) -> str:
    if isinstance(exc, OfficeError):
        return str(exc)
    if isinstance(exc, FileNotFoundError):
        return "Office document was not found"
    if isinstance(exc, PermissionError):
        return "Office document access was denied by workspace policy"
    if isinstance(exc, OSError):
        return f"Office document I/O failed: {exc}"
    logger.exception("Unexpected VassilFlow Office failure")
    return "Unexpected Office operation failure"


def _pptx_image_asset_paths(
    operations: list[OfficeEditOperation],
) -> dict[str, str]:
    paths: dict[str, str] = {}
    for operation in operations:
        if isinstance(operation, PptxShapeFormatOperation):
            fill = operation.formatting.fill
        elif isinstance(operation, PptxSlideBackgroundFormatOperation):
            fill = operation.formatting
        elif isinstance(operation, PptxPictureSourceReplacementOperation):
            paths[operation.image_path] = normalize_office_image_path(operation.image_path)
            continue
        else:
            continue
        if fill is None or fill.type != "image" or fill.image_path is None:
            continue
        paths[fill.image_path] = normalize_office_image_path(fill.image_path)
    return paths


def _output_exists(sandbox, path: str) -> bool:
    try:
        sandbox.download_file(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        if exc.errno == errno.ENOENT or "not found" in str(exc).lower():
            return False
        raise


def _directory_has_entries(sandbox, path: str) -> bool:
    try:
        entries = sandbox.list_dir(path, max_depth=1)
    except FileNotFoundError:
        return False
    except OSError as exc:
        if exc.errno == errno.ENOENT or "not found" in str(exc).lower():
            return False
        raise
    root = path.rstrip("/")
    return any(entry.rstrip("/\\") != root for entry in entries)


def _visual_review_contract(runtime: Runtime, *, gateway_images_available: bool = True) -> tuple[str, str]:
    tools = getattr(runtime, "tools", ()) or ()
    if gateway_images_available and any(getattr(candidate, "name", None) == "view_image" for candidate in tools):
        return "pending", "Inspect every page_path with view_image before accepting visual QA."
    return (
        "external_review_required",
        "The current model cannot inspect these images. Render every page, present the Office file with the external review warning, and do not claim visual QA passed until an image-capable client reviews every page_path.",
    )


def _mirror_binary_to_gateway_if_needed(runtime: Runtime, path: str, content: bytes) -> bool:
    """Keep remote-sandbox artifacts visible to Gateway-local file tools."""
    if not hasattr(runtime, "state"):
        return True

    from vassilflow.sandbox.sandbox_provider import get_sandbox_provider
    from vassilflow.sandbox.tools import (
        get_thread_data,
        resolve_and_validate_user_data_path,
        validate_local_tool_path,
    )

    try:
        provider = get_sandbox_provider()
        if getattr(provider, "uses_thread_data_mounts", False):
            return True

        thread_data = get_thread_data(runtime)
        if thread_data is None:
            raise OfficeOperationError("Remote Office artifact could not be synchronized to the Gateway")
        validate_local_tool_path(path, thread_data)
        destination = Path(resolve_and_validate_user_data_path(path, thread_data))
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(f".{destination.name}.stage-{uuid4().hex}")
        try:
            with staging.open("xb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(staging, destination)
        finally:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove staged Office mirror file")
        return True
    except Exception:
        logger.exception("Unable to mirror committed Office artifact to the Gateway")
        return False


@tool("office_inspect", parse_docstring=True)
def office_inspect_tool(
    runtime: Runtime,
    path: str,
    start_paragraph: int = 1,
    max_paragraphs: int = 100,
    include_runs: bool = False,
    sheet_name: str | None = None,
    cell_range: str | None = None,
    include_cell_styles: bool = False,
    start_slide: int = 1,
    max_slides: int = 20,
    include_pptx_formatting: bool = False,
    pptx_selector: PptxObjectSelector | None = None,
    include_pptx_annotations: bool = False,
    include_pptx_dynamics: bool = False,
    include_pptx_media_gc_plan: bool = False,
) -> str:
    """Inspect a DOCX, XLSX, or PPTX as bounded structured data.

    Args:
        path: Absolute DOCX, XLSX, or PPTX path under /mnt/user-data/uploads, workspace, or outputs.
        start_paragraph: DOCX only; first 1-based paragraph to return.
        max_paragraphs: DOCX only; number of paragraphs to return, from 1 through 200.
        include_runs: DOCX only; include bounded run paths and direct formatting.
        sheet_name: XLSX only; worksheet to inspect, or omit to list workbook sheets.
        cell_range: XLSX only; optional bounded A1 range on sheet_name, such as A1:F40.
        include_cell_styles: XLSX only; include direct cell formatting for typed selectors.
        start_slide: PPTX only; first 1-based slide to return.
        max_slides: PPTX only; number of slides to return, from 1 through 50.
        include_pptx_formatting: PPTX only; include bounded direct shape, picture, paragraph, and text-run formatting. Embedded picture source digests are always returned.
        pptx_selector: PPTX only; optional conjunctive exact-path and object metadata filters.
        include_pptx_annotations: PPTX only; include bounded speaker notes and legacy or threaded review comments.
        include_pptx_dynamics: PPTX only; include bounded authored animation effects tied to stable object paths.
        include_pptx_media_gc_plan: PPTX only; include package-wide, bounded,
            non-destructive dry-run evidence for image relationships with zero
            source-XML references and ppt/media image parts with zero incoming
            relationships, plus package-wide XML relationship integrity and
            package-root reachability. Root-unreachable image evidence includes
            bounded incoming relationship state and exact package hashes. Every
            record is non-actionable; this never deletes data.
    """
    try:
        source_path = normalize_office_path(path)
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        document = sandbox.download_file(source_path)
        result = office_engine.inspect(
            document,
            suffix=PurePosixPath(source_path).suffix,
            start_paragraph=start_paragraph,
            max_paragraphs=max_paragraphs,
            include_runs=include_runs,
            sheet_name=sheet_name,
            cell_range=cell_range,
            include_cell_styles=include_cell_styles,
            start_slide=start_slide,
            max_slides=max_slides,
            include_pptx_formatting=include_pptx_formatting,
            include_pptx_annotations=include_pptx_annotations,
            include_pptx_dynamics=include_pptx_dynamics,
            include_pptx_media_gc_plan=include_pptx_media_gc_plan,
            pptx_selector=pptx_selector,
        )
        return _json({"ok": True, "path": source_path, **result})
    except Exception as exc:
        return _json({"ok": False, "error": _known_error(exc)})


async def _office_inspect_async(
    runtime: Runtime,
    path: str,
    start_paragraph: int = 1,
    max_paragraphs: int = 100,
    include_runs: bool = False,
    sheet_name: str | None = None,
    cell_range: str | None = None,
    include_cell_styles: bool = False,
    start_slide: int = 1,
    max_slides: int = 20,
    include_pptx_formatting: bool = False,
    pptx_selector: PptxObjectSelector | None = None,
    include_pptx_annotations: bool = False,
    include_pptx_dynamics: bool = False,
    include_pptx_media_gc_plan: bool = False,
) -> str:
    await ensure_sandbox_initialized_async(runtime)
    return await asyncio.to_thread(
        office_inspect_tool.func,
        runtime,
        path,
        start_paragraph=start_paragraph,
        max_paragraphs=max_paragraphs,
        include_runs=include_runs,
        sheet_name=sheet_name,
        cell_range=cell_range,
        include_cell_styles=include_cell_styles,
        start_slide=start_slide,
        max_slides=max_slides,
        include_pptx_formatting=include_pptx_formatting,
        pptx_selector=pptx_selector,
        include_pptx_annotations=include_pptx_annotations,
        include_pptx_dynamics=include_pptx_dynamics,
        include_pptx_media_gc_plan=include_pptx_media_gc_plan,
    )


office_inspect_tool.coroutine = _office_inspect_async


@tool("office_edit", parse_docstring=True)
def office_edit_tool(
    runtime: Runtime,
    source_path: str,
    output_path: str,
    operations: list[OfficeEditOperation],
    overwrite_output: bool = False,
) -> str:
    """Apply transactional structured edits to a DOCX, XLSX, or PPTX.

    The source is always read immediately before editing. Uploads remain immutable:
    output_path must be a distinct path under workspace or outputs. All operations
    succeed and the resulting package validates before a staged atomic replacement.
    PPTX supports paragraph-local literal replacement, source-only embedded-picture
    replacement, plus bounded direct run, paragraph, shape, shape-or-connector
    line, and direct slide-background formatting. Picture targets use exact
    authored-ID paths, object names, and inspected source SHA-256 guards; replacement
    preserves crop, framing, effects, geometry, alt text, and interactions. Other
    formatting targets use expected text, object name, or slide part name to reject
    stale paths. Every
    PPTX formatting selector contains only targets. Direct shape fills accept typed RGB
    solid, no-fill, bounded gradients, RGB patterns, and embedded PNG or baseline
    JPEG image fills. Image framing supports stretch, explicit tile scale/offset/
    alignment/flip, or canonical center; crop is limited to stretch mode.
    Direct slide backgrounds accept none, RGB solid, bounded linear gradient, or
    embedded image fill with the same three framing modes but no crop or effects.
    Center is a 100-percent center-aligned tile and may repeat for a small asset.
    Image sources are read-only /mnt/user-data paths locked with the document edit;
    raw XML, base64, data URIs, external URLs, and linked images are unsupported.
    Direct line fills accept solid, no-fill, or bounded linear gradients.
    DOCX text filters and replacement occurrence controls are invalid inside
    these PPTX selectors. Each formatting operation has exactly type, its typed
    selector, and formatting; occurrence and require_match are not accepted.

    Args:
        source_path: Absolute source DOCX, XLSX, or PPTX path under thread user-data.
        output_path: Distinct same-format destination under workspace or outputs.
        operations: Ordered format-specific typed operations to apply as one transaction.
        overwrite_output: Allow replacement of an existing destination when it differs from the source.
    """
    try:
        source = normalize_office_path(source_path)
        output = normalize_office_path(output_path, writable=True)
        if PurePosixPath(source).suffix.lower() != PurePosixPath(output).suffix.lower():
            raise OfficeOperationError("Office source and output must use the same document format")
        image_asset_paths = _pptx_image_asset_paths(operations) if PurePosixPath(source).suffix.lower() == ".pptx" else {}
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)

        with ExitStack() as stack:
            for path in sorted({source, output, *image_asset_paths.values()}):
                stack.enter_context(get_file_operation_lock(sandbox, path))
            if source == output:
                raise OfficeOperationError("In-place Office edits are not supported; choose a distinct output_path")
            if source != output and not overwrite_output and _output_exists(sandbox, output):
                raise FileExistsError(f"Destination already exists: {output}. Choose a new path or set overwrite_output=true")
            document = sandbox.download_file(source)
            image_payloads_by_path = {path: sandbox.download_file(path) for path in sorted(set(image_asset_paths.values()))}
            image_assets = {requested_path: image_payloads_by_path[canonical_path] for requested_path, canonical_path in image_asset_paths.items()}
            edited, reports = office_engine.edit(
                document,
                suffix=PurePosixPath(source).suffix,
                operations=operations,
                image_assets=image_assets,
            )
            validation = office_engine.validate(edited, suffix=PurePosixPath(output).suffix)
            output_path = PurePosixPath(output)
            staging_path = str(output_path.parent / f".{output_path.name}.stage-{uuid4().hex}")
            sandbox.update_file(staging_path, edited)
            sandbox.replace_file(staging_path, output)
            gateway_mirror_available = _mirror_binary_to_gateway_if_needed(runtime, output, edited)

        response = {
            "ok": True,
            "commit_status": "committed",
            "gateway_mirror_status": "available" if gateway_mirror_available else "unavailable",
            "source_path": source,
            "output_path": output,
            "operations": reports,
            "change_count": sum(report["match_count"] for report in reports),
            "replacement_count": sum(
                report["match_count"]
                for report in reports
                if report["type"]
                in {
                    "replace_text",
                    "replace_pptx_text",
                    "replace_pptx_picture_sources",
                }
            ),
            "validation": validation,
        }
        if not gateway_mirror_available:
            response["warning"] = "The output is committed in the sandbox but is not available to Gateway-local file tools."
        return _json(response)
    except Exception as exc:
        return _json({"ok": False, "error": _known_error(exc)})


async def _office_edit_async(
    runtime: Runtime,
    source_path: str,
    output_path: str,
    operations: list[OfficeEditOperation],
    overwrite_output: bool = False,
) -> str:
    await ensure_sandbox_initialized_async(runtime)
    return await asyncio.to_thread(
        office_edit_tool.func,
        runtime,
        source_path,
        output_path,
        operations,
        overwrite_output,
    )


office_edit_tool.coroutine = _office_edit_async


@tool("office_render", parse_docstring=True)
def office_render_tool(
    runtime: Runtime,
    path: str,
    output_dir: str,
    start_page: int = 1,
    max_pages: int = 1,
    dpi: int = 120,
) -> str:
    """Render a bounded DOCX, XLSX, or PPTX page window to PNG files for visual review.

    The output directory must be new or empty. A completion manifest is written
    only after every page image succeeds. Rendering does not itself pass visual QA.
    When visual_review_status is pending, inspect every returned page_path with
    view_image in a separate model step before presenting the document. When it
    is external_review_required, do not claim visual QA passed.
    PPTX output is static and does not verify animations or transition behavior.

    Args:
        path: Absolute DOCX or XLSX path under /mnt/user-data/uploads, workspace, or outputs.
        output_dir: New or empty directory under workspace or outputs for PNG pages.
        start_page: First 1-based document page to render.
        max_pages: Maximum consecutive pages to render, from 1 through 12.
        dpi: Raster resolution from 96 through 200 DPI.
    """
    try:
        source_path = normalize_office_path(path)
        destination = normalize_office_output_dir(output_dir)
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)

        with ExitStack() as stack:
            for locked_path in sorted({source_path, destination}):
                stack.enter_context(get_file_operation_lock(sandbox, locked_path))
            if _directory_has_entries(sandbox, destination):
                raise FileExistsError(f"Render output directory is not empty: {destination}. Choose a new directory.")

            document = sandbox.download_file(source_path)
            rendered = office_engine.render(
                document,
                suffix=PurePosixPath(source_path).suffix,
                start_page=start_page,
                max_pages=max_pages,
                dpi=dpi,
            )

            page_paths: list[str] = []
            page_metadata: list[dict] = []
            gateway_images_available = True
            try:
                for page in rendered.pages:
                    output_path = f"{destination}/{page.filename}"
                    if _output_exists(sandbox, output_path):
                        raise FileExistsError(f"Render output already exists: {output_path}. Choose a new directory.")
                    sandbox.update_file(output_path, page.data)
                    gateway_images_available = _mirror_binary_to_gateway_if_needed(runtime, output_path, page.data) and gateway_images_available
                    page_paths.append(output_path)
                    page_metadata.append(
                        {
                            "page": page.page,
                            **({"source_slide": page.source_slide} if page.source_slide is not None else {}),
                            "path": output_path,
                            "width": page.width,
                            "height": page.height,
                            "sha256": page.sha256,
                        }
                    )

                review_status, next_action = _visual_review_contract(
                    runtime,
                    gateway_images_available=gateway_images_available,
                )
                manifest_path = f"{destination}/render-manifest.json"
                manifest = {
                    "complete": True,
                    "format": rendered.format,
                    "source_path": source_path,
                    "source_sha256": rendered.source_sha256,
                    "renderer": rendered.renderer,
                    "renderer_version": rendered.renderer_version,
                    "pdfium_version": rendered.pdfium_version,
                    "pipeline_fingerprint": rendered.pipeline_fingerprint,
                    "page_count": rendered.page_count,
                    "start_page": rendered.start_page,
                    "end_page": rendered.pages[-1].page,
                    "requested_max_pages": max_pages,
                    "dpi": rendered.dpi,
                    "has_more": rendered.has_more,
                    "pages": page_metadata,
                    "visual_review_status": review_status,
                    "gateway_page_access": "available" if gateway_images_available else "unavailable",
                }
                manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                sandbox.update_file(manifest_path, manifest_bytes)
                gateway_manifest_available = _mirror_binary_to_gateway_if_needed(runtime, manifest_path, manifest_bytes)
            except Exception as exc:
                if page_paths:
                    raise OfficeOperationError(f"Render output is incomplete in {destination}; do not review it and retry with a new directory") from exc
                raise

        gateway_mirror_available = gateway_images_available and gateway_manifest_available
        response = {
            "ok": True,
            "commit_status": "committed",
            "gateway_mirror_status": "available" if gateway_mirror_available else "unavailable",
            "source_path": source_path,
            "output_dir": destination,
            "manifest_path": manifest_path,
            "page_count": rendered.page_count,
            "rendered": len(rendered.pages),
            "has_more": rendered.has_more,
            "page_paths": page_paths,
            "source_sha256": rendered.source_sha256,
            "pipeline_fingerprint": rendered.pipeline_fingerprint,
            "visual_review_status": review_status,
            "next_action": next_action,
        }
        if not gateway_mirror_available:
            response["warning"] = "Render artifacts are committed in the sandbox but are not all available to Gateway-local file tools."
        return _json(response)
    except Exception as exc:
        return _json({"ok": False, "error": _known_error(exc)})


async def _office_render_async(
    runtime: Runtime,
    path: str,
    output_dir: str,
    start_page: int = 1,
    max_pages: int = 1,
    dpi: int = 120,
) -> str:
    await ensure_sandbox_initialized_async(runtime)
    return await asyncio.to_thread(
        office_render_tool.func,
        runtime,
        path,
        output_dir,
        start_page,
        max_pages,
        dpi,
    )


office_render_tool.coroutine = _office_render_async
