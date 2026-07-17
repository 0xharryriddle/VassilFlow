"""Evidence-backed render, review, and restore workflows for Office projects."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .engine import office_engine
from .errors import OfficeRevisionConflictError, OfficeRevisionError
from .receipt import build_restore_change_receipt
from .render import OfficeRenderResult
from .revisions import (
    RENDER_MANIFEST_SCHEMA,
    OfficeRenderEvidenceCommit,
    OfficeRevisionCommit,
    OfficeRevisionStore,
)
from .templates import OfficeTemplateStore

_MAX_RENDER_BATCH_PAGES = 12
_MAX_WORKFLOW_PAGE_COUNT = 500
_RENDER_DPI = 120


@dataclass(frozen=True, slots=True)
class OfficeProjectRenderCommit:
    project_id: str
    revision_id: str
    evidence: tuple[OfficeRenderEvidenceCommit, ...]
    page_count: int


@dataclass(frozen=True, slots=True)
class OfficeProjectRestoreCommit:
    project: OfficeRevisionCommit
    restored_from_revision_id: str
    receipt: dict[str, Any]
    validation: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OfficeResolvedRenderSet:
    evidence: tuple[dict[str, Any], ...]
    page_count: int
    rendered_page_count: int
    complete: bool

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(record["evidence_id"] for record in self.evidence)


class OfficeProjectWorkflowService:
    """Coordinate expensive Office workflows while the store owns persistence."""

    def __init__(
        self,
        revision_store: OfficeRevisionStore,
        *,
        template_store: OfficeTemplateStore | None = None,
        renderer: Callable[..., OfficeRenderResult] | None = None,
    ) -> None:
        self.revision_store = revision_store
        self.template_store = template_store
        self._renderer = renderer or office_engine.render

    @staticmethod
    def _render_identity(rendered: OfficeRenderResult) -> tuple[str, ...]:
        return (
            rendered.renderer,
            rendered.renderer_version,
            rendered.pdfium_version,
            rendered.pipeline_fingerprint,
        )

    def _render_full_document(
        self,
        document: bytes,
        *,
        suffix: str,
    ) -> tuple[OfficeRenderResult, ...]:
        source_sha256 = hashlib.sha256(document).hexdigest()
        windows: list[OfficeRenderResult] = []
        expected_identity: tuple[str, ...] | None = None
        page_count: int | None = None
        start_page = 1
        while page_count is None or start_page <= page_count:
            rendered = self._renderer(
                document,
                suffix=suffix,
                start_page=start_page,
                max_pages=_MAX_RENDER_BATCH_PAGES,
                dpi=_RENDER_DPI,
            )
            if page_count is None:
                page_count = rendered.page_count
                if not 1 <= page_count <= _MAX_WORKFLOW_PAGE_COUNT:
                    raise OfficeRevisionError(f"Office project full render supports between 1 and {_MAX_WORKFLOW_PAGE_COUNT} pages")
            expected_pages = list(
                range(
                    start_page,
                    min(start_page + _MAX_RENDER_BATCH_PAGES, page_count + 1),
                )
            )
            identity = self._render_identity(rendered)
            if (
                rendered.format != suffix.lstrip(".").lower()
                or rendered.source_sha256 != source_sha256
                or rendered.page_count != page_count
                or rendered.start_page != start_page
                or rendered.dpi != _RENDER_DPI
                or [page.page for page in rendered.pages] != expected_pages
                or rendered.has_more != (expected_pages[-1] < page_count)
                or (expected_identity is not None and identity != expected_identity)
                or (suffix.lower() == ".pptx" and any(page.source_slide != page.page for page in rendered.pages))
            ):
                raise OfficeRevisionConflictError("Office project renderer returned inconsistent full-document evidence")
            expected_identity = identity
            windows.append(rendered)
            start_page = expected_pages[-1] + 1
        if not windows or page_count is None:
            raise OfficeRevisionError("Office project renderer returned no evidence")
        return tuple(windows)

    def render_revision(
        self,
        project_id: str,
        revision_id: str,
    ) -> OfficeProjectRenderCommit:
        revision, document = self.revision_store.read_revision_artifact(
            project_id,
            revision_id,
        )
        suffix = f".{revision['format']}"
        windows = self._render_full_document(document, suffix=suffix)
        provenance = revision.get("provenance")
        output_path = provenance.get("output_path") if isinstance(provenance, dict) else None
        filename = PurePosixPath(output_path).name if isinstance(output_path, str) else ""
        if not filename or PurePosixPath(filename).suffix.lower() != suffix:
            filename = f"office-project-{project_id}.{revision['format']}"
        thread_id = provenance.get("thread_id") if isinstance(provenance, dict) else None
        evidence: list[OfficeRenderEvidenceCommit] = []
        for rendered in windows:
            output_dir = f"/mnt/user-data/outputs/.office-project-renders/{revision_id}/window-{rendered.start_page:05d}"
            manifest = {
                "schema": RENDER_MANIFEST_SCHEMA,
                "complete": True,
                "project_id": project_id,
                "revision_id": revision_id,
                "format": revision["format"],
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
                "pages": [
                    {
                        "page": page.page,
                        **({"source_slide": page.source_slide} if page.source_slide is not None else {}),
                        "path": f"{output_dir}/{page.filename}",
                        "width": page.width,
                        "height": page.height,
                        "sha256": page.sha256,
                    }
                    for page in rendered.pages
                ],
                "visual_review_status": "pending",
                "gateway_page_access": "available",
            }
            evidence.append(
                self.revision_store.commit_render_evidence(
                    project_id=project_id,
                    revision_id=revision_id,
                    source=document,
                    suffix=suffix,
                    manifest=manifest,
                    pages=rendered.pages,
                    thread_id=thread_id,
                )
            )
        return OfficeProjectRenderCommit(
            project_id=project_id,
            revision_id=revision_id,
            evidence=tuple(evidence),
            page_count=windows[0].page_count,
        )

    def resolve_latest_render_set(
        self,
        project_id: str,
        revision_id: str,
    ) -> OfficeResolvedRenderSet:
        resolved = self.revision_store.resolve_latest_render_set(
            project_id,
            revision_id,
        )
        return OfficeResolvedRenderSet(
            resolved.evidence,
            resolved.page_count,
            resolved.rendered_page_count,
            resolved.complete,
        )

    def restore_revision(
        self,
        project_id: str,
        target_revision_id: str,
        *,
        expected_current_revision_id: str,
    ) -> OfficeProjectRestoreCommit:
        project = self.revision_store.load_project(project_id)
        if project["current_revision_id"] != expected_current_revision_id:
            raise OfficeRevisionConflictError("Office project has a newer current revision; reload before restoring")
        current_revision, current_data = self.revision_store.read_revision_artifact(
            project_id,
            expected_current_revision_id,
        )
        target_revision, target_data = self.revision_store.read_revision_artifact(
            project_id,
            target_revision_id,
        )
        if current_revision["revision_id"] == target_revision["revision_id"]:
            raise OfficeRevisionConflictError("Office restore target is already current")
        suffix = f".{project['format']}"
        resources = current_revision.get("resource_versions")
        template_resource = resources.get("template") if isinstance(resources, dict) else None
        semantic_targets = ()
        if template_resource is not None:
            if self.template_store is None:
                raise OfficeRevisionError("Office template policy store is required for this restore")
            semantic_targets = self.template_store.published_restore_targets(
                template_resource["template_id"],
                template_resource["version"],
            )
        receipt = build_restore_change_receipt(
            current_data,
            target_data,
            suffix=suffix,
            target_revision_id=target_revision_id,
            semantic_targets=semantic_targets,
        )
        template_policy = None
        if template_resource is not None:
            template_policy = self.template_store.enforce_published_restore_policy(
                template_resource["template_id"],
                template_resource["version"],
                source=current_data,
                result=target_data,
                receipt=receipt,
            )
        source_validation = office_engine.validate(current_data, suffix=suffix)
        target_validation = office_engine.validate(target_data, suffix=suffix)
        provenance = current_revision.get("provenance")
        output_path = provenance.get("output_path") if isinstance(provenance, dict) else None
        if not isinstance(output_path, str) or not output_path.startswith("/mnt/user-data/"):
            output_path = f"/mnt/user-data/outputs/office-project-{project_id}{suffix}"
        thread_id = provenance.get("thread_id") if isinstance(provenance, dict) else None
        commit = self.revision_store.commit_restore(
            project_id=project_id,
            parent_revision_id=expected_current_revision_id,
            restored_from_revision_id=target_revision_id,
            source=current_data,
            result=target_data,
            suffix=suffix,
            source_path=(f"/mnt/user-data/projects/{project_id}/revisions/{target_revision_id}/artifact{suffix}"),
            output_path=output_path,
            thread_id=thread_id,
            receipt=receipt,
            source_validation=source_validation,
            result_validation=target_validation,
            template_resource=template_resource,
            template_policy=template_policy,
        )
        return OfficeProjectRestoreCommit(
            project=commit,
            restored_from_revision_id=target_revision_id,
            receipt=receipt,
            validation=target_validation,
        )
