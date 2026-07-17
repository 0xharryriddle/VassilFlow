from __future__ import annotations

import json
from pathlib import Path

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from test_office_templates import _PNG, _TEMPLATE_ID, _pptx, _render_result

import app.gateway.routers.office_templates as office_templates_router
import vassilflow.community.office.instantiation as office_instantiation
from vassilflow.community.office.revisions import OfficeRevisionStore
from vassilflow.community.office.templates import OfficeTemplateStore
from vassilflow.config.paths import get_paths

_RENDER_ID = f"otr_{'2' * 32}"
_PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _client() -> TestClient:
    app = make_authed_test_app()
    app.include_router(office_templates_router.router)
    return TestClient(app)


def test_office_template_api_runs_import_mapping_render_review_and_publish(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = OfficeTemplateStore(
        tmp_path / "office",
        template_id_factory=lambda: _TEMPLATE_ID,
        render_id_factory=lambda: _RENDER_ID,
        renderer=_render_result,
    )
    monkeypatch.setattr(
        office_templates_router,
        "get_effective_user_id",
        lambda: "alice",
    )
    monkeypatch.setattr(
        office_templates_router,
        "_store_for_user",
        lambda _user_id: store,
    )
    monkeypatch.setattr(office_instantiation.office_engine, "render", _render_result)

    with _client() as client:
        imported = client.post(
            "/api/office/templates",
            files={
                "file": (
                    "company-template.pptx",
                    _pptx(),
                    _PPTX_MEDIA_TYPE,
                )
            },
            data={"title": "Quarterly company deck"},
        )
        assert imported.status_code == 201
        imported_payload = imported.json()
        assert imported_payload["template_id"] == _TEMPLATE_ID
        assert imported_payload["status"] == "draft"
        assert imported_payload["active_version"]["slot_candidate_count"] == 2

        version = client.get(f"/api/office/templates/{_TEMPLATE_ID}/versions/1")
        assert version.status_code == 200
        version_payload = version.json()
        text_candidate = next(candidate for candidate in version_payload["slot_candidates"] if candidate["type"] == "text")

        mapped = client.put(
            f"/api/office/templates/{_TEMPLATE_ID}/versions/1/slots",
            json={
                "slots": [
                    {
                        "key": "headline",
                        "label": "Headline",
                        "type": "text",
                        "candidate_id": text_candidate["candidate_id"],
                        "required": True,
                        "max_length": 200,
                    }
                ]
            },
        )
        assert mapped.status_code == 200
        assert mapped.json()["slots"][0]["selector"]["expected_text"] == "Quarterly update"

        rendered = client.post(f"/api/office/templates/{_TEMPLATE_ID}/versions/1/render")
        assert rendered.status_code == 200
        render_payload = rendered.json()["render"]
        assert render_payload["evidence_id"] == _RENDER_ID
        assert render_payload["visual_review_status"] == "pending"
        [preview] = render_payload["preview_pages"]
        assert preview["url"].endswith(f"/{_RENDER_ID}/pages/1")

        preview_response = client.get(preview["url"])
        not_modified = client.get(
            preview["url"],
            headers={"If-None-Match": preview_response.headers["etag"]},
        )
        assert preview_response.status_code == 200
        assert preview_response.content == _PNG
        assert not_modified.status_code == 304

        reviewed = client.post(
            f"/api/office/templates/{_TEMPLATE_ID}/versions/1/renders/{_RENDER_ID}/review",
            json={"status": "reviewed"},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["render"]["visual_review_status"] == "reviewed"
        assert reviewed.json()["render"]["reviewed_by"] == "alice"

        published = client.post(f"/api/office/templates/{_TEMPLATE_ID}/versions/1/publish")
        recent = client.get("/api/office/templates")
        detail = client.get(f"/api/office/templates/{_TEMPLATE_ID}")
        source = client.get(f"/api/office/templates/{_TEMPLATE_ID}/versions/1/source")
        instantiated = client.post(
            f"/api/office/templates/{_TEMPLATE_ID}/versions/1/instantiate",
            data={
                "title": "Q4 customer update",
                "bindings_json": json.dumps(
                    {
                        "bindings": [
                            {
                                "key": "headline",
                                "type": "text",
                                "value": "Q4 customer update",
                            }
                        ]
                    }
                ),
            },
        )

    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert recent.status_code == 200
    [summary] = recent.json()["templates"]
    assert summary["status"] == "published"
    assert summary["published_versions"] == [1]
    assert detail.status_code == 200
    assert detail.json()["draft_version"] is None
    assert source.status_code == 200
    assert source.headers["content-type"] == _PPTX_MEDIA_TYPE
    assert source.content == _pptx()
    assert instantiated.status_code == 201
    instantiation_payload = instantiated.json()
    assert instantiation_payload["template_id"] == _TEMPLATE_ID
    assert instantiation_payload["template_version"] == 1
    assert instantiation_payload["project_title"] == "Q4 customer update"
    assert instantiation_payload["bound_slot_keys"] == ["headline"]
    assert instantiation_payload["render_evidence_status"] == "available"
    revision_store = OfficeRevisionStore(store.root)
    baseline, baseline_bytes = revision_store.read_revision_artifact(
        instantiation_payload["project_id"],
        instantiation_payload["baseline_revision_id"],
    )
    assert baseline_bytes == _pptx()
    assert baseline["resource_versions"]["template"]["version"] == 1
    serialized = json.dumps(detail.json())
    assert str(tmp_path) not in serialized
    assert "drafts" not in serialized
    assert "versions/v000001" not in serialized


def test_office_template_api_is_user_scoped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    OfficeTemplateStore(get_paths().user_office_dir("alice")).import_pptx(
        _pptx(),
        filename="private-template.pptx",
    )
    monkeypatch.setattr(
        office_templates_router,
        "get_effective_user_id",
        lambda: "bob",
    )

    with _client() as client:
        recent = client.get("/api/office/templates")
        detail = client.get(f"/api/office/templates/{_TEMPLATE_ID}")

    assert recent.status_code == 200
    assert recent.json() == {"templates": []}
    assert detail.status_code == 404


def test_office_template_api_rejects_oversized_upload_before_storage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(office_templates_router, "_MAX_UPLOAD_BYTES", 4)
    monkeypatch.setattr(
        office_templates_router,
        "get_effective_user_id",
        lambda: "alice",
    )
    monkeypatch.setattr(
        office_templates_router,
        "_store_for_user",
        lambda _user_id: OfficeTemplateStore(tmp_path / "office"),
    )

    with _client() as client:
        response = client.post(
            "/api/office/templates",
            files={"file": ("large.pptx", b"12345", _PPTX_MEDIA_TYPE)},
        )

    assert response.status_code == 413
    assert not (tmp_path / "office" / "templates").exists()
