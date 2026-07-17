from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

import app.gateway.routers.office_projects as office_projects_router
from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.generation import (
    PRESENTATION_INTENT_SCHEMA,
    PresentationIntent,
    compile_presentation,
)
from vassilflow.community.office.models import DocxTextReplacement, PptxTextReplacement
from vassilflow.community.office.render import RenderedOfficePage
from vassilflow.community.office.revisions import RENDER_MANIFEST_SCHEMA, OfficeRevisionStore
from vassilflow.config.paths import get_paths

_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
_PPTX_CORPUS = Path(__file__).parent / "fixtures" / "office" / "pptx" / "roundtrip" / "seed-v1.pptx"


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


def _seed_project(user_id: str) -> tuple[OfficeRevisionStore, str, str, str, bytes]:
    source = _docx("old value")
    result, _reports, receipt = office_engine.edit_with_receipt(
        source,
        suffix=".docx",
        operations=[DocxTextReplacement(find="old", replace="new")],
    )
    store = OfficeRevisionStore(get_paths().user_office_dir(user_id))
    revision = store.commit_edit(
        source=source,
        result=result,
        suffix=".docx",
        source_path="/mnt/user-data/uploads/source.docx",
        output_path="/mnt/user-data/outputs/result.docx",
        thread_id="thread-office-1",
        receipt=receipt,
        source_validation=office_engine.validate(source, suffix=".docx"),
        result_validation=office_engine.validate(result, suffix=".docx"),
    )
    page = RenderedOfficePage(
        page=1,
        filename="page-001.png",
        width=1,
        height=1,
        sha256=hashlib.sha256(_PNG).hexdigest(),
        data=_PNG,
    )
    output_dir = "/mnt/user-data/workspace/render-v1"
    manifest = {
        "schema": RENDER_MANIFEST_SCHEMA,
        "complete": True,
        "project_id": revision.project_id,
        "revision_id": revision.revision_id,
        "format": "docx",
        "source_path": "/mnt/user-data/outputs/result.docx",
        "source_sha256": hashlib.sha256(result).hexdigest(),
        "source_size_bytes": len(result),
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
    evidence = store.commit_render_evidence(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        source=result,
        suffix=".docx",
        manifest=manifest,
        pages=(page,),
        thread_id="thread-office-1",
    )
    return store, revision.project_id, revision.revision_id, evidence.evidence_id, result


def _seed_pptx_project(
    user_id: str,
) -> tuple[OfficeRevisionStore, str, str, str, bytes]:
    source = _PPTX_CORPUS.read_bytes()
    result, _reports, receipt = office_engine.edit_with_receipt(
        source,
        suffix=".pptx",
        operations=[
            PptxTextReplacement(
                paths=["/slide[1]/shape[@id=5]"],
                find="Final",
                replace="Reviewed",
            )
        ],
    )
    store = OfficeRevisionStore(get_paths().user_office_dir(user_id))
    revision = store.commit_edit(
        source=source,
        result=result,
        suffix=".pptx",
        source_path="/mnt/user-data/uploads/source.pptx",
        output_path="/mnt/user-data/outputs/result.pptx",
        thread_id="thread-office-pptx-1",
        receipt=receipt,
        source_validation=office_engine.validate(source, suffix=".pptx"),
        result_validation=office_engine.validate(result, suffix=".pptx"),
    )
    baseline_revision_id = store.list_revisions(revision.project_id)[-1]["revision_id"]
    return store, revision.project_id, revision.revision_id, baseline_revision_id, result


def _seed_generated_pptx_project(
    user_id: str,
) -> tuple[OfficeRevisionStore, str, str, str, bytes]:
    intent = PresentationIntent.model_validate(
        {
            "schema": PRESENTATION_INTENT_SCHEMA,
            "title": "Native quarterly deck",
            "slides": [
                {
                    "id": "opening",
                    "purpose": "Open the quarterly review",
                    "layout": "title",
                    "elements": [
                        {
                            "kind": "text",
                            "id": "opening-title",
                            "role": "title",
                            "text": "Native quarterly deck",
                        }
                    ],
                }
            ],
        }
    )
    artifact, receipt = compile_presentation(intent)
    preflight = office_engine.preflight(artifact, suffix=".pptx")
    store = OfficeRevisionStore(get_paths().user_office_dir(user_id))
    revision = store.commit_generation(
        artifact=artifact,
        output_path="/mnt/user-data/outputs/native-quarterly-deck.pptx",
        thread_id="thread-office-generation-1",
        intent=intent.model_dump(by_alias=True, exclude_none=True, mode="json"),
        receipt=receipt,
        preflight=preflight,
        validation=office_engine.validate(artifact, suffix=".pptx"),
    )
    page = RenderedOfficePage(
        page=1,
        source_slide=1,
        filename="slide-001.png",
        width=1,
        height=1,
        sha256=hashlib.sha256(_PNG).hexdigest(),
        data=_PNG,
    )
    output_dir = "/mnt/user-data/workspace/generated-render-v1"
    manifest = {
        "schema": RENDER_MANIFEST_SCHEMA,
        "complete": True,
        "project_id": revision.project_id,
        "revision_id": revision.revision_id,
        "format": "pptx",
        "source_path": "/mnt/user-data/outputs/native-quarterly-deck.pptx",
        "source_sha256": hashlib.sha256(artifact).hexdigest(),
        "source_size_bytes": len(artifact),
        "output_dir": output_dir,
        "manifest_path": f"{output_dir}/render-manifest.json",
        "renderer": "test-renderer",
        "renderer_version": "1.0",
        "pdfium_version": "5.11.0",
        "pipeline_fingerprint": "b" * 64,
        "page_count": 1,
        "start_page": 1,
        "end_page": 1,
        "requested_max_pages": 1,
        "dpi": 120,
        "has_more": False,
        "pages": [
            {
                "page": 1,
                "source_slide": 1,
                "path": f"{output_dir}/slide-001.png",
                "width": 1,
                "height": 1,
                "sha256": page.sha256,
            }
        ],
        "visual_review_status": "pending",
        "gateway_page_access": "available",
    }
    evidence = store.commit_render_evidence(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        source=artifact,
        suffix=".pptx",
        manifest=manifest,
        pages=(page,),
        thread_id="thread-office-generation-1",
    )
    return (
        store,
        revision.project_id,
        revision.revision_id,
        evidence.evidence_id,
        artifact,
    )


def _client() -> TestClient:
    app = make_authed_test_app()
    app.include_router(office_projects_router.router)
    return TestClient(app)


def test_generated_project_api_exposes_bounded_generation_and_render_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    monkeypatch.setattr(
        office_projects_router,
        "get_effective_user_id",
        lambda: "generation-user",
    )
    _store, project_id, revision_id, evidence_id, artifact = _seed_generated_pptx_project("generation-user")

    with _client() as client:
        recent = client.get("/api/office/projects")
        detail = client.get(f"/api/office/projects/{project_id}")
        revision = client.get(f"/api/office/projects/{project_id}/revisions/{revision_id}")
        comparison = client.get(f"/api/office/projects/{project_id}/revisions/{revision_id}/comparison")
        preview = client.get(f"/api/office/projects/{project_id}/renders/{evidence_id}/pages/1")

    assert recent.status_code == detail.status_code == revision.status_code == 200
    [project] = recent.json()["projects"]
    assert project["title"] == "native-quarterly-deck.pptx"
    assert project["current_revision"]["kind"] == "generation"
    assert project["current_revision"]["parent_revision_id"] is None
    assert project["current_revision"]["generation_slide_count"] == 1
    assert project["current_revision"]["generation_object_count"] == 1
    assert project["current_revision"]["latest_render"]["preview_pages"][0]["url"].endswith("/pages/1")

    detail_payload = detail.json()
    generation_receipt = detail_payload["generation_receipt"]
    assert generation_receipt["output"]["sha256"] == hashlib.sha256(artifact).hexdigest()
    assert generation_receipt["presentation"]["slide_count"] == 1
    assert generation_receipt["slides"][0]["objects"][0]["element_id"] == ("opening-title")
    assert generation_receipt["slides"][0]["objects"][0]["object_path"].startswith("/slide[1]/shape[@id=")
    assert detail_payload["generation_preflight"] == {
        "schema": "vassilflow.office.pptx.quality_preflight.v1",
        "source_sha256": hashlib.sha256(artifact).hexdigest(),
        "source_size_bytes": len(artifact),
        "slide_count": 1,
        "object_count": 1,
        "picture_count": 0,
        "finding_count": 0,
        "findings_returned": 0,
        "findings_truncated": False,
        "findings_by_severity": {},
    }
    assert "/mnt/user-data/" not in detail.text

    revision_payload = revision.json()
    assert revision_payload["operation_receipt"] is None
    assert revision_payload["generation_receipt"] == generation_receipt
    assert revision_payload["generation_preflight"] == detail_payload["generation_preflight"]
    assert comparison.status_code == 409
    assert "initial revision" in comparison.json()["detail"]
    assert preview.status_code == 200
    assert preview.content == _PNG


def test_office_project_api_lists_evidence_and_serves_verified_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "alice")
    store, project_id, revision_id, evidence_id, result = _seed_project("alice")
    baseline_revision_id = store.list_revisions(project_id)[-1]["revision_id"]

    with _client() as client:
        recent = client.get("/api/office/projects")
        detail = client.get(f"/api/office/projects/{project_id}")
        revisions = client.get(f"/api/office/projects/{project_id}/revisions")
        current_revision = client.get(f"/api/office/projects/{project_id}/revisions/{revision_id}")
        baseline_revision = client.get(f"/api/office/projects/{project_id}/revisions/{baseline_revision_id}")
        preview = client.get(f"/api/office/projects/{project_id}/renders/{evidence_id}/pages/1")
        not_modified = client.get(
            f"/api/office/projects/{project_id}/renders/{evidence_id}/pages/1",
            headers={"If-None-Match": preview.headers["etag"]},
        )
        artifact = client.get(f"/api/office/projects/{project_id}/revisions/{revision_id}/artifact")

    assert recent.status_code == 200
    [project] = recent.json()["projects"]
    assert project["title"] == "result.docx"
    assert project["primary_thread_id"] == "thread-office-1"
    assert project["current_revision"]["artifact"]["sha256"] == hashlib.sha256(result).hexdigest()
    assert project["current_revision"]["quality"] == {
        "package_validation_status": "valid",
        "preflight_status": "not_recorded",
        "render_evidence_status": "available",
        "visual_review_status": "pending",
    }
    assert project["current_revision"]["latest_render"]["preview_pages"][0]["url"].endswith(f"/{evidence_id}/pages/1")

    assert detail.status_code == 200
    detail_payload = detail.json()
    assert [item["evidence_id"] for item in detail_payload["render_evidence"]] == [evidence_id]
    serialized_detail = json.dumps(detail_payload)
    assert "source_path" not in serialized_detail
    assert "output_dir" not in serialized_detail
    assert str(tmp_path) not in serialized_detail

    assert revisions.status_code == 200
    assert [item["sequence"] for item in revisions.json()["revisions"]] == [2, 1]
    assert current_revision.status_code == 200
    assert current_revision.json()["is_current"] is True
    assert [item["evidence_id"] for item in current_revision.json()["render_evidence"]] == [evidence_id]
    assert baseline_revision.status_code == 200
    assert baseline_revision.json()["is_current"] is False
    assert baseline_revision.json()["revision"]["kind"] == "baseline"
    assert baseline_revision.json()["render_evidence"] == []
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content == _PNG
    assert not_modified.status_code == 304
    assert artifact.status_code == 200
    assert artifact.headers["content-disposition"].startswith("attachment;")
    assert artifact.content == result


def test_office_project_api_is_user_scoped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    _store, project_id, _revision_id, _evidence_id, _result = _seed_project("alice")
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "bob")

    with _client() as client:
        recent = client.get("/api/office/projects")
        detail = client.get(f"/api/office/projects/{project_id}")

    assert recent.status_code == 200
    assert recent.json() == {"projects": []}
    assert detail.status_code == 404


def test_office_project_api_returns_hash_bound_pptx_selection_surface(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "alice")
    _store, project_id, revision_id, baseline_revision_id, result = _seed_pptx_project("alice")

    with _client() as client:
        current = client.get(
            f"/api/office/projects/{project_id}/revisions/{revision_id}/selection",
            params={"slide": 1},
        )
        historical = client.get(
            f"/api/office/projects/{project_id}/revisions/{baseline_revision_id}/selection",
            params={"slide": 1},
        )
        missing_slide = client.get(
            f"/api/office/projects/{project_id}/revisions/{revision_id}/selection",
            params={"slide": 99},
        )

    assert current.status_code == 200
    payload = current.json()
    assert payload["project_id"] == project_id
    assert payload["revision_id"] == revision_id
    assert payload["is_current"] is True
    assert payload["source_sha256"] == hashlib.sha256(result).hexdigest()
    selected = next(item for item in payload["objects"] if item["path"] == "/slide[1]/shape[@id=3]")
    assert selected["selection_status"] == "selectable"
    assert selected["text_preview"] == "AlphaBeta"
    assert selected["overlay"]["width_percent"] > 0
    assert "format_pptx_runs" in selected["allowed_operations"]
    serialized = json.dumps(payload)
    assert "part_name" not in serialized
    assert "/mnt/user-data" not in serialized
    assert str(tmp_path) not in serialized

    assert historical.status_code == 200
    assert historical.json()["is_current"] is False
    assert historical.json()["source_sha256"] == hashlib.sha256(_PPTX_CORPUS.read_bytes()).hexdigest()
    assert missing_slide.status_code == 422


def test_office_project_selection_rejects_non_pptx_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "alice")
    _store, project_id, revision_id, _evidence_id, _result = _seed_project("alice")

    with _client() as client:
        response = client.get(
            f"/api/office/projects/{project_id}/revisions/{revision_id}/selection",
            params={"slide": 1},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Object selection is currently available for PPTX projects only"}


def test_office_project_api_rejects_tampered_preview(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "alice")
    store, project_id, _revision_id, evidence_id, _result = _seed_project("alice")
    preview_path = store.root / "projects" / project_id / "renders" / evidence_id / "pages" / "page-00001.png"
    preview_path.write_bytes(b"tampered")

    with _client() as client:
        response = client.get(f"/api/office/projects/{project_id}/renders/{evidence_id}/pages/1")

    assert response.status_code == 409
    assert response.json() == {"detail": "Office project evidence failed integrity checks."}


def test_office_project_api_does_not_publish_or_serve_orphan_render_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "alice")
    store, project_id, revision_id, evidence_id, _result = _seed_project("alice")

    project_path = store.root / "projects" / project_id / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    baseline = store.list_revisions(project_id)[-1]
    project.update(
        current_revision_id=baseline["revision_id"],
        current_artifact_sha256=baseline["artifact"]["sha256"],
        revision_count=1,
    )
    project_path.write_text(json.dumps(project), encoding="utf-8")

    with _client() as client:
        recent = client.get("/api/office/projects")
        detail = client.get(f"/api/office/projects/{project_id}")
        preview = client.get(f"/api/office/projects/{project_id}/renders/{evidence_id}/pages/1")
        orphan_revision = client.get(f"/api/office/projects/{project_id}/revisions/{revision_id}")

    assert recent.status_code == 200
    [listed_project] = recent.json()["projects"]
    assert listed_project["current_revision"]["revision_id"] == baseline["revision_id"]
    assert listed_project["current_revision"]["latest_render"] is None
    assert detail.status_code == 200
    assert detail.json()["render_evidence"] == []
    assert preview.status_code == 404
    assert orphan_revision.status_code == 404


def test_office_project_api_hides_invalid_identifiers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "alice")

    with _client() as client:
        response = client.get("/api/office/projects/not-a-project")

    assert response.status_code == 404
    assert response.json() == {"detail": "Office project resource was not found."}


def test_office_project_review_final_comparison_and_restore_flow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "alice")
    store, project_id, revision_id, evidence_id, result = _seed_project("alice")
    baseline_revision_id = store.list_revisions(project_id)[-1]["revision_id"]

    with _client() as client:
        review = client.post(
            f"/api/office/projects/{project_id}/revisions/{revision_id}/reviews",
            json={
                "status": "approved",
                "evidence_ids": [evidence_id],
                "note": "Checked the rendered page",
            },
        )
        assert review.status_code == 200
        review_payload = review.json()

        final = client.post(
            f"/api/office/projects/{project_id}/final",
            json={
                "revision_id": revision_id,
                "review_id": review_payload["review_id"],
                "expected_current_revision_id": revision_id,
            },
        )
        comparison = client.get(f"/api/office/projects/{project_id}/revisions/{revision_id}/comparison")
        final_artifact = client.get(f"/api/office/projects/{project_id}/final/artifact")
        restore = client.post(
            f"/api/office/projects/{project_id}/revisions/{baseline_revision_id}/restore",
            json={"expected_current_revision_id": revision_id},
        )
        assert restore.status_code == 200
        restore_payload = restore.json()
        detail = client.get(f"/api/office/projects/{project_id}")
        stale_restore = client.post(
            f"/api/office/projects/{project_id}/revisions/{baseline_revision_id}/restore",
            json={"expected_current_revision_id": revision_id},
        )

    assert review_payload["status"] == "approved"
    assert review_payload["evidence_ids"] == [evidence_id]
    assert review_payload["page_count"] == 1
    assert final.status_code == 200
    assert final.json()["revision_id"] == revision_id
    assert comparison.status_code == 200
    comparison_payload = comparison.json()
    assert comparison_payload["base_revision"]["revision_id"] == baseline_revision_id
    assert comparison_payload["revision"]["revision_id"] == revision_id
    assert comparison_payload["operation_receipt"]["result"]["sha256"] == hashlib.sha256(result).hexdigest()
    assert comparison_payload["before_render"]["complete"] is False
    assert comparison_payload["after_render"]["complete"] is True
    assert final_artifact.status_code == 200
    assert final_artifact.content == result
    assert restore_payload["restored_from_revision_id"] == baseline_revision_id
    assert restore_payload["parent_revision_id"] == revision_id
    detail_payload = detail.json()
    assert detail_payload["current_revision"]["revision_id"] == restore_payload["revision_id"]
    assert detail_payload["current_revision"]["kind"] == "restore"
    assert detail_payload["final_selection"]["revision_id"] == revision_id
    assert detail_payload["render_set"]["complete"] is False
    assert stale_restore.status_code == 409
    assert "newer current revision" in stale_restore.json()["detail"]


def test_office_project_api_hides_review_after_a_new_complete_render(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "alice")
    store, project_id, revision_id, evidence_id, result = _seed_project("alice")

    with _client() as client:
        review = client.post(
            f"/api/office/projects/{project_id}/revisions/{revision_id}/reviews",
            json={
                "status": "approved",
                "evidence_ids": [evidence_id],
            },
        )
    assert review.status_code == 200
    review_id = review.json()["review_id"]

    first_evidence = store.load_render_evidence(project_id, evidence_id)
    first_manifest = first_evidence["render_manifest"]
    output_dir = "/mnt/user-data/workspace/render-v2"
    second_manifest = {
        **first_manifest,
        "output_dir": output_dir,
        "manifest_path": f"{output_dir}/render-manifest.json",
        "pages": [
            {
                **first_manifest["pages"][0],
                "path": f"{output_dir}/page-001.png",
            }
        ],
    }
    page = RenderedOfficePage(
        page=1,
        filename="page-001.png",
        width=1,
        height=1,
        sha256=hashlib.sha256(_PNG).hexdigest(),
        data=_PNG,
    )
    store = OfficeRevisionStore(
        store.root,
        clock=lambda: datetime(2027, 1, 1, tzinfo=UTC),
    )
    second_evidence = store.commit_render_evidence(
        project_id=project_id,
        revision_id=revision_id,
        source=result,
        suffix=".docx",
        manifest=second_manifest,
        pages=(page,),
        thread_id="thread-office-1",
    )

    with _client() as client:
        project = client.get(f"/api/office/projects/{project_id}")
        revisions = client.get(f"/api/office/projects/{project_id}/revisions")
        detail = client.get(f"/api/office/projects/{project_id}/revisions/{revision_id}")
        stale_final = client.post(
            f"/api/office/projects/{project_id}/final",
            json={
                "revision_id": revision_id,
                "review_id": review_id,
                "expected_current_revision_id": revision_id,
            },
        )

    assert project.status_code == 200
    current = project.json()["current_revision"]
    assert current["latest_review"] is None
    assert current["quality"]["visual_review_status"] == "pending"
    assert project.json()["render_set"]["evidence_ids"] == [second_evidence.evidence_id]
    assert revisions.status_code == 200
    assert revisions.json()["revisions"][0]["latest_review"] is None
    assert detail.status_code == 200
    assert detail.json()["revision"]["latest_review"] is None
    assert stale_final.status_code == 409
    assert "latest complete render evidence" in stale_final.json()["detail"]
