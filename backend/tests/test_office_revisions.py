from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest

from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.errors import (
    OfficeRevisionConflictError,
    OfficeRevisionError,
    OfficeRevisionIntegrityError,
)
from vassilflow.community.office.models import DocxTextReplacement
from vassilflow.community.office.render import RenderedOfficePage
from vassilflow.community.office.revisions import (
    PROJECT_SCHEMA,
    RENDER_EVIDENCE_SCHEMA,
    RENDER_MANIFEST_SCHEMA,
    REVISION_SCHEMA,
    OfficeRevisionCommit,
    OfficeRevisionStore,
)

_PROJECT_ID = f"ofp_{'1' * 32}"
_BASELINE_REVISION_ID = f"ofr_{'2' * 32}"
_FIRST_REVISION_ID = f"ofr_{'3' * 32}"
_SECOND_REVISION_ID = f"ofr_{'4' * 32}"
_EVIDENCE_ID = f"ofe_{'5' * 32}"
_CREATED_AT = datetime(2026, 7, 16, 9, 30, tzinfo=UTC)
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


def _edit(document: bytes, *, find: str, replace: str) -> tuple[bytes, dict, dict, dict]:
    edited, _reports, receipt = office_engine.edit_with_receipt(
        document,
        suffix=".docx",
        operations=[DocxTextReplacement(find=find, replace=replace)],
    )
    return (
        edited,
        receipt,
        office_engine.validate(document, suffix=".docx"),
        office_engine.validate(edited, suffix=".docx"),
    )


def _commit(
    store: OfficeRevisionStore,
    *,
    source: bytes,
    result: bytes,
    receipt: dict,
    source_validation: dict,
    result_validation: dict,
    project_id: str | None = None,
    parent_revision_id: str | None = None,
) -> OfficeRevisionCommit:
    return store.commit_edit(
        source=source,
        result=result,
        suffix=".docx",
        source_path="/mnt/user-data/uploads/source.docx",
        output_path="/mnt/user-data/workspace/result.docx",
        thread_id="thread-1",
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
        project_id=project_id,
        parent_revision_id=parent_revision_id,
    )


def _fixed_store(tmp_path: Path) -> OfficeRevisionStore:
    revision_ids = iter(
        (
            _BASELINE_REVISION_ID,
            _FIRST_REVISION_ID,
            _SECOND_REVISION_ID,
        )
    )
    return OfficeRevisionStore(
        tmp_path / "office",
        clock=lambda: _CREATED_AT,
        project_id_factory=lambda: _PROJECT_ID,
        revision_id_factory=lambda: next(revision_ids),
        evidence_id_factory=lambda: _EVIDENCE_ID,
    )


def _render_page() -> RenderedOfficePage:
    return RenderedOfficePage(
        page=1,
        filename="page-001.png",
        width=1,
        height=1,
        sha256=hashlib.sha256(_PNG).hexdigest(),
        data=_PNG,
    )


def _render_manifest(source: bytes) -> dict:
    output_dir = "/mnt/user-data/workspace/render-v1"
    page = _render_page()
    return {
        "schema": RENDER_MANIFEST_SCHEMA,
        "complete": True,
        "project_id": _PROJECT_ID,
        "revision_id": _FIRST_REVISION_ID,
        "format": "docx",
        "source_path": "/mnt/user-data/workspace/result.docx",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "source_size_bytes": len(source),
        "output_dir": output_dir,
        "manifest_path": f"{output_dir}/render-manifest.json",
        "renderer": "test-renderer",
        "renderer_version": "1.0",
        "pdfium_version": "5.11.0",
        "pipeline_fingerprint": "a" * 64,
        "page_count": 1,
        "start_page": 1,
        "end_page": 1,
        "requested_max_pages": 1,
        "dpi": 120,
        "has_more": False,
        "pages": [
            {
                "page": 1,
                "path": f"{output_dir}/page-001.png",
                "width": 1,
                "height": 1,
                "sha256": page.sha256,
            }
        ],
        "visual_review_status": "pending",
        "gateway_page_access": "available",
    }


def test_create_project_publishes_baseline_and_edit_revisions_once(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("old value")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )

    commit = _commit(
        store,
        source=source,
        result=result,
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
    )

    assert commit.project_id == _PROJECT_ID
    assert commit.baseline_revision_id == _BASELINE_REVISION_ID
    assert commit.parent_revision_id == _BASELINE_REVISION_ID
    assert commit.revision_id == _FIRST_REVISION_ID
    assert commit.sequence == 2
    project = store.load_project(_PROJECT_ID)
    assert project == {
        "schema": PROJECT_SCHEMA,
        "project_id": _PROJECT_ID,
        "format": "docx",
        "created_at": "2026-07-16T09:30:00Z",
        "updated_at": "2026-07-16T09:30:00Z",
        "primary_thread_id": "thread-1",
        "current_revision_id": _FIRST_REVISION_ID,
        "current_artifact_sha256": receipt["result"]["sha256"],
        "revision_count": 2,
    }
    baseline = store.load_revision(_PROJECT_ID, _BASELINE_REVISION_ID)
    revision = store.load_revision(_PROJECT_ID, _FIRST_REVISION_ID)
    assert baseline["schema"] == REVISION_SCHEMA
    assert baseline["kind"] == "baseline"
    assert baseline["parent_revision_id"] is None
    assert baseline["quality_at_commit"]["package_validation"] == source_validation
    assert revision["kind"] == "edit"
    assert revision["parent_revision_id"] == _BASELINE_REVISION_ID
    assert revision["operation_receipt"] == receipt
    assert revision["quality_at_commit"] == {
        "package_validation": result_validation,
        "preflight_status": "not_recorded",
        "render_status": "not_recorded",
        "visual_review_status": "not_performed",
    }
    project_dir = tmp_path / "office" / "projects" / _PROJECT_ID
    assert (project_dir / "revisions" / _BASELINE_REVISION_ID / "artifact.docx").read_bytes() == source
    assert (project_dir / "revisions" / _FIRST_REVISION_ID / "artifact.docx").read_bytes() == result
    assert not list((tmp_path / "office" / "projects").glob(".s-*"))


def test_append_checks_parent_and_preserves_prior_revision_bytes(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("one")
    first_result, first_receipt, source_validation, first_validation = _edit(
        source,
        find="one",
        replace="two",
    )
    first = _commit(
        store,
        source=source,
        result=first_result,
        receipt=first_receipt,
        source_validation=source_validation,
        result_validation=first_validation,
    )
    first_revision_path = tmp_path / "office" / "projects" / _PROJECT_ID / "revisions" / _FIRST_REVISION_ID / "revision.json"
    first_revision_bytes = first_revision_path.read_bytes()
    second_result, second_receipt, second_source_validation, second_validation = _edit(
        first_result,
        find="two",
        replace="three",
    )

    second = _commit(
        store,
        source=first_result,
        result=second_result,
        receipt=second_receipt,
        source_validation=second_source_validation,
        result_validation=second_validation,
        project_id=first.project_id,
        parent_revision_id=first.revision_id,
    )

    assert second.revision_id == _SECOND_REVISION_ID
    assert second.parent_revision_id == _FIRST_REVISION_ID
    assert second.sequence == 3
    assert second.project_created is False
    assert first_revision_path.read_bytes() == first_revision_bytes
    project = store.load_project(_PROJECT_ID)
    assert project["current_revision_id"] == _SECOND_REVISION_ID
    assert project["current_artifact_sha256"] == second_receipt["result"]["sha256"]
    assert project["revision_count"] == 3


def test_stale_parent_and_wrong_source_cannot_advance_project(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("one")
    first_result, first_receipt, source_validation, first_validation = _edit(
        source,
        find="one",
        replace="two",
    )
    first = _commit(
        store,
        source=source,
        result=first_result,
        receipt=first_receipt,
        source_validation=source_validation,
        result_validation=first_validation,
    )
    wrong_result, wrong_receipt, wrong_source_validation, wrong_validation = _edit(
        source,
        find="one",
        replace="other",
    )

    with pytest.raises(OfficeRevisionConflictError, match="does not match"):
        _commit(
            store,
            source=source,
            result=wrong_result,
            receipt=wrong_receipt,
            source_validation=wrong_source_validation,
            result_validation=wrong_validation,
            project_id=first.project_id,
            parent_revision_id=first.revision_id,
        )

    second_result, second_receipt, second_source_validation, second_validation = _edit(
        first_result,
        find="two",
        replace="three",
    )
    second = _commit(
        store,
        source=first_result,
        result=second_result,
        receipt=second_receipt,
        source_validation=second_source_validation,
        result_validation=second_validation,
        project_id=first.project_id,
        parent_revision_id=first.revision_id,
    )
    with pytest.raises(OfficeRevisionConflictError, match="newer current revision"):
        _commit(
            store,
            source=first_result,
            result=second_result,
            receipt=second_receipt,
            source_validation=second_source_validation,
            result_validation=second_validation,
            project_id=first.project_id,
            parent_revision_id=first.revision_id,
        )
    assert store.load_project(_PROJECT_ID)["current_revision_id"] == second.revision_id


def test_revision_integrity_check_rejects_tampered_artifact(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    commit = _commit(
        store,
        source=source,
        result=result,
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
    )
    artifact = tmp_path / "office" / "projects" / commit.project_id / "revisions" / commit.revision_id / "artifact.docx"
    artifact.write_bytes(b"tampered")

    with pytest.raises(OfficeRevisionIntegrityError, match="SHA-256"):
        store.load_revision(commit.project_id, commit.revision_id)


def test_revision_integrity_check_rejects_incomplete_receipt_metadata(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    commit = _commit(
        store,
        source=source,
        result=result,
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
    )
    metadata_path = tmp_path / "office" / "projects" / commit.project_id / "revisions" / commit.revision_id / "revision.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["operation_receipt"].pop("semantic_changes")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(OfficeRevisionIntegrityError, match="semantic evidence"):
        store.load_revision(commit.project_id, commit.revision_id)


def test_receipt_hash_mismatch_and_partial_project_ids_fail_before_writes(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    tampered_receipt = json.loads(json.dumps(receipt))
    tampered_receipt["result"]["sha256"] = "0" * 64

    with pytest.raises(OfficeRevisionIntegrityError, match="receipt"):
        _commit(
            store,
            source=source,
            result=result,
            receipt=tampered_receipt,
            source_validation=source_validation,
            result_validation=result_validation,
        )
    with pytest.raises(OfficeRevisionError, match="provided together"):
        _commit(
            store,
            source=source,
            result=result,
            receipt=receipt,
            source_validation=source_validation,
            result_validation=result_validation,
            project_id=_PROJECT_ID,
        )
    assert not (tmp_path / "office" / "projects" / _PROJECT_ID).exists()


def test_render_evidence_persists_preview_without_mutating_revision_core(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    revision = _commit(
        store,
        source=source,
        result=result,
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
    )
    revision_json = tmp_path / "office" / "projects" / revision.project_id / "revisions" / revision.revision_id / "revision.json"
    revision_bytes = revision_json.read_bytes()
    manifest = _render_manifest(result)

    evidence = store.commit_render_evidence(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        source=result,
        suffix=".docx",
        manifest=manifest,
        pages=(_render_page(),),
        thread_id="thread-1",
    )

    assert evidence.evidence_id == _EVIDENCE_ID
    assert evidence.revision_id == revision.revision_id
    assert evidence.visual_review_status == "pending"
    assert revision_json.read_bytes() == revision_bytes
    persisted = store.load_render_evidence(revision.project_id, evidence.evidence_id)
    assert persisted["schema"] == RENDER_EVIDENCE_SCHEMA
    assert persisted["render_manifest"] == manifest
    assert persisted["source"] == {
        "sha256": hashlib.sha256(result).hexdigest(),
        "size_bytes": len(result),
    }
    preview = persisted["preview_pages"][0]
    assert preview["workspace_filename"] == "page-001.png"
    assert preview["filename"] == "page-00001.png"
    evidence_dir = tmp_path / "office" / "projects" / revision.project_id / "renders" / evidence.evidence_id
    assert (evidence_dir / "pages" / "page-00001.png").read_bytes() == _PNG
    assert store.list_render_evidence(
        revision.project_id,
        revision_id=revision.revision_id,
    ) == [persisted]


def test_read_surfaces_list_canonical_history_and_verified_bytes(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    revision = _commit(
        store,
        source=source,
        result=result,
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
    )
    evidence = store.commit_render_evidence(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        source=result,
        suffix=".docx",
        manifest=_render_manifest(result),
        pages=(_render_page(),),
        thread_id="thread-1",
    )

    orphan_id = f"ofr_{'9' * 32}"
    orphan_dir = tmp_path / "office" / "projects" / revision.project_id / "revisions" / orphan_id
    orphan_dir.mkdir()
    (orphan_dir / "unpublished").write_text("ignored", encoding="utf-8")

    projects = store.list_projects()
    revisions = store.list_revisions(revision.project_id)
    artifact_metadata, artifact_bytes = store.read_revision_artifact(
        revision.project_id,
        revision.revision_id,
    )
    render_metadata, preview_metadata, preview_bytes = store.read_render_preview_page(
        revision.project_id,
        evidence.evidence_id,
        1,
    )

    assert [project["project_id"] for project in projects] == [revision.project_id]
    assert [item["revision_id"] for item in revisions] == [
        revision.revision_id,
        revision.baseline_revision_id,
    ]
    assert orphan_id not in {item["revision_id"] for item in revisions}
    with pytest.raises(OfficeRevisionError, match="project history"):
        store.load_project_revision(revision.project_id, orphan_id)
    with pytest.raises(OfficeRevisionError, match="project history"):
        store.read_revision_artifact(revision.project_id, orphan_id)
    assert artifact_metadata["artifact"]["sha256"] == hashlib.sha256(result).hexdigest()
    assert artifact_bytes == result
    assert render_metadata["evidence_id"] == evidence.evidence_id
    assert preview_metadata["page"] == 1
    assert preview_bytes == _PNG


def test_baseline_rejects_injected_generation_evidence(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    revision = _commit(
        store,
        source=source,
        result=result,
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
    )
    metadata_path = tmp_path / "office" / "projects" / revision.project_id / "revisions" / revision.baseline_revision_id / "revision.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["generation"] = {"intent": {}, "receipt": {}, "preflight": {}}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(OfficeRevisionIntegrityError, match="baseline revision"):
        store.load_revision(revision.project_id, revision.baseline_revision_id)


def test_project_snapshot_list_loads_only_selected_current_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OfficeRevisionStore(tmp_path / "office")
    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    for _ in range(2):
        _commit(
            store,
            source=source,
            result=result,
            receipt=receipt,
            source_validation=source_validation,
            result_validation=result_validation,
        )

    loaded_revision_ids: list[str] = []
    original = store._load_revision_unlocked

    def counted(project_id: str, revision_id: str) -> dict:
        loaded_revision_ids.append(revision_id)
        return original(project_id, revision_id)

    monkeypatch.setattr(store, "_load_revision_unlocked", counted)

    snapshots = store.list_project_snapshots(limit=1)

    assert len(snapshots) == 1
    assert loaded_revision_ids == [snapshots[0][0]["current_revision_id"]]


def test_render_evidence_read_and_write_surfaces_reject_orphan_revision(
    tmp_path: Path,
) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    revision = _commit(
        store,
        source=source,
        result=result,
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
    )
    manifest = _render_manifest(result)
    evidence = store.commit_render_evidence(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        source=result,
        suffix=".docx",
        manifest=manifest,
        pages=(_render_page(),),
        thread_id="thread-1",
    )

    project_path = tmp_path / "office" / "projects" / revision.project_id / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    baseline = store.load_revision(
        revision.project_id,
        revision.baseline_revision_id,
    )
    project.update(
        current_revision_id=revision.baseline_revision_id,
        current_artifact_sha256=baseline["artifact"]["sha256"],
        revision_count=1,
    )
    project_path.write_text(json.dumps(project), encoding="utf-8")

    assert store.list_render_evidence(revision.project_id) == []
    with pytest.raises(OfficeRevisionError, match="project history"):
        store.list_render_evidence(
            revision.project_id,
            revision_id=revision.revision_id,
        )
    with pytest.raises(OfficeRevisionError, match="project history"):
        store.load_render_evidence(revision.project_id, evidence.evidence_id)
    with pytest.raises(OfficeRevisionError, match="project history"):
        store.read_render_preview_page(
            revision.project_id,
            evidence.evidence_id,
            1,
        )
    with pytest.raises(OfficeRevisionError, match="project history"):
        store.verify_revision_source(
            project_id=revision.project_id,
            revision_id=revision.revision_id,
            source=result,
            suffix=".docx",
        )
    with pytest.raises(OfficeRevisionError, match="project history"):
        store.commit_render_evidence(
            project_id=revision.project_id,
            revision_id=revision.revision_id,
            source=result,
            suffix=".docx",
            manifest=manifest,
            pages=(_render_page(),),
            thread_id="thread-1",
        )


def test_read_surfaces_reject_invalid_limits_and_missing_preview_page(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    assert store.list_projects() == []
    with pytest.raises(OfficeRevisionError, match="project limit"):
        store.list_projects(limit=0)

    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    revision = _commit(
        store,
        source=source,
        result=result,
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
    )
    evidence = store.commit_render_evidence(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        source=result,
        suffix=".docx",
        manifest=_render_manifest(result),
        pages=(_render_page(),),
        thread_id="thread-1",
    )

    with pytest.raises(OfficeRevisionError, match="revision limit"):
        store.list_revisions(revision.project_id, limit=501)
    with pytest.raises(OfficeRevisionError, match="was not found"):
        store.read_render_preview_page(revision.project_id, evidence.evidence_id, 2)


def test_render_evidence_rejects_wrong_revision_source_and_tampered_preview(tmp_path: Path) -> None:
    store = _fixed_store(tmp_path)
    source = _docx("old")
    result, receipt, source_validation, result_validation = _edit(
        source,
        find="old",
        replace="new",
    )
    revision = _commit(
        store,
        source=source,
        result=result,
        receipt=receipt,
        source_validation=source_validation,
        result_validation=result_validation,
    )
    with pytest.raises(OfficeRevisionConflictError, match="does not match"):
        store.verify_revision_source(
            project_id=revision.project_id,
            revision_id=revision.revision_id,
            source=source,
            suffix=".docx",
        )
    evidence = store.commit_render_evidence(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        source=result,
        suffix=".docx",
        manifest=_render_manifest(result),
        pages=(_render_page(),),
        thread_id="thread-1",
    )
    preview = tmp_path / "office" / "projects" / revision.project_id / "renders" / evidence.evidence_id / "pages" / "page-00001.png"
    preview.write_bytes(b"tampered")

    with pytest.raises(OfficeRevisionIntegrityError, match="SHA-256"):
        store.load_render_evidence(revision.project_id, evidence.evidence_id)


def test_concurrent_appends_allow_only_one_current_parent(tmp_path: Path) -> None:
    store = OfficeRevisionStore(tmp_path / "office")
    source = _docx("one")
    first_result, first_receipt, source_validation, first_validation = _edit(
        source,
        find="one",
        replace="two",
    )
    first = _commit(
        store,
        source=source,
        result=first_result,
        receipt=first_receipt,
        source_validation=source_validation,
        result_validation=first_validation,
    )
    result, receipt, next_source_validation, result_validation = _edit(
        first_result,
        find="two",
        replace="three",
    )
    barrier = Barrier(2)

    def append_once() -> OfficeRevisionCommit | Exception:
        second_store = OfficeRevisionStore(tmp_path / "office")
        barrier.wait()
        try:
            return _commit(
                second_store,
                source=first_result,
                result=result,
                receipt=receipt,
                source_validation=next_source_validation,
                result_validation=result_validation,
                project_id=first.project_id,
                parent_revision_id=first.revision_id,
            )
        except Exception as exc:  # noqa: BLE001 - assert the competing transaction outcome
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: append_once(), range(2)))

    commits = [outcome for outcome in outcomes if isinstance(outcome, OfficeRevisionCommit)]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, OfficeRevisionConflictError)]
    assert len(commits) == 1
    assert len(conflicts) == 1
    assert store.load_project(first.project_id)["current_revision_id"] == commits[0].revision_id
