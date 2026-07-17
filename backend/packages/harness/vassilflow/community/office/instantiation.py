"""Trusted instantiation of published fixed-structure Office templates."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from .engine import office_engine
from .errors import (
    OfficeRevisionError,
    OfficeTemplateConflictError,
    OfficeTemplateError,
)
from .models import (
    OfficeEditOperation,
    PptxPictureSelector,
    PptxPictureSourceReplacementOperation,
    PptxPictureTarget,
    PptxTextReplacement,
)
from .render import OfficeRenderResult
from .revisions import (
    RENDER_MANIFEST_SCHEMA,
    OfficeRenderEvidenceCommit,
    OfficeRevisionCommit,
    OfficeRevisionStore,
)
from .templates import OfficeTemplateStore

logger = logging.getLogger(__name__)

_SLOT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
_MAX_RENDER_BATCH_PAGES = 12
_RENDER_DPI = 120


@dataclass(frozen=True, slots=True)
class OfficeTemplateTextBinding:
    """One text value bound by published slot key."""

    key: str
    value: str
    type: Literal["text"] = "text"


@dataclass(frozen=True, slots=True)
class OfficeTemplatePictureBinding:
    """One bounded embedded image bound by published slot key."""

    key: str
    data: bytes
    filename: str
    content_type: Literal["image/png", "image/jpeg"]
    type: Literal["picture"] = "picture"


OfficeTemplateBinding = OfficeTemplateTextBinding | OfficeTemplatePictureBinding


@dataclass(frozen=True, slots=True)
class OfficeTemplateInstantiationCommit:
    """Durable project identity and evidence produced by one instantiation."""

    template_id: str
    template_version: int
    project_title: str
    project: OfficeRevisionCommit
    reports: tuple[dict, ...]
    receipt: dict
    validation: dict
    preflight: dict
    bound_slot_keys: tuple[str, ...]
    omitted_optional_slot_keys: tuple[str, ...]
    render_evidence: tuple[OfficeRenderEvidenceCommit, ...]
    render_evidence_status: Literal["available", "partial", "not_available"]


def _project_filename(title: str | None, *, fallback: str) -> tuple[str, str]:
    raw = title if title is not None else fallback
    if not isinstance(raw, str):
        raise OfficeTemplateError("Office template project title must be text")
    normalized = raw.strip()
    if normalized.lower().endswith(".pptx"):
        normalized = normalized[:-5].rstrip()
    normalized = normalized.replace("/", "-").replace("\\", "-")
    if not normalized or len(normalized) > 200 or any(ord(character) < 32 for character in normalized):
        raise OfficeTemplateError("Office template project title is invalid")
    return normalized, f"{normalized}.pptx"


class OfficeTemplateInstantiationService:
    """Compile typed bindings, enforce locks, and commit one Office project."""

    def __init__(
        self,
        template_store: OfficeTemplateStore,
        revision_store: OfficeRevisionStore,
        *,
        renderer: Callable[..., OfficeRenderResult] | None = None,
    ) -> None:
        self.template_store = template_store
        self.revision_store = revision_store
        self._renderer = renderer or office_engine.render

    @staticmethod
    def _compile_bindings(
        version_payload: dict,
        bindings: Sequence[OfficeTemplateBinding],
    ) -> tuple[
        list[OfficeEditOperation],
        dict[str, bytes],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        slots = version_payload["slots"]
        slots_by_key = {slot["key"]: slot for slot in slots}
        bindings_by_key: dict[str, OfficeTemplateBinding] = {}
        for binding in bindings:
            if not isinstance(binding, (OfficeTemplateTextBinding, OfficeTemplatePictureBinding)):
                raise OfficeTemplateError("Office template binding has an invalid type")
            if _SLOT_KEY_RE.fullmatch(binding.key) is None:
                raise OfficeTemplateError("Office template binding key is invalid")
            if binding.key in bindings_by_key:
                raise OfficeTemplateError("Office template binding keys must be unique")
            if binding.key not in slots_by_key:
                raise OfficeTemplateConflictError("Office template binding references an unknown or stale slot")
            bindings_by_key[binding.key] = binding

        missing_required = sorted(slot["key"] for slot in slots if slot["required"] and slot["key"] not in bindings_by_key)
        if missing_required:
            raise OfficeTemplateConflictError("Office template required bindings are missing: " + ", ".join(missing_required))

        operations: list[OfficeEditOperation] = []
        image_assets: dict[str, bytes] = {}
        total_image_bytes = 0
        for position, slot in enumerate(slots, start=1):
            binding = bindings_by_key.get(slot["key"])
            if binding is None:
                continue
            if binding.type != slot["type"]:
                raise OfficeTemplateConflictError(f"Office template binding type does not match slot {slot['key']}")
            selector = slot["selector"]
            if isinstance(binding, OfficeTemplateTextBinding):
                max_length = slot["constraints"]["max_length"]
                if not isinstance(binding.value, str) or len(binding.value) > max_length or (slot["required"] and not binding.value) or any(character in binding.value for character in ("\r", "\n", "\t")):
                    raise OfficeTemplateError(f"Office template text binding {slot['key']} violates its constraints")
                operations.append(
                    PptxTextReplacement(
                        paths=[selector["path"]],
                        find=selector["expected_text"],
                        replace=binding.value,
                    )
                )
                continue

            if not isinstance(binding.data, bytes) or not binding.data or len(binding.data) > _MAX_IMAGE_BYTES:
                raise OfficeTemplateError(f"Office template picture binding {slot['key']} exceeds its size limit")
            total_image_bytes += len(binding.data)
            if total_image_bytes > _MAX_TOTAL_IMAGE_BYTES:
                raise OfficeTemplateError("Office template picture bindings exceed the total size limit")
            extension = "png" if binding.content_type == "image/png" else "jpg"
            image_path = f"/mnt/user-data/uploads/.template-bindings/{position:03d}-{slot['key']}.{extension}"
            image_assets[image_path] = binding.data
            operations.append(
                PptxPictureSourceReplacementOperation(
                    pictures=PptxPictureSelector(targets=[PptxPictureTarget(**selector)]),
                    image_path=image_path,
                )
            )

        omitted_optional = tuple(sorted(slot["key"] for slot in slots if not slot["required"] and slot["key"] not in bindings_by_key))
        return (
            operations,
            image_assets,
            tuple(sorted(bindings_by_key)),
            omitted_optional,
        )

    def _render_full_deck(
        self,
        document: bytes,
        *,
        page_count: int,
    ) -> tuple[OfficeRenderResult, ...]:
        windows: list[OfficeRenderResult] = []
        source_sha256 = hashlib.sha256(document).hexdigest()
        identity: tuple[str, str, str, str] | None = None
        start_page = 1
        while start_page <= page_count:
            max_pages = min(_MAX_RENDER_BATCH_PAGES, page_count - start_page + 1)
            rendered = self._renderer(
                document,
                suffix=".pptx",
                start_page=start_page,
                max_pages=max_pages,
                dpi=_RENDER_DPI,
            )
            current_identity = (
                rendered.renderer,
                rendered.renderer_version,
                rendered.pdfium_version,
                rendered.pipeline_fingerprint,
            )
            expected_pages = list(range(start_page, start_page + min(max_pages, page_count - start_page + 1)))
            if (
                rendered.format != "pptx"
                or rendered.source_sha256 != source_sha256
                or rendered.page_count != page_count
                or rendered.start_page != start_page
                or rendered.dpi != _RENDER_DPI
                or [page.page for page in rendered.pages] != expected_pages
                or any(page.source_slide != page.page for page in rendered.pages)
                or (identity is not None and current_identity != identity)
            ):
                raise OfficeTemplateConflictError("Office template project renderer returned inconsistent full-deck evidence")
            identity = current_identity
            windows.append(rendered)
            start_page = rendered.pages[-1].page + 1
        if not windows:
            raise OfficeTemplateConflictError("Office template project renderer returned no evidence")
        return tuple(windows)

    def _commit_render_windows(
        self,
        *,
        commit: OfficeRevisionCommit,
        document: bytes,
        filename: str,
        windows: Sequence[OfficeRenderResult],
        thread_id: str | None,
    ) -> tuple[tuple[OfficeRenderEvidenceCommit, ...], str]:
        evidence: list[OfficeRenderEvidenceCommit] = []
        try:
            for rendered in windows:
                output_dir = f"/mnt/user-data/outputs/.office-project-renders/{commit.revision_id}/window-{rendered.start_page:05d}"
                pages = [
                    {
                        "page": page.page,
                        "source_slide": page.source_slide,
                        "path": f"{output_dir}/{page.filename}",
                        "width": page.width,
                        "height": page.height,
                        "sha256": page.sha256,
                    }
                    for page in rendered.pages
                ]
                manifest = {
                    "schema": RENDER_MANIFEST_SCHEMA,
                    "complete": True,
                    "project_id": commit.project_id,
                    "revision_id": commit.revision_id,
                    "format": "pptx",
                    "source_path": f"/mnt/user-data/outputs/{filename}",
                    "source_sha256": rendered.source_sha256,
                    "source_size_bytes": len(document),
                    "output_dir": output_dir,
                    "manifest_path": f"{output_dir}/render-manifest.json",
                    "renderer": rendered.renderer,
                    "renderer_version": rendered.renderer_version,
                    "pdfium_version": rendered.pdfium_version,
                    "pipeline_fingerprint": rendered.pipeline_fingerprint,
                    "page_count": rendered.page_count,
                    "start_page": rendered.start_page,
                    "end_page": rendered.pages[-1].page,
                    "requested_max_pages": len(rendered.pages),
                    "dpi": rendered.dpi,
                    "has_more": rendered.has_more,
                    "pages": pages,
                    "visual_review_status": "pending",
                    "gateway_page_access": "available",
                }
                evidence.append(
                    self.revision_store.commit_render_evidence(
                        project_id=commit.project_id,
                        revision_id=commit.revision_id,
                        source=document,
                        suffix=".pptx",
                        manifest=manifest,
                        pages=rendered.pages,
                        thread_id=thread_id,
                    )
                )
        except (OfficeRevisionError, OSError):
            logger.exception("Office template project committed but render evidence storage was incomplete")
            status = "partial" if evidence else "not_available"
            return tuple(evidence), status
        return tuple(evidence), "available"

    def instantiate(
        self,
        template_id: str,
        version: int,
        *,
        bindings: Sequence[OfficeTemplateBinding],
        title: str | None = None,
        thread_id: str | None = None,
        render: bool = True,
    ) -> OfficeTemplateInstantiationCommit:
        """Create a project from exact published bytes and typed slot values."""

        template = self.template_store.load_template(template_id)
        version_payload, source = self.template_store.read_source(
            template_id,
            version,
        )
        if version_payload["status"] != "published":
            raise OfficeTemplateConflictError("Office template instantiation requires a published version")
        operations, image_assets, bound_keys, omitted_optional = self._compile_bindings(version_payload, bindings)
        source_validation = office_engine.validate(source, suffix=".pptx")
        result, reports, receipt = office_engine.edit_with_receipt(
            source,
            suffix=".pptx",
            operations=operations,
            image_assets=image_assets,
        )
        if len(reports) != len(operations) or any(report.get("match_count", 0) < 1 for report in reports):
            raise OfficeTemplateConflictError("Office template binding did not resolve every selected slot")
        validation = office_engine.validate(result, suffix=".pptx")
        preflight = office_engine.preflight(result, suffix=".pptx")
        policy = self.template_store.enforce_published_edit_policy(
            template_id,
            version,
            source=source,
            result=result,
            operations=operations,
            receipt=receipt,
        )
        project_title, filename = _project_filename(
            title,
            fallback=template["title"],
        )
        windows = (
            self._render_full_deck(
                result,
                page_count=version_payload["locked_policy"]["fixed_slide_count"],
            )
            if render
            else ()
        )
        template_resource = {
            "template_id": template_id,
            "version": version,
            "source_sha256": version_payload["source"]["sha256"],
        }
        commit = self.revision_store.commit_edit(
            source=source,
            result=result,
            suffix=".pptx",
            source_path=(f"/mnt/user-data/templates/{template_id}/versions/{version}/{version_payload['filename']}"),
            output_path=f"/mnt/user-data/outputs/{filename}",
            thread_id=thread_id,
            receipt=receipt,
            source_validation=source_validation,
            result_validation=validation,
            template_resource=template_resource,
            template_policy=policy,
        )
        render_evidence, render_status = (
            self._commit_render_windows(
                commit=commit,
                document=result,
                filename=filename,
                windows=windows,
                thread_id=thread_id,
            )
            if windows
            else ((), "not_available")
        )
        return OfficeTemplateInstantiationCommit(
            template_id=template_id,
            template_version=version,
            project_title=project_title,
            project=commit,
            reports=tuple(reports),
            receipt=receipt,
            validation=validation,
            preflight=preflight,
            bound_slot_keys=bound_keys,
            omitted_optional_slot_keys=omitted_optional,
            render_evidence=render_evidence,
            render_evidence_status=render_status,
        )
