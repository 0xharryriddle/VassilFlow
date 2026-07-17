"""Trusted API for user-scoped Office projects, evidence, and save points."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from vassilflow.community.office.errors import (
    OfficeOperationError,
    OfficePackageError,
    OfficeRenderError,
    OfficeRenderUnavailableError,
    OfficeRevisionConflictError,
    OfficeRevisionError,
    OfficeRevisionIntegrityError,
    OfficeTemplateError,
)
from vassilflow.community.office.project_workflow import OfficeProjectWorkflowService
from vassilflow.community.office.revisions import (
    OfficeRevisionStore,
    resolve_render_evidence_set,
)
from vassilflow.community.office.selection import build_pptx_selection_surface
from vassilflow.community.office.templates import OfficeTemplateStore
from vassilflow.config.paths import get_paths
from vassilflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/office", tags=["office-projects"])

_MAX_PROJECTS = 500
_MAX_REVISIONS = 500
_MAX_RENDER_EVIDENCE = 500
_OFFICE_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class OfficeArtifactIdentity(BaseModel):
    sha256: str
    size_bytes: int


class OfficePreviewPageResponse(BaseModel):
    page: int
    source_slide: int | None = None
    width: int
    height: int
    sha256: str
    url: str


class OfficeRenderEvidenceResponse(BaseModel):
    evidence_id: str
    revision_id: str
    created_at: str
    source_sha256: str
    page_count: int
    rendered_page_count: int
    start_page: int
    end_page: int
    has_more: bool
    visual_review_status: str
    renderer: str
    renderer_version: str
    pipeline_fingerprint: str
    preview_pages: list[OfficePreviewPageResponse]


class OfficeRevisionQualityResponse(BaseModel):
    package_validation_status: str
    preflight_status: str
    render_evidence_status: str
    visual_review_status: str


class OfficeProjectReviewResponse(BaseModel):
    review_id: str
    revision_id: str
    created_at: str
    status: str
    note: str | None
    evidence_ids: list[str]
    page_count: int
    render_set_sha256: str


class OfficeFinalSelectionResponse(BaseModel):
    selection_id: str
    revision_id: str
    review_id: str
    created_at: str
    artifact: OfficeArtifactIdentity


class OfficeGenerationCompilerResponse(BaseModel):
    id: str
    version: int


class OfficeGenerationIntentIdentityResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: str = Field(alias="schema")
    sha256: str
    size_bytes: int


class OfficeGenerationPresentationResponse(BaseModel):
    title: str
    aspect_ratio: str
    slide_width_emu: int
    slide_height_emu: int
    slide_count: int
    object_count: int
    mapping_sha256: str


class OfficeGenerationObjectResponse(BaseModel):
    slide_id: str
    element_id: str
    element_kind: str
    role: str
    object_path: str
    object_kind: str
    authored_name: str


class OfficeGenerationSlideResponse(BaseModel):
    slide_id: str
    slide_index: int
    slide_path: str
    layout: str
    purpose: str
    object_count: int
    objects: list[OfficeGenerationObjectResponse]


class OfficeGenerationAssetResponse(BaseModel):
    element_id: str
    sha256: str
    size_bytes: int
    format: str
    width_px: int
    height_px: int
    alt_text_sha256: str


class OfficeGenerationBoundsResponse(BaseModel):
    slides_returned: int
    slides_truncated: bool
    objects_returned: int
    objects_truncated: bool
    assets_returned: int
    assets_truncated: bool


class OfficeGenerationReceiptResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: str = Field(alias="schema")
    compiler: OfficeGenerationCompilerResponse
    intent: OfficeGenerationIntentIdentityResponse
    output: OfficeArtifactIdentity
    presentation: OfficeGenerationPresentationResponse
    slides: list[OfficeGenerationSlideResponse]
    assets: list[OfficeGenerationAssetResponse]
    bounds: OfficeGenerationBoundsResponse


class OfficeGenerationPreflightResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: str = Field(alias="schema")
    source_sha256: str
    source_size_bytes: int
    slide_count: int
    object_count: int
    picture_count: int
    finding_count: int
    findings_returned: int
    findings_truncated: bool
    findings_by_severity: dict[str, int]


class OfficeRevisionSummaryResponse(BaseModel):
    revision_id: str
    parent_revision_id: str | None
    sequence: int
    kind: Literal["baseline", "generation", "edit", "restore"]
    created_at: str
    artifact: OfficeArtifactIdentity
    operation_count: int
    changed_target_count: int
    part_change_count: int
    relationship_change_count: int
    generation_slide_count: int = 0
    generation_object_count: int = 0
    quality: OfficeRevisionQualityResponse
    latest_render: OfficeRenderEvidenceResponse | None
    restored_from_revision_id: str | None = None
    latest_review: OfficeProjectReviewResponse | None = None
    is_final: bool = False


class OfficeProjectTemplateResponse(BaseModel):
    template_id: str
    version: int
    source_sha256: str


class OfficeProjectSummaryResponse(BaseModel):
    project_id: str
    title: str
    format: str
    created_at: str
    updated_at: str
    primary_thread_id: str | None
    revision_count: int
    template: OfficeProjectTemplateResponse | None = None
    final_selection: OfficeFinalSelectionResponse | None = None
    current_revision: OfficeRevisionSummaryResponse


class OfficeProjectsResponse(BaseModel):
    projects: list[OfficeProjectSummaryResponse]


class OfficeProjectDetailResponse(OfficeProjectSummaryResponse):
    render_evidence: list[OfficeRenderEvidenceResponse]
    render_set: OfficeRenderSetResponse
    generation_receipt: OfficeGenerationReceiptResponse | None = None
    generation_preflight: OfficeGenerationPreflightResponse | None = None


class OfficeRevisionsResponse(BaseModel):
    project_id: str
    revisions: list[OfficeRevisionSummaryResponse]


class OfficeRevisionDetailResponse(BaseModel):
    project_id: str
    title: str
    format: str
    is_current: bool
    revision: OfficeRevisionSummaryResponse
    render_evidence: list[OfficeRenderEvidenceResponse]
    render_set: OfficeRenderSetResponse
    operation_receipt: dict[str, Any] | None
    generation_receipt: OfficeGenerationReceiptResponse | None = None
    generation_preflight: OfficeGenerationPreflightResponse | None = None


class OfficePptxSelectionOverlayResponse(BaseModel):
    left_percent: float
    top_percent: float
    width_percent: float
    height_percent: float
    rotation_degrees: float | None = None


class OfficePptxSelectionObjectResponse(BaseModel):
    path: str
    parent_path: str
    kind: str
    name: str | None
    z_order: int | None
    identity_source: str
    selection_status: str
    allowed_operations: list[str]
    geometry: dict[str, Any]
    overlay: OfficePptxSelectionOverlayResponse | None
    text_preview: str
    text_truncated: bool
    object_fingerprint: str


class OfficePptxSelectionSlideResponse(BaseModel):
    index: int
    path: str
    title: str | None
    width_emu: int
    height_emu: int


class OfficePptxSelectionSurfaceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: str = Field(alias="schema")
    format: str
    project_id: str
    revision_id: str
    is_current: bool
    source_sha256: str
    slide: OfficePptxSelectionSlideResponse
    object_count: int
    objects_returned: int
    objects_truncated: bool
    objects: list[OfficePptxSelectionObjectResponse]


class OfficeRenderSetResponse(BaseModel):
    complete: bool
    page_count: int
    rendered_page_count: int
    evidence_ids: list[str]
    evidence: list[OfficeRenderEvidenceResponse]


class OfficeRevisionComparisonResponse(BaseModel):
    project_id: str
    format: str
    base_revision: OfficeRevisionSummaryResponse
    revision: OfficeRevisionSummaryResponse
    operation_receipt: dict[str, Any]
    before_render: OfficeRenderSetResponse
    after_render: OfficeRenderSetResponse


class OfficeProjectReviewRequest(BaseModel):
    status: str
    evidence_ids: list[str] = Field(min_length=1, max_length=1000)
    note: str | None = Field(default=None, max_length=2048)


class OfficeFinalSelectionRequest(BaseModel):
    revision_id: str
    review_id: str
    expected_current_revision_id: str


class OfficeRestoreRequest(BaseModel):
    expected_current_revision_id: str


class OfficeRestoreResponse(BaseModel):
    project_id: str
    revision_id: str
    parent_revision_id: str
    restored_from_revision_id: str
    sequence: int
    artifact: OfficeArtifactIdentity
    project_url: str


def _store_for_user(user_id: str) -> OfficeRevisionStore:
    return OfficeRevisionStore(get_paths().user_office_dir(user_id))


def _workflow_for_user(user_id: str) -> OfficeProjectWorkflowService:
    root = get_paths().user_office_dir(user_id)
    return OfficeProjectWorkflowService(
        OfficeRevisionStore(root),
        template_store=OfficeTemplateStore(root),
    )


async def _run_office_io[T](operation: Callable[[], T]) -> T:
    try:
        return await asyncio.to_thread(operation)
    except OfficeRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OfficeRevisionIntegrityError as exc:
        logger.error("Office project evidence failed integrity checks", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="Office project evidence failed integrity checks.",
        ) from exc
    except OfficeRenderUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Office rendering is currently unavailable.",
        ) from exc
    except (OfficeRenderError, OfficePackageError, OfficeOperationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OfficeTemplateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OfficeRevisionError as exc:
        raise HTTPException(
            status_code=404,
            detail="Office project resource was not found.",
        ) from exc
    except OSError as exc:
        logger.error("Office project storage could not be read", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Office project storage could not be read.",
        ) from exc


def _project_title(project: dict[str, Any], revision: dict[str, Any]) -> str:
    provenance = revision.get("provenance")
    if isinstance(provenance, dict):
        for field_name in ("output_path", "source_path"):
            value = provenance.get(field_name)
            if isinstance(value, str) and value:
                filename = PurePosixPath(value.replace("\\", "/")).name
                if filename:
                    return filename
    return f"{str(project['format']).upper()} {project['project_id'][-6:]}"


def _render_response(
    project_id: str,
    evidence: dict[str, Any],
) -> OfficeRenderEvidenceResponse:
    manifest = evidence["render_manifest"]
    preview_pages = [
        OfficePreviewPageResponse(
            page=preview["page"],
            source_slide=preview.get("source_slide"),
            width=preview["width"],
            height=preview["height"],
            sha256=preview["sha256"],
            url=(f"/api/office/projects/{project_id}/renders/{evidence['evidence_id']}/pages/{preview['page']}"),
        )
        for preview in evidence["preview_pages"]
    ]
    return OfficeRenderEvidenceResponse(
        evidence_id=evidence["evidence_id"],
        revision_id=evidence["revision_id"],
        created_at=evidence["created_at"],
        source_sha256=evidence["source"]["sha256"],
        page_count=manifest["page_count"],
        rendered_page_count=len(preview_pages),
        start_page=manifest["start_page"],
        end_page=manifest["end_page"],
        has_more=manifest["has_more"],
        visual_review_status=manifest["visual_review_status"],
        renderer=manifest["renderer"],
        renderer_version=manifest["renderer_version"],
        pipeline_fingerprint=manifest["pipeline_fingerprint"],
        preview_pages=preview_pages,
    )


def _review_response(review: dict[str, Any]) -> OfficeProjectReviewResponse:
    render_set = review["render_set"]
    return OfficeProjectReviewResponse(
        review_id=review["review_id"],
        revision_id=review["revision_id"],
        created_at=review["created_at"],
        status=review["status"],
        note=review.get("note"),
        evidence_ids=list(render_set["evidence_ids"]),
        page_count=render_set["page_count"],
        render_set_sha256=render_set["sha256"],
    )


def _current_review_response(
    store: OfficeRevisionStore,
    project_id: str,
    revision_id: str,
) -> OfficeProjectReviewResponse | None:
    reviews = store.list_project_reviews(
        project_id,
        revision_id=revision_id,
        limit=1,
    )
    if not reviews:
        return None
    resolved = store.resolve_latest_render_set(project_id, revision_id)
    review = reviews[0]
    if not resolved.complete or tuple(review["render_set"]["evidence_ids"]) != resolved.evidence_ids:
        return None
    return _review_response(review)


def _final_selection_response(selection: dict[str, Any] | None) -> OfficeFinalSelectionResponse | None:
    if selection is None:
        return None
    return OfficeFinalSelectionResponse(
        selection_id=selection["selection_id"],
        revision_id=selection["revision_id"],
        review_id=selection["review_id"],
        created_at=selection["created_at"],
        artifact=OfficeArtifactIdentity(
            sha256=selection["artifact"]["sha256"],
            size_bytes=selection["artifact"]["size_bytes"],
        ),
    )


def _render_set_response(
    project_id: str,
    workflow: OfficeProjectWorkflowService,
    revision_id: str,
) -> OfficeRenderSetResponse:
    render_set = workflow.resolve_latest_render_set(project_id, revision_id)
    evidence = [_render_response(project_id, item) for item in render_set.evidence]
    return OfficeRenderSetResponse(
        complete=render_set.complete,
        page_count=render_set.page_count,
        rendered_page_count=render_set.rendered_page_count,
        evidence_ids=list(render_set.evidence_ids),
        evidence=evidence,
    )


def _generation_evidence_response(
    revision: dict[str, Any],
) -> tuple[
    OfficeGenerationReceiptResponse | None,
    OfficeGenerationPreflightResponse | None,
]:
    if revision.get("kind") != "generation":
        return None, None
    generation = revision.get("generation")
    if not isinstance(generation, dict):
        return None, None
    receipt = OfficeGenerationReceiptResponse.model_validate(generation["receipt"])
    preflight = generation["preflight"]
    summary = preflight["summary"]
    return receipt, OfficeGenerationPreflightResponse(
        schema_version=preflight["schema"],
        source_sha256=preflight["source_sha256"],
        source_size_bytes=preflight["source_size_bytes"],
        slide_count=summary["slide_count"],
        object_count=summary["object_count"],
        picture_count=summary["picture_count"],
        finding_count=summary["finding_count"],
        findings_returned=summary["findings_returned"],
        findings_truncated=summary["findings_truncated"],
        findings_by_severity=dict(summary["findings_by_severity"]),
    )


def _revision_response(
    revision: dict[str, Any],
    latest_render: OfficeRenderEvidenceResponse | None,
    latest_review: OfficeProjectReviewResponse | None = None,
    final_revision_id: str | None = None,
) -> OfficeRevisionSummaryResponse:
    receipt = revision.get("operation_receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    semantic = receipt.get("semantic_changes")
    semantic = semantic if isinstance(semantic, dict) else {}
    package = receipt.get("package_changes")
    package = package if isinstance(package, dict) else {}
    quality = revision["quality_at_commit"]
    validation = quality["package_validation"]
    generation_receipt, _generation_preflight = _generation_evidence_response(revision)
    return OfficeRevisionSummaryResponse(
        revision_id=revision["revision_id"],
        parent_revision_id=revision["parent_revision_id"],
        sequence=revision["sequence"],
        kind=revision["kind"],
        created_at=revision["created_at"],
        artifact=OfficeArtifactIdentity(
            sha256=revision["artifact"]["sha256"],
            size_bytes=revision["artifact"]["size_bytes"],
        ),
        operation_count=receipt.get("operation_count", 0),
        changed_target_count=semantic.get("changed_target_count", 0),
        part_change_count=package.get("part_change_count", 0),
        relationship_change_count=package.get("relationship_change_count", 0),
        generation_slide_count=(generation_receipt.presentation.slide_count if generation_receipt is not None else 0),
        generation_object_count=(generation_receipt.presentation.object_count if generation_receipt is not None else 0),
        quality=OfficeRevisionQualityResponse(
            package_validation_status="valid" if validation.get("valid") is True else "invalid",
            preflight_status=quality["preflight_status"],
            render_evidence_status="available" if latest_render is not None else "not_available",
            visual_review_status=(latest_review.status if latest_review is not None else latest_render.visual_review_status if latest_render is not None else quality["visual_review_status"]),
        ),
        latest_render=latest_render,
        restored_from_revision_id=revision.get("restored_from_revision_id"),
        latest_review=latest_review,
        is_final=revision["revision_id"] == final_revision_id,
    )


def _project_summary(
    store: OfficeRevisionStore,
    project: dict[str, Any],
    revision: dict[str, Any] | None = None,
) -> OfficeProjectSummaryResponse:
    project_id = project["project_id"]
    if revision is None:
        revision = store.load_revision(project_id, project["current_revision_id"])
    evidence = store.list_render_evidence(
        project_id,
        revision_id=revision["revision_id"],
        limit=1,
    )
    latest_render = _render_response(project_id, evidence[0]) if evidence else None
    latest_review = _current_review_response(
        store,
        project_id,
        revision["revision_id"],
    )
    final_selection = store.load_final_selection(project_id)
    resources = revision.get("resource_versions")
    template_resource = resources.get("template") if isinstance(resources, dict) else None
    return OfficeProjectSummaryResponse(
        project_id=project_id,
        title=_project_title(project, revision),
        format=project["format"],
        created_at=project["created_at"],
        updated_at=project["updated_at"],
        primary_thread_id=project.get("primary_thread_id"),
        revision_count=project["revision_count"],
        template=(OfficeProjectTemplateResponse(**template_resource) if isinstance(template_resource, dict) else None),
        final_selection=_final_selection_response(final_selection),
        current_revision=_revision_response(
            revision,
            latest_render,
            latest_review,
            final_selection["revision_id"] if final_selection is not None else None,
        ),
    )


@router.get("/projects", response_model=OfficeProjectsResponse)
async def list_office_projects(
    limit: int = Query(default=100, ge=1, le=_MAX_PROJECTS),
) -> OfficeProjectsResponse:
    """List the current user's newest trusted Office projects."""

    user_id = get_effective_user_id()

    def load() -> OfficeProjectsResponse:
        store = _store_for_user(user_id)
        return OfficeProjectsResponse(projects=[_project_summary(store, project, revision) for project, revision in store.list_project_snapshots(limit=limit)])

    return await _run_office_io(load)


@router.get("/projects/{project_id}", response_model=OfficeProjectDetailResponse)
async def get_office_project(project_id: str) -> OfficeProjectDetailResponse:
    """Get one project and every verified render window for its current revision."""

    user_id = get_effective_user_id()

    def load() -> OfficeProjectDetailResponse:
        store = _store_for_user(user_id)
        workflow = _workflow_for_user(user_id)
        project, revision = store.load_project_snapshot(project_id)
        summary = _project_summary(store, project, revision)
        generation_receipt, generation_preflight = _generation_evidence_response(revision)
        evidence = store.list_render_evidence(
            project_id,
            revision_id=project["current_revision_id"],
            limit=_MAX_RENDER_EVIDENCE,
        )
        return OfficeProjectDetailResponse(
            **summary.model_dump(),
            render_evidence=[_render_response(project_id, item) for item in evidence],
            render_set=_render_set_response(
                project_id,
                workflow,
                project["current_revision_id"],
            ),
            generation_receipt=generation_receipt,
            generation_preflight=generation_preflight,
        )

    return await _run_office_io(load)


@router.get("/projects/{project_id}/revisions", response_model=OfficeRevisionsResponse)
async def list_office_revisions(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=_MAX_REVISIONS),
) -> OfficeRevisionsResponse:
    """List verified revisions from the project's canonical parent chain."""

    user_id = get_effective_user_id()

    def load() -> OfficeRevisionsResponse:
        store = _store_for_user(user_id)
        revisions = store.list_revisions(project_id, limit=limit)
        evidence = store.list_render_evidence(project_id, limit=_MAX_RENDER_EVIDENCE)
        latest_by_revision: dict[str, OfficeRenderEvidenceResponse] = {}
        evidence_by_revision: dict[str, list[dict[str, Any]]] = {}
        for item in evidence:
            revision_id = item["revision_id"]
            latest_by_revision.setdefault(revision_id, _render_response(project_id, item))
            evidence_by_revision.setdefault(revision_id, []).append(item)
        reviews = store.list_project_reviews(project_id, limit=500)
        latest_review_by_revision: dict[str, OfficeProjectReviewResponse] = {}
        for review in reviews:
            latest_review_by_revision.setdefault(
                review["revision_id"],
                _review_response(review),
            )
        final_selection = store.load_final_selection(project_id)
        final_revision_id = final_selection["revision_id"] if final_selection is not None else None

        def summary(revision: dict[str, Any]) -> OfficeRevisionSummaryResponse:
            revision_id = revision["revision_id"]
            resolved = resolve_render_evidence_set(
                revision,
                evidence_by_revision.get(revision_id, []),
            )
            latest_review = latest_review_by_revision.get(revision_id)
            if latest_review is not None and (not resolved.complete or tuple(latest_review.evidence_ids) != resolved.evidence_ids):
                latest_review = None
            return _revision_response(
                revision,
                latest_by_revision.get(revision_id),
                latest_review,
                final_revision_id,
            )

        return OfficeRevisionsResponse(
            project_id=project_id,
            revisions=[summary(revision) for revision in revisions],
        )

    return await _run_office_io(load)


@router.get(
    "/projects/{project_id}/revisions/{revision_id}",
    response_model=OfficeRevisionDetailResponse,
)
async def get_office_revision(
    project_id: str,
    revision_id: str,
) -> OfficeRevisionDetailResponse:
    """Get one canonical save point with its exact render evidence."""

    user_id = get_effective_user_id()

    def load() -> OfficeRevisionDetailResponse:
        store = _store_for_user(user_id)
        workflow = _workflow_for_user(user_id)
        project = store.load_project(project_id)
        revision = store.load_project_revision(project_id, revision_id)
        current_revision = store.load_revision(project_id, project["current_revision_id"])
        evidence = store.list_render_evidence(
            project_id,
            revision_id=revision_id,
            limit=_MAX_RENDER_EVIDENCE,
        )
        render_evidence = [_render_response(project_id, item) for item in evidence]
        latest_review = _current_review_response(
            store,
            project_id,
            revision_id,
        )
        final_selection = store.load_final_selection(project_id)
        generation_receipt, generation_preflight = _generation_evidence_response(revision)
        return OfficeRevisionDetailResponse(
            project_id=project_id,
            title=_project_title(project, current_revision),
            format=project["format"],
            is_current=revision_id == project["current_revision_id"],
            revision=_revision_response(
                revision,
                render_evidence[0] if render_evidence else None,
                latest_review,
                final_selection["revision_id"] if final_selection is not None else None,
            ),
            render_evidence=render_evidence,
            render_set=_render_set_response(project_id, workflow, revision_id),
            operation_receipt=revision.get("operation_receipt"),
            generation_receipt=generation_receipt,
            generation_preflight=generation_preflight,
        )

    return await _run_office_io(load)


@router.get(
    "/projects/{project_id}/revisions/{revision_id}/selection",
    response_model=OfficePptxSelectionSurfaceResponse,
)
async def get_office_pptx_selection_surface(
    project_id: str,
    revision_id: str,
    slide: int = Query(ge=1),
) -> OfficePptxSelectionSurfaceResponse:
    """Return selectable objects derived from one exact canonical PPTX revision."""

    user_id = get_effective_user_id()

    def load() -> OfficePptxSelectionSurfaceResponse:
        store = _store_for_user(user_id)
        project = store.load_project(project_id)
        revision, artifact = store.read_revision_artifact(project_id, revision_id)
        if revision["format"] != "pptx" or project["format"] != "pptx":
            raise OfficeOperationError("Object selection is currently available for PPTX projects only")
        surface = build_pptx_selection_surface(
            artifact,
            slide_index=slide,
        )
        return OfficePptxSelectionSurfaceResponse(
            **surface,
            project_id=project_id,
            revision_id=revision_id,
            is_current=project["current_revision_id"] == revision_id,
        )

    return await _run_office_io(load)


@router.get(
    "/projects/{project_id}/revisions/{revision_id}/comparison",
    response_model=OfficeRevisionComparisonResponse,
)
async def compare_office_revision(
    project_id: str,
    revision_id: str,
) -> OfficeRevisionComparisonResponse:
    """Compare one change revision with its exact canonical parent."""

    user_id = get_effective_user_id()

    def load() -> OfficeRevisionComparisonResponse:
        store = _store_for_user(user_id)
        workflow = _workflow_for_user(user_id)
        project = store.load_project(project_id)
        revision = store.load_project_revision(project_id, revision_id)
        parent_revision_id = revision.get("parent_revision_id")
        receipt = revision.get("operation_receipt")
        if not isinstance(parent_revision_id, str) or not isinstance(receipt, dict):
            raise OfficeRevisionConflictError("Office initial revision has no before/after comparison")
        base_revision = store.load_project_revision(project_id, parent_revision_id)
        final_selection = store.load_final_selection(project_id)
        final_revision_id = final_selection["revision_id"] if final_selection is not None else None

        def summary(candidate: dict[str, Any]) -> OfficeRevisionSummaryResponse:
            candidate_id = candidate["revision_id"]
            evidence = store.list_render_evidence(
                project_id,
                revision_id=candidate_id,
                limit=1,
            )
            latest_review = _current_review_response(
                store,
                project_id,
                candidate_id,
            )
            return _revision_response(
                candidate,
                _render_response(project_id, evidence[0]) if evidence else None,
                latest_review,
                final_revision_id,
            )

        return OfficeRevisionComparisonResponse(
            project_id=project_id,
            format=project["format"],
            base_revision=summary(base_revision),
            revision=summary(revision),
            operation_receipt=receipt,
            before_render=_render_set_response(
                project_id,
                workflow,
                parent_revision_id,
            ),
            after_render=_render_set_response(
                project_id,
                workflow,
                revision_id,
            ),
        )

    return await _run_office_io(load)


@router.post(
    "/projects/{project_id}/revisions/{revision_id}/render",
    response_model=OfficeRenderSetResponse,
)
async def render_office_project_revision(
    project_id: str,
    revision_id: str,
) -> OfficeRenderSetResponse:
    """Render every page of one exact canonical revision into immutable evidence."""

    user_id = get_effective_user_id()

    def render() -> OfficeRenderSetResponse:
        workflow = _workflow_for_user(user_id)
        workflow.render_revision(project_id, revision_id)
        return _render_set_response(project_id, workflow, revision_id)

    return await _run_office_io(render)


@router.post(
    "/projects/{project_id}/revisions/{revision_id}/reviews",
    response_model=OfficeProjectReviewResponse,
)
async def review_office_project_revision(
    project_id: str,
    revision_id: str,
    request: OfficeProjectReviewRequest,
) -> OfficeProjectReviewResponse:
    """Record an immutable decision for an exact complete render set."""

    user_id = get_effective_user_id()

    def review() -> OfficeProjectReviewResponse:
        store = _store_for_user(user_id)
        commit = store.commit_project_review(
            project_id=project_id,
            revision_id=revision_id,
            evidence_ids=request.evidence_ids,
            status=request.status,
            reviewed_by="current_user",
            note=request.note,
        )
        return _review_response(store.load_project_review(project_id, commit.review_id))

    return await _run_office_io(review)


@router.post(
    "/projects/{project_id}/revisions/{revision_id}/restore",
    response_model=OfficeRestoreResponse,
)
async def restore_office_project_revision(
    project_id: str,
    revision_id: str,
    request: OfficeRestoreRequest,
) -> OfficeRestoreResponse:
    """Restore historical bytes by appending a new canonical revision."""

    user_id = get_effective_user_id()

    def restore() -> OfficeRestoreResponse:
        commit = _workflow_for_user(user_id).restore_revision(
            project_id,
            revision_id,
            expected_current_revision_id=request.expected_current_revision_id,
        )
        project = commit.project
        return OfficeRestoreResponse(
            project_id=project.project_id,
            revision_id=project.revision_id,
            parent_revision_id=project.parent_revision_id,
            restored_from_revision_id=commit.restored_from_revision_id,
            sequence=project.sequence,
            artifact=OfficeArtifactIdentity(
                sha256=project.artifact_sha256,
                size_bytes=project.artifact_size_bytes,
            ),
            project_url=f"/workspace/office/projects/{project.project_id}",
        )

    return await _run_office_io(restore)


@router.post(
    "/projects/{project_id}/final",
    response_model=OfficeFinalSelectionResponse,
)
async def select_office_project_final(
    project_id: str,
    request: OfficeFinalSelectionRequest,
) -> OfficeFinalSelectionResponse:
    """Select an approved revision as final without changing the current revision."""

    user_id = get_effective_user_id()

    def select() -> OfficeFinalSelectionResponse:
        store = _store_for_user(user_id)
        store.commit_final_selection(
            project_id=project_id,
            revision_id=request.revision_id,
            review_id=request.review_id,
            expected_current_revision_id=request.expected_current_revision_id,
        )
        selection = store.load_final_selection(project_id)
        response = _final_selection_response(selection)
        if response is None:
            raise OfficeRevisionIntegrityError("Office final selection was not published")
        return response

    return await _run_office_io(select)


@router.get("/projects/{project_id}/final/artifact")
async def get_office_project_final_artifact(project_id: str) -> Response:
    """Download the explicitly selected final Office artifact."""

    user_id = get_effective_user_id()

    def load() -> tuple[dict[str, Any], dict[str, Any], bytes]:
        return _store_for_user(user_id).read_final_artifact(project_id)

    _selection, revision, data = await _run_office_io(load)
    format_name = revision["format"]
    filename = f"final-revision-{revision['sequence']}.{format_name}"
    return Response(
        content=data,
        media_type=_OFFICE_MEDIA_TYPES[format_name],
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/projects/{project_id}/revisions/{revision_id}/artifact")
async def get_office_revision_artifact(
    project_id: str,
    revision_id: str,
) -> Response:
    """Download one immutable Office revision artifact."""

    user_id = get_effective_user_id()

    def load() -> tuple[dict[str, Any], bytes]:
        return _store_for_user(user_id).read_revision_artifact(project_id, revision_id)

    revision, data = await _run_office_io(load)
    format_name = revision["format"]
    filename = f"revision-{revision['sequence']}.{format_name}"
    return Response(
        content=data,
        media_type=_OFFICE_MEDIA_TYPES[format_name],
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/projects/{project_id}/renders/{evidence_id}/pages/{page}")
async def get_office_render_preview_page(
    project_id: str,
    evidence_id: str,
    page: int,
    request: Request,
) -> Response:
    """Serve one immutable render-evidence PNG after its SHA-256 check."""

    user_id = get_effective_user_id()

    def load() -> tuple[dict[str, Any], dict[str, Any], bytes]:
        return _store_for_user(user_id).read_render_preview_page(project_id, evidence_id, page)

    _evidence, preview, data = await _run_office_io(load)
    etag = f'"{preview["sha256"]}"'
    headers = {
        "Cache-Control": "private, max-age=31536000, immutable",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/png", headers=headers)
