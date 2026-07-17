"""Management API for trusted, user-scoped PPTX templates."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any, Literal, cast
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError, model_validator

from vassilflow.community.office.errors import (
    OfficeOperationError,
    OfficePackageError,
    OfficeRenderError,
    OfficeRenderUnavailableError,
    OfficeRevisionError,
    OfficeRevisionIntegrityError,
    OfficeTemplateConflictError,
    OfficeTemplateError,
    OfficeTemplateIntegrityError,
)
from vassilflow.community.office.instantiation import (
    OfficeTemplateInstantiationService,
    OfficeTemplatePictureBinding,
    OfficeTemplateTextBinding,
)
from vassilflow.community.office.revisions import OfficeRevisionStore
from vassilflow.community.office.templates import (
    OfficeTemplateSlotDraft,
    OfficeTemplateStore,
)
from vassilflow.config.paths import get_paths
from vassilflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/office/templates", tags=["office-templates"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 64 * 1024
_MAX_TEMPLATES = 500
_PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_MAX_BINDINGS_JSON_BYTES = 64 * 1024
_MAX_BINDING_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_BINDING_IMAGES_BYTES = 50 * 1024 * 1024


class OfficeTemplateSourceResponse(BaseModel):
    sha256: str
    size_bytes: int


class OfficeTemplatePreviewPageResponse(BaseModel):
    page: int
    source_slide: int
    width: int
    height: int
    sha256: str
    url: str


class OfficeTemplateRenderResponse(BaseModel):
    status: str
    evidence_id: str | None = None
    created_at: str | None = None
    source_sha256: str | None = None
    page_count: int = 0
    rendered_page_count: int = 0
    pipeline_fingerprint: str | None = None
    renderer: str | None = None
    renderer_version: str | None = None
    visual_review_status: str
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    preview_pages: list[OfficeTemplatePreviewPageResponse] = Field(default_factory=list)


class OfficeTemplateVersionSummaryResponse(BaseModel):
    template_id: str
    version: int
    status: str
    format: Literal["pptx"]
    filename: str
    created_at: str
    updated_at: str
    published_at: str | None
    source: OfficeTemplateSourceResponse
    validation_status: str
    slide_count: int
    object_count: int
    preflight_finding_count: int
    preflight_findings_by_severity: dict[str, int]
    slot_candidate_count: int
    slot_count: int
    render: OfficeTemplateRenderResponse


class OfficeTemplateCandidateResponse(BaseModel):
    candidate_id: str
    source_fingerprint: str
    type: Literal["text", "picture"]
    path: str
    slide_index: int
    default_label: str
    selector: dict[str, Any]
    source: dict[str, Any]


class OfficeTemplateSlotResponse(BaseModel):
    key: str
    label: str
    type: Literal["text", "picture"]
    required: bool
    candidate_id: str
    source_fingerprint: str
    selector: dict[str, Any]
    constraints: dict[str, Any]
    allowed_operations: list[str]


class OfficeTemplateVersionDetailResponse(OfficeTemplateVersionSummaryResponse):
    validation: dict[str, Any]
    locked_policy: dict[str, Any]
    slot_candidates: list[OfficeTemplateCandidateResponse]
    slots: list[OfficeTemplateSlotResponse]


class OfficeTemplateSummaryResponse(BaseModel):
    template_id: str
    title: str
    format: Literal["pptx"]
    owner_scope: Literal["user"]
    created_at: str
    updated_at: str
    latest_version: int
    draft_version: int | None
    published_versions: list[int]
    archived: bool
    status: Literal["draft", "published"]
    active_version: OfficeTemplateVersionSummaryResponse


class OfficeTemplatesResponse(BaseModel):
    templates: list[OfficeTemplateSummaryResponse]


class OfficeTemplateDetailResponse(OfficeTemplateSummaryResponse):
    versions: list[OfficeTemplateVersionSummaryResponse]


class OfficeTemplateSlotDraftRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    type: Literal["text", "picture"]
    candidate_id: str = Field(pattern=r"^otc_[0-9a-f]{32}$")
    required: bool = True
    max_length: int | None = Field(default=None, ge=1, le=4_000)


class OfficeTemplateSlotsRequest(BaseModel):
    slots: list[OfficeTemplateSlotDraftRequest] = Field(max_length=100)


class OfficeTemplateReviewRequest(BaseModel):
    status: Literal["reviewed", "external_review_required"]
    note: str | None = Field(default=None, min_length=1, max_length=1_000)


class OfficeTemplateBindingRequest(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: Literal["text", "picture"]
    value: str | None = Field(default=None, max_length=4_000)
    upload_index: int | None = Field(default=None, ge=0, le=99)

    @model_validator(mode="after")
    def require_typed_value(self) -> OfficeTemplateBindingRequest:
        if self.type == "text" and (self.value is None or self.upload_index is not None):
            raise ValueError("Text bindings require only value")
        if self.type == "picture" and (self.upload_index is None or self.value is not None):
            raise ValueError("Picture bindings require only upload_index")
        return self


class OfficeTemplateBindingsRequest(BaseModel):
    bindings: list[OfficeTemplateBindingRequest] = Field(max_length=100)


class OfficeTemplateInstantiationResponse(BaseModel):
    template_id: str
    template_version: int
    project_id: str
    revision_id: str
    baseline_revision_id: str
    project_title: str
    artifact: OfficeTemplateSourceResponse
    bound_slot_keys: list[str]
    omitted_optional_slot_keys: list[str]
    operation_count: int
    changed_target_count: int
    preflight_finding_count: int
    render_evidence_status: Literal["available", "partial", "not_available"]
    render_evidence_ids: list[str]
    project_url: str


def _store_for_user(user_id: str) -> OfficeTemplateStore:
    return OfficeTemplateStore(get_paths().user_office_dir(user_id))


async def _run_template_io[T](operation: Callable[[], T]) -> T:
    try:
        return await asyncio.to_thread(operation)
    except OfficeRevisionIntegrityError as exc:
        logger.error("Office template project evidence failed integrity checks", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="Office template project evidence failed integrity checks.",
        ) from exc
    except OfficeTemplateIntegrityError as exc:
        logger.error("Office template evidence failed integrity checks", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="Office template evidence failed integrity checks.",
        ) from exc
    except OfficeTemplateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OfficeTemplateError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except OfficeRevisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OfficeRenderUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Office template rendering is currently unavailable.",
        ) from exc
    except OfficeRenderError as exc:
        logger.error("Office template rendering failed", exc_info=True)
        raise HTTPException(status_code=502, detail="Office template rendering failed.") from exc
    except (OfficeOperationError, OfficePackageError) as exc:
        raise HTTPException(
            status_code=422,
            detail="The PPTX was rejected by the Office safety or compatibility policy.",
        ) from exc
    except OSError as exc:
        logger.error("Office template storage operation failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Office template storage operation failed.") from exc


async def _read_template_upload(file: UploadFile) -> tuple[str, bytes]:
    filename = file.filename or ""
    data = bytearray()
    try:
        while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
            data.extend(chunk)
            if len(data) > _MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Office template upload exceeds the 50 MB limit.",
                )
    finally:
        await file.close()
    return filename, bytes(data)


def _parse_bindings_json(value: str) -> OfficeTemplateBindingsRequest:
    if not isinstance(value, str) or len(value.encode("utf-8")) > _MAX_BINDINGS_JSON_BYTES:
        raise HTTPException(
            status_code=422,
            detail="Office template bindings exceed the supported metadata limit.",
        )
    try:
        payload = json.loads(value)
        return OfficeTemplateBindingsRequest.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Office template bindings are invalid.",
        ) from exc


async def _read_binding_images(
    files: list[UploadFile],
) -> list[tuple[str, str, bytes]]:
    images: list[tuple[str, str, bytes]] = []
    total_bytes = 0
    for file in files:
        content_type = file.content_type or ""
        if content_type not in {"image/png", "image/jpeg"}:
            await file.close()
            raise HTTPException(
                status_code=422,
                detail="Office template picture bindings accept PNG or JPEG only.",
            )
        data = bytearray()
        try:
            while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
                data.extend(chunk)
                total_bytes += len(chunk)
                if len(data) > _MAX_BINDING_IMAGE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="An Office template picture exceeds the 12 MB limit.",
                    )
                if total_bytes > _MAX_BINDING_IMAGES_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Office template pictures exceed the 50 MB total limit.",
                    )
        finally:
            await file.close()
        images.append((file.filename or f"image-{len(images) + 1}", content_type, bytes(data)))
    return images


def _render_response(
    template_id: str,
    version: int,
    render: dict[str, Any],
    evidence: dict[str, Any] | None,
) -> OfficeTemplateRenderResponse:
    if render["status"] != "available" or evidence is None:
        return OfficeTemplateRenderResponse(
            status="not_recorded",
            visual_review_status="not_performed",
        )
    preview_pages = [
        OfficeTemplatePreviewPageResponse(
            page=page["page"],
            source_slide=page["source_slide"],
            width=page["width"],
            height=page["height"],
            sha256=page["sha256"],
            url=(f"/api/office/templates/{template_id}/versions/{version}/renders/{evidence['evidence_id']}/pages/{page['page']}"),
        )
        for page in evidence["pages"]
    ]
    return OfficeTemplateRenderResponse(
        status="available",
        evidence_id=evidence["evidence_id"],
        created_at=evidence["created_at"],
        source_sha256=evidence["source"]["sha256"],
        page_count=evidence["page_count"],
        rendered_page_count=evidence["rendered_page_count"],
        pipeline_fingerprint=evidence["pipeline_fingerprint"],
        renderer=evidence["renderer"],
        renderer_version=evidence["renderer_version"],
        visual_review_status=render["visual_review_status"],
        reviewed_at=render.get("reviewed_at"),
        reviewed_by=render.get("reviewed_by"),
        review_note=render.get("review_note"),
        preview_pages=preview_pages,
    )


def _version_summary(
    version: dict[str, Any],
    evidence: dict[str, Any] | None,
) -> OfficeTemplateVersionSummaryResponse:
    validation = version["validation"]
    inspection = version["inspection"]
    preflight = version["preflight"]
    return OfficeTemplateVersionSummaryResponse(
        template_id=version["template_id"],
        version=version["version"],
        status=version["status"],
        format="pptx",
        filename=version["filename"],
        created_at=version["created_at"],
        updated_at=version["updated_at"],
        published_at=version["published_at"],
        source=OfficeTemplateSourceResponse(**version["source"]),
        validation_status="valid" if validation.get("valid") is True else "invalid",
        slide_count=inspection["slide_count"],
        object_count=inspection["object_count"],
        preflight_finding_count=preflight["finding_count"],
        preflight_findings_by_severity=preflight["findings_by_severity"],
        slot_candidate_count=len(version["slot_candidates"]),
        slot_count=len(version["slots"]),
        render=_render_response(
            version["template_id"],
            version["version"],
            version["render"],
            evidence,
        ),
    )


def _version_detail(
    version: dict[str, Any],
    evidence: dict[str, Any] | None,
) -> OfficeTemplateVersionDetailResponse:
    summary = _version_summary(version, evidence)
    return OfficeTemplateVersionDetailResponse(
        **summary.model_dump(),
        validation=version["validation"],
        locked_policy=version["locked_policy"],
        slot_candidates=[OfficeTemplateCandidateResponse(**candidate) for candidate in version["slot_candidates"]],
        slots=[OfficeTemplateSlotResponse(**slot) for slot in version["slots"]],
    )


def _template_summary(
    store: OfficeTemplateStore,
    template: dict[str, Any],
) -> OfficeTemplateSummaryResponse:
    active_version_number = template["draft_version"] if template["draft_version"] is not None else max(template["published_versions"])
    version, evidence = store.load_version_detail(
        template["template_id"],
        active_version_number,
    )
    return OfficeTemplateSummaryResponse(
        template_id=template["template_id"],
        title=template["title"],
        format="pptx",
        owner_scope="user",
        created_at=template["created_at"],
        updated_at=template["updated_at"],
        latest_version=template["latest_version"],
        draft_version=template["draft_version"],
        published_versions=template["published_versions"],
        archived=template["archived"],
        status="draft" if template["draft_version"] is not None else "published",
        active_version=_version_summary(version, evidence),
    )


def _template_detail(
    store: OfficeTemplateStore,
    template: dict[str, Any],
) -> OfficeTemplateDetailResponse:
    summary = _template_summary(store, template)
    version_numbers = set(template["published_versions"])
    if template["draft_version"] is not None:
        version_numbers.add(template["draft_version"])
    versions = []
    for version_number in sorted(version_numbers, reverse=True):
        version, evidence = store.load_version_detail(
            template["template_id"],
            version_number,
        )
        versions.append(_version_summary(version, evidence))
    return OfficeTemplateDetailResponse(
        **summary.model_dump(),
        versions=versions,
    )


@router.get("", response_model=OfficeTemplatesResponse)
async def list_office_templates(
    limit: int = Query(default=100, ge=1, le=_MAX_TEMPLATES),
) -> OfficeTemplatesResponse:
    """List the current user's trusted personal Office templates."""

    user_id = get_effective_user_id()

    def load() -> OfficeTemplatesResponse:
        store = _store_for_user(user_id)
        return OfficeTemplatesResponse(templates=[_template_summary(store, template) for template in store.list_templates(limit=limit)])

    return await _run_template_io(load)


@router.post("", response_model=OfficeTemplateDetailResponse, status_code=201)
async def import_office_template(
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=200),
) -> OfficeTemplateDetailResponse:
    """Import one bounded PPTX as a personal version-one draft."""

    filename, source = await _read_template_upload(file)
    user_id = get_effective_user_id()

    def create() -> OfficeTemplateDetailResponse:
        store = _store_for_user(user_id)
        commit = store.import_pptx(source, filename=filename, title=title)
        return _template_detail(store, store.load_template(commit.template_id))

    return await _run_template_io(create)


@router.get("/{template_id}", response_model=OfficeTemplateDetailResponse)
async def get_office_template(template_id: str) -> OfficeTemplateDetailResponse:
    """Get one personal template and its canonical version index."""

    user_id = get_effective_user_id()

    def load() -> OfficeTemplateDetailResponse:
        store = _store_for_user(user_id)
        return _template_detail(store, store.load_template(template_id))

    return await _run_template_io(load)


@router.get(
    "/{template_id}/versions/{version}",
    response_model=OfficeTemplateVersionDetailResponse,
)
async def get_office_template_version(
    template_id: str,
    version: int,
) -> OfficeTemplateVersionDetailResponse:
    """Get source-bound candidates, slots, QA, and preview metadata."""

    user_id = get_effective_user_id()

    def load() -> OfficeTemplateVersionDetailResponse:
        payload, evidence = _store_for_user(user_id).load_version_detail(
            template_id,
            version,
        )
        return _version_detail(payload, evidence)

    return await _run_template_io(load)


@router.put(
    "/{template_id}/versions/{version}/slots",
    response_model=OfficeTemplateVersionDetailResponse,
)
async def update_office_template_slots(
    template_id: str,
    version: int,
    request: OfficeTemplateSlotsRequest,
) -> OfficeTemplateVersionDetailResponse:
    """Replace a draft slot map using server-issued candidate IDs only."""

    user_id = get_effective_user_id()
    mappings = [OfficeTemplateSlotDraft(**slot.model_dump()) for slot in request.slots]

    def update() -> OfficeTemplateVersionDetailResponse:
        store = _store_for_user(user_id)
        store.update_draft_slots(template_id, version, mappings)
        payload, evidence = store.load_version_detail(template_id, version)
        return _version_detail(payload, evidence)

    return await _run_template_io(update)


@router.post(
    "/{template_id}/versions/{version}/render",
    response_model=OfficeTemplateVersionDetailResponse,
)
async def render_office_template(
    template_id: str,
    version: int,
) -> OfficeTemplateVersionDetailResponse:
    """Render every slide and select one immutable draft evidence run."""

    user_id = get_effective_user_id()

    def render() -> OfficeTemplateVersionDetailResponse:
        store = _store_for_user(user_id)
        store.render_draft(template_id, version)
        payload, evidence = store.load_version_detail(template_id, version)
        return _version_detail(payload, evidence)

    return await _run_template_io(render)


@router.post(
    "/{template_id}/versions/{version}/renders/{evidence_id}/review",
    response_model=OfficeTemplateVersionDetailResponse,
)
async def review_office_template_render(
    template_id: str,
    version: int,
    evidence_id: str,
    request: OfficeTemplateReviewRequest,
) -> OfficeTemplateVersionDetailResponse:
    """Record the current owner user's explicit visual review decision."""

    user_id = get_effective_user_id()

    def review() -> OfficeTemplateVersionDetailResponse:
        store = _store_for_user(user_id)
        store.review_draft_render(
            template_id,
            version,
            evidence_id,
            status=request.status,
            reviewer=user_id,
            note=request.note,
        )
        payload, evidence = store.load_version_detail(template_id, version)
        return _version_detail(payload, evidence)

    return await _run_template_io(review)


@router.post(
    "/{template_id}/versions/{version}/publish",
    response_model=OfficeTemplateVersionDetailResponse,
)
async def publish_office_template(
    template_id: str,
    version: int,
) -> OfficeTemplateVersionDetailResponse:
    """Publish one immutable personal template version after all gates pass."""

    user_id = get_effective_user_id()

    def publish() -> OfficeTemplateVersionDetailResponse:
        store = _store_for_user(user_id)
        store.publish_draft(template_id, version)
        payload, evidence = store.load_version_detail(template_id, version)
        return _version_detail(payload, evidence)

    return await _run_template_io(publish)


@router.post(
    "/{template_id}/versions/{version}/instantiate",
    response_model=OfficeTemplateInstantiationResponse,
    status_code=201,
)
async def instantiate_office_template(
    template_id: str,
    version: int,
    bindings_json: str = Form(...),
    title: str | None = Form(default=None, max_length=200),
    files: list[UploadFile] | None = File(default=None),
) -> OfficeTemplateInstantiationResponse:
    """Create one project from exact published bytes and typed slot bindings."""

    request = _parse_bindings_json(bindings_json)
    images = await _read_binding_images(files or [])
    used_uploads: set[int] = set()
    bindings = []
    for binding in request.bindings:
        if binding.type == "text":
            bindings.append(
                OfficeTemplateTextBinding(
                    key=binding.key,
                    value=binding.value or "",
                )
            )
            continue
        upload_index = binding.upload_index
        if upload_index is None or upload_index >= len(images) or upload_index in used_uploads:
            raise HTTPException(
                status_code=422,
                detail="Office template picture upload references are invalid.",
            )
        filename, content_type, data = images[upload_index]
        bindings.append(
            OfficeTemplatePictureBinding(
                key=binding.key,
                data=data,
                filename=filename,
                content_type=cast(Literal["image/png", "image/jpeg"], content_type),
            )
        )
        used_uploads.add(upload_index)
    if used_uploads != set(range(len(images))):
        raise HTTPException(
            status_code=422,
            detail="Office template picture uploads must each be referenced exactly once.",
        )

    user_id = get_effective_user_id()

    def instantiate() -> OfficeTemplateInstantiationResponse:
        template_store = _store_for_user(user_id)
        commit = OfficeTemplateInstantiationService(
            template_store,
            OfficeRevisionStore(template_store.root),
        ).instantiate(
            template_id,
            version,
            bindings=bindings,
            title=title,
        )
        semantic = commit.receipt["semantic_changes"]
        preflight_summary = commit.preflight["summary"]
        if commit.project.baseline_revision_id is None:
            raise OfficeRevisionIntegrityError("Office template project baseline identity is missing")
        return OfficeTemplateInstantiationResponse(
            template_id=template_id,
            template_version=version,
            project_id=commit.project.project_id,
            revision_id=commit.project.revision_id,
            baseline_revision_id=commit.project.baseline_revision_id,
            project_title=commit.project_title,
            artifact=OfficeTemplateSourceResponse(
                sha256=commit.project.artifact_sha256,
                size_bytes=commit.project.artifact_size_bytes,
            ),
            bound_slot_keys=list(commit.bound_slot_keys),
            omitted_optional_slot_keys=list(commit.omitted_optional_slot_keys),
            operation_count=commit.receipt["operation_count"],
            changed_target_count=semantic["changed_target_count"],
            preflight_finding_count=preflight_summary["finding_count"],
            render_evidence_status=commit.render_evidence_status,
            render_evidence_ids=[evidence.evidence_id for evidence in commit.render_evidence],
            project_url=f"/workspace/office/projects/{commit.project.project_id}",
        )

    return await _run_template_io(instantiate)


@router.get("/{template_id}/versions/{version}/source")
async def download_office_template_source(
    template_id: str,
    version: int,
) -> Response:
    """Download exact source bytes for one permission-checked template version."""

    user_id = get_effective_user_id()

    def load() -> tuple[dict[str, Any], bytes]:
        return _store_for_user(user_id).read_source(template_id, version)

    payload, data = await _run_template_io(load)
    return Response(
        content=data,
        media_type=_PPTX_MEDIA_TYPE,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(payload['filename'])}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{template_id}/versions/{version}/renders/{evidence_id}/pages/{page}")
async def get_office_template_preview_page(
    template_id: str,
    version: int,
    evidence_id: str,
    page: int,
    request: Request,
) -> Response:
    """Serve one immutable template preview PNG after its SHA-256 check."""

    user_id = get_effective_user_id()

    def load() -> tuple[dict[str, Any], dict[str, Any], bytes]:
        return _store_for_user(user_id).read_render_preview_page(
            template_id,
            version,
            evidence_id,
            page,
        )

    _evidence, preview, data = await _run_template_io(load)
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
