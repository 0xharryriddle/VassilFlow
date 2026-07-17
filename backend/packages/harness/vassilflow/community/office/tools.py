"""Agent-facing VassilFlow Office tools backed by structured sandbox I/O."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

from langchain.tools import tool

from vassilflow.config.paths import get_paths
from vassilflow.runtime.user_context import resolve_runtime_user_id
from vassilflow.sandbox.file_operation_lock import get_file_operation_lock
from vassilflow.sandbox.tools import (
    ensure_sandbox_initialized,
    ensure_sandbox_initialized_async,
    ensure_thread_directories_exist,
)
from vassilflow.tools.types import Runtime

from .engine import office_engine
from .errors import OfficeError, OfficeOperationError
from .generation import PresentationIntent, compile_presentation
from .models import (
    OfficeEditOperation,
    PptxObjectSelector,
    PptxPictureSourceReplacementOperation,
    PptxShapeFormatOperation,
    PptxSlideBackgroundFormatOperation,
)
from .policy import normalize_office_image_path, normalize_office_output_dir, normalize_office_path
from .revisions import RENDER_MANIFEST_SCHEMA, OfficeRevisionStore
from .selection import PPTX_SELECTION_SCHEMA, resolve_pptx_selection
from .templates import OfficeTemplateStore

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


def _runtime_thread_id(runtime: Runtime) -> str | None:
    context = getattr(runtime, "context", None)
    if isinstance(context, dict) and context.get("thread_id"):
        return str(context["thread_id"])
    config = getattr(runtime, "config", None)
    if isinstance(config, dict):
        configurable = config.get("configurable")
        if isinstance(configurable, dict) and configurable.get("thread_id"):
            return str(configurable["thread_id"])
    return None


def _office_revision_store(runtime: Runtime) -> OfficeRevisionStore:
    user_id = resolve_runtime_user_id(runtime)
    return OfficeRevisionStore(get_paths().user_office_dir(user_id))


def _runtime_office_selection(runtime: Runtime) -> dict | None:
    context = getattr(runtime, "context", None)
    selection = context.get("office_selection") if isinstance(context, dict) else None
    if selection is None:
        return None
    if not isinstance(selection, dict) or selection.get("schema") != PPTX_SELECTION_SCHEMA:
        raise OfficeOperationError("Office selection context is invalid")
    return selection


def _path_is_within_selection(path: object, root: str) -> bool:
    return isinstance(path, str) and (path == root or path.startswith(f"{root}/"))


def _operation_target_paths(operation: OfficeEditOperation) -> list[str]:
    payload = operation.model_dump()
    operation_type = payload.get("type")
    if operation_type == "replace_pptx_text":
        paths = payload.get("paths")
        return list(paths) if isinstance(paths, list) else []
    selector_field = {
        "format_pptx_runs": "runs",
        "format_pptx_paragraphs": "paragraphs",
        "format_pptx_shapes": "shapes",
        "format_pptx_lines": "lines",
        "replace_pptx_picture_sources": "pictures",
    }.get(str(operation_type))
    if selector_field is None:
        return []
    selector = payload.get(selector_field)
    targets = selector.get("targets") if isinstance(selector, dict) else None
    if not isinstance(targets, list):
        return []
    return [target["path"] for target in targets if isinstance(target, dict) and isinstance(target.get("path"), str)]


def _validate_selected_operations(
    operations: list[OfficeEditOperation],
    *,
    selection: dict,
) -> None:
    root = selection.get("object_path")
    allowed = selection.get("allowed_operations")
    if not isinstance(root, str) or not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise OfficeOperationError("Office selection edit scope is invalid")
    allowed_set = set(allowed)
    if not operations:
        raise OfficeOperationError("Office selection edit requires at least one operation")
    for operation in operations:
        if operation.type not in allowed_set:
            raise OfficeOperationError(f"Office selection does not allow operation type {operation.type}")
        target_paths = _operation_target_paths(operation)
        if not target_paths or any(not _path_is_within_selection(path, root) for path in target_paths):
            raise OfficeOperationError("Office edit operation escapes the selected object scope")


def _validate_selected_receipt(
    receipt: dict,
    *,
    selection: dict,
    operation_count: int,
) -> None:
    root = selection["object_path"]
    allowed = set(selection["allowed_operations"])
    if (
        receipt.get("operation_count") != operation_count
        or receipt.get("operation_ids_truncated") is not False
        or receipt.get("operations_truncated") is not False
        or receipt.get("operation_ids_returned") != operation_count
        or receipt.get("operations_returned") != operation_count
    ):
        raise OfficeOperationError("Office selection receipt has incomplete operation evidence")
    operation_records = receipt.get("operations")
    if not isinstance(operation_records, list) or len(operation_records) != operation_count:
        raise OfficeOperationError("Office selection receipt operation evidence is invalid")
    for record in operation_records:
        paths = record.get("target_paths") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or record.get("type") not in allowed
            or record.get("target_paths_truncated") is not False
            or record.get("target_path_count") != record.get("target_paths_returned")
            or not isinstance(paths, list)
            or not paths
            or any(not _path_is_within_selection(path, root) for path in paths)
        ):
            raise OfficeOperationError("Office selection receipt escapes the selected object scope")

    semantic = receipt.get("semantic_changes")
    if (
        not isinstance(semantic, dict)
        or semantic.get("coverage") != "complete"
        or semantic.get("changed_target_paths_truncated") is not False
        or semantic.get("semantic_deltas_truncated") is not False
        or semantic.get("changed_target_paths_returned") != semantic.get("changed_target_count")
        or semantic.get("semantic_deltas_returned") != semantic.get("semantic_delta_count")
    ):
        raise OfficeOperationError("Office selection receipt has incomplete semantic evidence")
    changed_paths = semantic.get("changed_target_paths")
    deltas = semantic.get("semantic_deltas")
    if (
        not isinstance(changed_paths, list)
        or any(not _path_is_within_selection(path, root) for path in changed_paths)
        or not isinstance(deltas, list)
        or any(not isinstance(delta, dict) or not _path_is_within_selection(delta.get("path"), root) for delta in deltas)
    ):
        raise OfficeOperationError("Office selection semantic changes escape the selected object scope")


def _load_selected_project_source(
    runtime: Runtime,
    selection: dict,
) -> tuple[bytes, dict]:
    required_strings = (
        "project_id",
        "revision_id",
        "source_sha256",
        "object_path",
        "object_fingerprint",
    )
    if any(not isinstance(selection.get(field), str) for field in required_strings) or not isinstance(selection.get("slide_index"), int) or isinstance(selection.get("slide_index"), bool):
        raise OfficeOperationError("Office selection context is incomplete")
    store = _office_revision_store(runtime)
    project = store.load_project(selection["project_id"])
    if project["current_revision_id"] != selection["revision_id"]:
        raise OfficeOperationError("Office project has a newer current revision; reopen the selection")
    revision, document = store.read_revision_artifact(
        selection["project_id"],
        selection["revision_id"],
    )
    if revision["format"] != "pptx" or project["format"] != "pptx":
        raise OfficeOperationError("Office object selection requires a PPTX project")
    if selection.get("artifact_size_bytes") != len(document):
        raise OfficeOperationError("Office selection artifact identity is stale")
    resolved = resolve_pptx_selection(
        document,
        slide_index=selection["slide_index"],
        source_sha256=selection["source_sha256"],
        object_path=selection["object_path"],
        object_fingerprint=selection["object_fingerprint"],
    )
    return document, {
        **resolved,
        "project_id": selection["project_id"],
        "revision_id": selection["revision_id"],
        "artifact_size_bytes": len(document),
    }


def _project_template_resource(
    runtime: Runtime,
    *,
    project_id: str | None,
    parent_revision_id: str | None,
    source: bytes,
    suffix: str,
) -> dict | None:
    if (project_id is None) != (parent_revision_id is None):
        raise OfficeOperationError("project_id and parent_revision_id must be provided together")
    if project_id is None or parent_revision_id is None:
        return None
    store = _office_revision_store(runtime)
    project = store.load_project(project_id)
    if project["current_revision_id"] != parent_revision_id:
        raise OfficeOperationError("Office project has a newer current revision; retry from that exact parent")
    store.verify_revision_source(
        project_id=project_id,
        revision_id=parent_revision_id,
        source=source,
        suffix=suffix,
    )
    revision = store.load_project_revision(project_id, parent_revision_id)
    resources = revision.get("resource_versions")
    template = resources.get("template") if isinstance(resources, dict) else None
    return template if isinstance(template, dict) else None


def _persist_office_revision(
    runtime: Runtime,
    *,
    source: bytes,
    result: bytes,
    suffix: str,
    source_path: str,
    output_path: str,
    receipt: dict,
    source_validation: dict,
    result_validation: dict,
    project_id: str | None,
    parent_revision_id: str | None,
    template_resource: dict | None = None,
    template_policy: dict | None = None,
) -> dict:
    commit = _office_revision_store(runtime).commit_edit(
        source=source,
        result=result,
        suffix=suffix,
        source_path=source_path,
        output_path=output_path,
        thread_id=_runtime_thread_id(runtime),
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
        project_id=project_id,
        parent_revision_id=parent_revision_id,
        template_resource=template_resource,
        template_policy=template_policy,
    )
    return commit.as_tool_metadata()


def _persist_generated_presentation(
    runtime: Runtime,
    *,
    artifact: bytes,
    output_path: str,
    intent: PresentationIntent,
    receipt: dict,
    preflight: dict,
    validation: dict,
) -> dict:
    commit = _office_revision_store(runtime).commit_generation(
        artifact=artifact,
        output_path=output_path,
        thread_id=_runtime_thread_id(runtime),
        intent=intent.model_dump(
            by_alias=True,
            exclude_none=True,
            mode="json",
        ),
        receipt=receipt,
        preflight=preflight,
        validation=validation,
    )
    return commit.as_tool_metadata()


def _resolve_office_render_store(
    runtime: Runtime,
    *,
    project_id: str | None,
    revision_id: str | None,
    source: bytes,
    suffix: str,
) -> OfficeRevisionStore | None:
    if (project_id is None) != (revision_id is None):
        raise OfficeOperationError("project_id and revision_id must be provided together")
    if project_id is None or revision_id is None:
        return None
    store = _office_revision_store(runtime)
    store.verify_revision_source(
        project_id=project_id,
        revision_id=revision_id,
        source=source,
        suffix=suffix,
    )
    return store


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
    analysis_mode: Literal["inspect", "pptx_quality_preflight"] = "inspect",
) -> str:
    """Inspect an Office file or run read-only PPTX quality preflight.

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
        analysis_mode: Use inspect for bounded DOCX, XLSX, or PPTX structure.
            Use pptx_quality_preflight for package-wide, source-hash-bound static
            quality evidence, including supported picture PPI after source crop,
            destination fill rectangles, and bounded nested-group transforms,
            plus rectangular frame/slide intersection evidence. Preflight does
            not mutate, render, or claim visual QA, does not detect generic
            overlap, and cannot be combined with inspect windows, selectors, or
            detail flags.
    """
    try:
        source_path = normalize_office_path(path)
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        document = sandbox.download_file(source_path)
        suffix = PurePosixPath(source_path).suffix
        if analysis_mode == "pptx_quality_preflight":
            if suffix.lower() != ".pptx":
                raise OfficeOperationError("PPTX quality preflight requires a .pptx document")
            incompatible_options = (
                start_paragraph != 1
                or max_paragraphs != 100
                or include_runs
                or sheet_name is not None
                or cell_range is not None
                or include_cell_styles
                or start_slide != 1
                or max_slides != 20
                or include_pptx_formatting
                or pptx_selector is not None
                or include_pptx_annotations
                or include_pptx_dynamics
                or include_pptx_media_gc_plan
            )
            if incompatible_options:
                raise OfficeOperationError("PPTX quality preflight cannot be combined with inspect windows, selectors, or detail flags")
            result = office_engine.preflight(document, suffix=suffix)
        elif analysis_mode == "inspect":
            result = office_engine.inspect(
                document,
                suffix=suffix,
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
        else:
            raise OfficeOperationError(f"Unsupported Office inspection analysis mode: {analysis_mode}")
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
    analysis_mode: Literal["inspect", "pptx_quality_preflight"] = "inspect",
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
        analysis_mode=analysis_mode,
    )


office_inspect_tool.coroutine = _office_inspect_async


@tool("office_generate", parse_docstring=True)
def office_generate_tool(
    runtime: Runtime,
    intent: PresentationIntent,
    output_path: str,
    overwrite_output: bool = False,
) -> str:
    """Generate a new editable native PPTX from versioned semantic intent.

    The intent contains stable slide and element IDs, semantic layout roles,
    bounded theme tokens, text, image references, and simple decorations. It
    cannot contain raw OOXML or object coordinates. The deterministic compiler
    creates native title placeholders, text boxes, embedded pictures, and
    shapes, then runs package validation and source-bound PPTX quality preflight.
    A successful call creates a trusted Office Project whose initial revision
    stores the exact intent, object-path generation receipt, and preflight
    evidence. Render that returned project and revision with office_render and
    review every slide before presenting the output.

    Args:
        intent: Versioned presentation intent using semantic layouts and stable IDs.
        output_path: Distinct .pptx destination under /mnt/user-data/workspace or /mnt/user-data/outputs.
        overwrite_output: Replace an existing output path only when explicitly true.
    """

    revision_metadata: dict | None = None
    try:
        output = normalize_office_path(output_path, writable=True)
        if PurePosixPath(output).suffix.lower() != ".pptx":
            raise OfficeOperationError("office_generate output_path must end with .pptx")
        image_asset_paths = {requested: normalize_office_image_path(requested) for requested in intent.image_paths()}
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)

        with ExitStack() as stack:
            for path in sorted({output, *image_asset_paths.values()}):
                stack.enter_context(get_file_operation_lock(sandbox, path))
            if not overwrite_output and _output_exists(sandbox, output):
                raise FileExistsError(f"Destination already exists: {output}. Choose a new path or set overwrite_output=true")
            payloads = {canonical_path: sandbox.download_file(canonical_path) for canonical_path in sorted(set(image_asset_paths.values()))}
            image_assets = {requested_path: payloads[canonical_path] for requested_path, canonical_path in image_asset_paths.items()}
            generated, generation_receipt = compile_presentation(
                intent,
                image_assets=image_assets,
            )
            validation = office_engine.validate(generated, suffix=".pptx")
            preflight = office_engine.preflight(generated, suffix=".pptx")
            summary = preflight.get("summary")
            severity_counts = summary.get("findings_by_severity") if isinstance(summary, dict) else None
            if not isinstance(summary, dict) or not isinstance(severity_counts, dict) or summary.get("findings_truncated") is not False or severity_counts.get("error", 0) != 0:
                raise OfficeOperationError("Generated presentation did not pass complete static preflight")
            revision_metadata = _persist_generated_presentation(
                runtime,
                artifact=generated,
                output_path=output,
                intent=intent,
                receipt=generation_receipt,
                preflight=preflight,
                validation=validation,
            )

            output_file = PurePosixPath(output)
            staging_path = str(output_file.parent / f".{output_file.name}.stage-{uuid4().hex}")
            sandbox.update_file(staging_path, generated)
            sandbox.replace_file(staging_path, output)
            gateway_mirror_available = _mirror_binary_to_gateway_if_needed(
                runtime,
                output,
                generated,
            )

        response = {
            "ok": True,
            "commit_status": "committed",
            "gateway_mirror_status": ("available" if gateway_mirror_available else "unavailable"),
            "output_path": output,
            "generation_receipt": generation_receipt,
            "preflight": preflight,
            "validation": validation,
            **revision_metadata,
        }
        if not gateway_mirror_available:
            response["warning"] = "The output is committed in the trusted Office project but is not available to Gateway-local file tools."
        return _json(response)
    except Exception as exc:
        response = {"ok": False, "error": _known_error(exc)}
        if revision_metadata is not None:
            response.update(
                {
                    "commit_status": "revision_committed_output_failed",
                    "warning": ("The trusted generated Office revision is committed, but output_path could not be materialized. Keep the returned project and revision IDs for recovery."),
                    **revision_metadata,
                }
            )
        return _json(response)


async def _office_generate_async(
    runtime: Runtime,
    intent: PresentationIntent,
    output_path: str,
    overwrite_output: bool = False,
) -> str:
    await ensure_sandbox_initialized_async(runtime)
    return await asyncio.to_thread(
        office_generate_tool.func,
        runtime,
        intent,
        output_path,
        overwrite_output=overwrite_output,
    )


office_generate_tool.coroutine = _office_generate_async


@tool("office_edit", parse_docstring=True)
def office_edit_tool(
    runtime: Runtime,
    source_path: str | None,
    output_path: str,
    operations: list[OfficeEditOperation],
    overwrite_output: bool = False,
    project_id: str | None = None,
    parent_revision_id: str | None = None,
) -> str:
    """Apply transactional structured edits to a DOCX, XLSX, or PPTX.

    The source is always read immediately before editing. Uploads remain immutable:
    output_path must be a distinct path under workspace or outputs. All operations
    succeed and the resulting package validates before a staged atomic replacement.
    Every successful edit creates an immutable revision in trusted user-scoped storage
    and returns its project and revision IDs. Omit both IDs to start a new project;
    pass both the returned project ID and current revision ID on the next edit in that
    project. Stale parent IDs and source bytes that differ from the parent artifact are
    rejected. Each edit also returns a bounded semantic change receipt built before commit,
    including exact source/result SHA-256, deterministic operation IDs, actual object
    paths, package part/relationship changes, and net semantic deltas.
    The receipt complements package validation, rendering, and visual review.
    PPTX supports paragraph-local literal replacement, source-only embedded-picture
    replacement, plus bounded direct run, paragraph, shape, shape-or-connector
    line, and direct slide-background formatting. Picture targets use exact
    authored-ID paths, object names, and inspected source SHA-256 guards; replacement
    preserves crop, framing, effects, geometry, alt text, and interactions. Other
    formatting targets use expected text, object name, or slide part name to reject
    stale paths. Every PPTX formatting selector contains only targets. Direct shape
    fills accept typed RGB solid, no-fill, bounded gradients, RGB patterns, and
    embedded PNG or baseline
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
    When the runtime carries a verified Office preview selection, pass source_path=null.
    The tool then reads the exact current canonical PPTX revision, derives project_id
    and parent_revision_id from trusted context, and rejects operations or semantic
    receipt evidence outside the selected object path.

    Args:
        source_path: Absolute source path under thread user-data, or null when editing a verified Office project selection.
        output_path: Distinct same-format destination under workspace or outputs.
        operations: Ordered format-specific typed operations to apply as one transaction.
        overwrite_output: Allow replacement of an existing destination when it differs from the source.
        project_id: Existing Office project ID; omit with parent_revision_id to start a project.
        parent_revision_id: Expected current revision ID for an existing project; must accompany project_id.
    """
    revision_metadata: dict | None = None
    try:
        runtime_selection = _runtime_office_selection(runtime)
        if runtime_selection is not None and source_path is not None:
            raise OfficeOperationError("source_path must be null for a verified Office project selection")
        if runtime_selection is None and source_path is None:
            raise OfficeOperationError("source_path is required without an Office project selection")
        source = normalize_office_path(source_path) if source_path is not None else None
        output = normalize_office_path(output_path, writable=True)
        suffix = ".pptx" if runtime_selection is not None else PurePosixPath(source or "").suffix
        if suffix.lower() != PurePosixPath(output).suffix.lower():
            raise OfficeOperationError("Office source and output must use the same document format")
        image_asset_paths = _pptx_image_asset_paths(operations) if suffix.lower() == ".pptx" else {}
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)

        with ExitStack() as stack:
            locked_paths = {output, *image_asset_paths.values()}
            if source is not None:
                locked_paths.add(source)
            for path in sorted(locked_paths):
                stack.enter_context(get_file_operation_lock(sandbox, path))
            if source is not None and source == output:
                raise OfficeOperationError("In-place Office edits are not supported; choose a distinct output_path")
            if not overwrite_output and _output_exists(sandbox, output):
                raise FileExistsError(f"Destination already exists: {output}. Choose a new path or set overwrite_output=true")
            if runtime_selection is not None:
                document, verified_selection = _load_selected_project_source(
                    runtime,
                    runtime_selection,
                )
                if project_id is not None and project_id != verified_selection["project_id"]:
                    raise OfficeOperationError("project_id does not match the verified Office selection")
                if parent_revision_id is not None and parent_revision_id != verified_selection["revision_id"]:
                    raise OfficeOperationError("parent_revision_id does not match the verified Office selection")
                project_id = verified_selection["project_id"]
                parent_revision_id = verified_selection["revision_id"]
                _validate_selected_operations(
                    operations,
                    selection=verified_selection,
                )
                source_provenance_path = f"/office-projects/{project_id}/revisions/{parent_revision_id}/artifact.pptx"
            else:
                document = sandbox.download_file(source)
                verified_selection = None
                source_provenance_path = source or ""
            template_resource = _project_template_resource(
                runtime,
                project_id=project_id,
                parent_revision_id=parent_revision_id,
                source=document,
                suffix=suffix,
            )
            source_validation = office_engine.validate(
                document,
                suffix=suffix,
            )
            image_payloads_by_path = {path: sandbox.download_file(path) for path in sorted(set(image_asset_paths.values()))}
            image_assets = {requested_path: image_payloads_by_path[canonical_path] for requested_path, canonical_path in image_asset_paths.items()}
            edited, reports, receipt = office_engine.edit_with_receipt(
                document,
                suffix=suffix,
                operations=operations,
                image_assets=image_assets,
            )
            if verified_selection is not None:
                _validate_selected_receipt(
                    receipt,
                    selection=verified_selection,
                    operation_count=len(operations),
                )
            validation = office_engine.validate(edited, suffix=PurePosixPath(output).suffix)
            template_policy = None
            if template_resource is not None:
                template_store = OfficeTemplateStore(get_paths().user_office_dir(resolve_runtime_user_id(runtime)))
                template_policy = template_store.enforce_published_edit_policy(
                    template_resource["template_id"],
                    template_resource["version"],
                    source=document,
                    result=edited,
                    operations=operations,
                    receipt=receipt,
                )
            revision_metadata = _persist_office_revision(
                runtime,
                source=document,
                result=edited,
                suffix=PurePosixPath(output).suffix,
                source_path=source_provenance_path,
                output_path=output,
                receipt=receipt,
                source_validation=source_validation,
                result_validation=validation,
                project_id=project_id,
                parent_revision_id=parent_revision_id,
                template_resource=template_resource,
                template_policy=template_policy,
            )
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
            "receipt": receipt,
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
            **revision_metadata,
        }
        if not gateway_mirror_available:
            response["warning"] = "The output is committed in the sandbox but is not available to Gateway-local file tools."
        return _json(response)
    except Exception as exc:
        response = {"ok": False, "error": _known_error(exc)}
        if revision_metadata is not None:
            response.update(
                {
                    "commit_status": "revision_committed_output_failed",
                    "warning": ("The trusted Office revision is committed, but output_path could not be materialized. Keep the returned project and revision IDs for recovery."),
                    **revision_metadata,
                }
            )
        return _json(response)


async def _office_edit_async(
    runtime: Runtime,
    source_path: str | None,
    output_path: str,
    operations: list[OfficeEditOperation],
    overwrite_output: bool = False,
    project_id: str | None = None,
    parent_revision_id: str | None = None,
) -> str:
    await ensure_sandbox_initialized_async(runtime)
    return await asyncio.to_thread(
        office_edit_tool.func,
        runtime,
        source_path,
        output_path,
        operations,
        overwrite_output,
        project_id,
        parent_revision_id,
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
    project_id: str | None = None,
    revision_id: str | None = None,
) -> str:
    """Render a bounded DOCX, XLSX, or PPTX page window to PNG files for visual review.

    The output directory must be new or empty. A completion manifest is written
    only after every page image succeeds. Rendering does not itself pass visual QA.
    Pass both project_id and revision_id from office_edit to bind this render to
    the exact immutable source revision and persist its manifest and preview PNGs
    in trusted user-scoped storage. Omit both only for a thread-local render.
    When visual_review_status is pending, inspect every returned page_path with
    view_image in a separate model step before presenting the document. When it
    is external_review_required, do not claim visual QA passed.
    PPTX output is static and does not verify animations or transition behavior.

    Args:
        path: Absolute DOCX, XLSX, or PPTX path under /mnt/user-data/uploads, workspace, or outputs.
        output_dir: New or empty directory under workspace or outputs for PNG pages.
        start_page: First 1-based document page to render.
        max_pages: Maximum consecutive pages to render, from 1 through 12.
        dpi: Raster resolution from 96 through 200 DPI.
        project_id: Office project ID to receive durable render evidence; must accompany revision_id.
        revision_id: Exact Office revision ID whose artifact bytes are being rendered.
    """
    render_evidence_metadata: dict | None = None
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
            suffix = PurePosixPath(source_path).suffix
            render_store = _resolve_office_render_store(
                runtime,
                project_id=project_id,
                revision_id=revision_id,
                source=document,
                suffix=suffix,
            )
            rendered = office_engine.render(
                document,
                suffix=suffix,
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
                    "schema": RENDER_MANIFEST_SCHEMA,
                    "complete": True,
                    "format": rendered.format,
                    "source_path": source_path,
                    "source_sha256": rendered.source_sha256,
                    "source_size_bytes": len(document),
                    "output_dir": destination,
                    "manifest_path": manifest_path,
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
                if project_id is not None and revision_id is not None:
                    manifest["project_id"] = project_id
                    manifest["revision_id"] = revision_id
                if render_store is not None and project_id is not None and revision_id is not None:
                    render_evidence_metadata = render_store.commit_render_evidence(
                        project_id=project_id,
                        revision_id=revision_id,
                        source=document,
                        suffix=suffix,
                        manifest=manifest,
                        pages=rendered.pages,
                        thread_id=_runtime_thread_id(runtime),
                    ).as_tool_metadata()
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
        if render_evidence_metadata is not None:
            response.update(render_evidence_metadata)
        if not gateway_mirror_available:
            response["warning"] = "Render artifacts are committed in the sandbox but are not all available to Gateway-local file tools."
        return _json(response)
    except Exception as exc:
        response = {"ok": False, "error": _known_error(exc)}
        if render_evidence_metadata is not None:
            response.update(
                {
                    "commit_status": "render_evidence_committed_output_failed",
                    "warning": ("Trusted render evidence is committed, but the thread render manifest is incomplete. Keep the returned render evidence ID for recovery."),
                    **render_evidence_metadata,
                }
            )
        return _json(response)


async def _office_render_async(
    runtime: Runtime,
    path: str,
    output_dir: str,
    start_page: int = 1,
    max_pages: int = 1,
    dpi: int = 120,
    project_id: str | None = None,
    revision_id: str | None = None,
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
        project_id,
        revision_id,
    )


office_render_tool.coroutine = _office_render_async
