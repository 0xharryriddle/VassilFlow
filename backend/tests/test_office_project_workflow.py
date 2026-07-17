from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.errors import OfficeRevisionConflictError
from vassilflow.community.office.models import DocxTextReplacement
from vassilflow.community.office.project_workflow import OfficeProjectWorkflowService
from vassilflow.community.office.render import OfficeRenderResult, RenderedOfficePage
from vassilflow.community.office.revisions import OfficeRevisionStore

_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def _docx(text: str) -> bytes:
    document = (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p><w:sectPr/></w:body></w:document>').encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _seed_project(store: OfficeRevisionStore) -> tuple[bytes, bytes, str, str, str]:
    source = _docx("one")
    result, _reports, receipt = office_engine.edit_with_receipt(
        source,
        suffix=".docx",
        operations=[DocxTextReplacement(find="one", replace="two")],
    )
    commit = store.commit_edit(
        source=source,
        result=result,
        suffix=".docx",
        source_path="/mnt/user-data/uploads/source.docx",
        output_path="/mnt/user-data/outputs/report.docx",
        thread_id="thread-office",
        receipt=receipt,
        source_validation=office_engine.validate(source, suffix=".docx"),
        result_validation=office_engine.validate(result, suffix=".docx"),
    )
    return (
        source,
        result,
        commit.project_id,
        commit.baseline_revision_id or "",
        commit.revision_id,
    )


def _renderer(page_count: int = 13):
    def render(
        document: bytes,
        *,
        suffix: str,
        start_page: int,
        max_pages: int,
        dpi: int,
    ) -> OfficeRenderResult:
        end_page = min(page_count, start_page + max_pages - 1)
        pages = tuple(
            RenderedOfficePage(
                page=page,
                filename=f"page-{page:03d}.png",
                width=1,
                height=1,
                sha256=hashlib.sha256(_PNG).hexdigest(),
                data=_PNG,
            )
            for page in range(start_page, end_page + 1)
        )
        return OfficeRenderResult(
            format=suffix.lstrip("."),
            renderer="test-renderer",
            renderer_version="1.0",
            pdfium_version="5.11.0",
            source_sha256=hashlib.sha256(document).hexdigest(),
            pipeline_fingerprint="a" * 64,
            page_count=page_count,
            start_page=start_page,
            dpi=dpi,
            pages=pages,
        )

    return render


def test_project_review_requires_complete_evidence_and_final_stays_separate_from_current(
    tmp_path: Path,
) -> None:
    store = OfficeRevisionStore(tmp_path / "office")
    source, result, project_id, baseline_revision_id, revision_id = _seed_project(store)
    workflow = OfficeProjectWorkflowService(store, renderer=_renderer())

    rendered = workflow.render_revision(project_id, revision_id)
    assert len(rendered.evidence) == 2
    with pytest.raises(
        OfficeRevisionConflictError,
        match="complete render evidence",
    ):
        store.commit_project_review(
            project_id=project_id,
            revision_id=revision_id,
            evidence_ids=[rendered.evidence[0].evidence_id],
            status="approved",
            reviewed_by="alice",
        )

    review = store.commit_project_review(
        project_id=project_id,
        revision_id=revision_id,
        evidence_ids=[item.evidence_id for item in rendered.evidence],
        status="approved",
        reviewed_by="alice",
        note="Checked every page",
    )
    final = store.commit_final_selection(
        project_id=project_id,
        revision_id=revision_id,
        review_id=review.review_id,
        expected_current_revision_id=revision_id,
    )
    assert final.revision_id == revision_id
    selection, final_revision, final_data = store.read_final_artifact(project_id)
    assert selection["review_id"] == review.review_id
    assert final_revision["revision_id"] == revision_id
    assert final_data == result

    restored = workflow.restore_revision(
        project_id,
        baseline_revision_id,
        expected_current_revision_id=revision_id,
    )
    project = store.load_project(project_id)
    assert project["current_revision_id"] == restored.project.revision_id
    assert project["final_revision_id"] == revision_id
    assert store.read_final_artifact(project_id)[2] == result
    assert store.read_revision_artifact(project_id, restored.project.revision_id)[1] == source

    [restore_revision, edit_revision, baseline_revision] = store.list_revisions(project_id)
    assert [restore_revision["kind"], edit_revision["kind"], baseline_revision["kind"]] == [
        "restore",
        "edit",
        "baseline",
    ]
    assert restore_revision["restored_from_revision_id"] == baseline_revision_id
    assert restore_revision["operation_receipt"]["operations"][0]["type"] == "restore_revision"
    assert restore_revision["operation_receipt"]["semantic_changes"]["coverage"] == "partial"


def test_latest_changes_requested_review_cannot_be_selected_as_final(tmp_path: Path) -> None:
    store = OfficeRevisionStore(tmp_path / "office")
    _source, _result, project_id, _baseline_revision_id, revision_id = _seed_project(store)
    rendered = OfficeProjectWorkflowService(store, renderer=_renderer(page_count=1)).render_revision(
        project_id,
        revision_id,
    )
    approved = store.commit_project_review(
        project_id=project_id,
        revision_id=revision_id,
        evidence_ids=[rendered.evidence[0].evidence_id],
        status="approved",
        reviewed_by="alice",
    )
    store.commit_project_review(
        project_id=project_id,
        revision_id=revision_id,
        evidence_ids=[rendered.evidence[0].evidence_id],
        status="changes_requested",
        reviewed_by="alice",
    )

    with pytest.raises(
        OfficeRevisionConflictError,
        match="latest approved review",
    ):
        store.commit_final_selection(
            project_id=project_id,
            revision_id=revision_id,
            review_id=approved.review_id,
            expected_current_revision_id=revision_id,
        )


def test_rerender_requires_a_new_review_before_final_selection(tmp_path: Path) -> None:
    store = OfficeRevisionStore(tmp_path / "office")
    _source, _result, project_id, _baseline_revision_id, revision_id = _seed_project(store)
    workflow = OfficeProjectWorkflowService(store, renderer=_renderer(page_count=2))

    first_render = workflow.render_revision(project_id, revision_id)
    first_evidence_ids = [item.evidence_id for item in first_render.evidence]
    first_review = store.commit_project_review(
        project_id=project_id,
        revision_id=revision_id,
        evidence_ids=first_evidence_ids,
        status="approved",
        reviewed_by="alice",
    )

    second_render = workflow.render_revision(project_id, revision_id)
    second_evidence_ids = [item.evidence_id for item in second_render.evidence]
    assert workflow.resolve_latest_render_set(project_id, revision_id).evidence_ids == tuple(second_evidence_ids)

    with pytest.raises(
        OfficeRevisionConflictError,
        match="latest complete render evidence",
    ):
        store.commit_project_review(
            project_id=project_id,
            revision_id=revision_id,
            evidence_ids=first_evidence_ids,
            status="approved",
            reviewed_by="alice",
        )
    with pytest.raises(
        OfficeRevisionConflictError,
        match="review of the latest complete render evidence",
    ):
        store.commit_final_selection(
            project_id=project_id,
            revision_id=revision_id,
            review_id=first_review.review_id,
            expected_current_revision_id=revision_id,
        )

    second_review = store.commit_project_review(
        project_id=project_id,
        revision_id=revision_id,
        evidence_ids=second_evidence_ids,
        status="approved",
        reviewed_by="alice",
    )
    final = store.commit_final_selection(
        project_id=project_id,
        revision_id=revision_id,
        review_id=second_review.review_id,
        expected_current_revision_id=revision_id,
    )
    assert final.review_id == second_review.review_id


def test_resolved_render_set_rejects_stale_revision_identity(tmp_path: Path) -> None:
    store = OfficeRevisionStore(tmp_path / "office")
    _source, _result, project_id, baseline_revision_id, revision_id = _seed_project(store)
    workflow = OfficeProjectWorkflowService(store, renderer=_renderer(page_count=2))
    workflow.render_revision(project_id, revision_id)

    current = workflow.resolve_latest_render_set(project_id, revision_id)
    baseline = workflow.resolve_latest_render_set(project_id, baseline_revision_id)

    assert current.complete is True
    assert current.rendered_page_count == 2
    assert baseline.complete is False
    assert baseline.evidence == ()
