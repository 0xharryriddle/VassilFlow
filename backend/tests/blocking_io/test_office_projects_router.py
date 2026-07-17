"""Regression anchor for Office Project API filesystem offloading."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.gateway.routers.office_projects as office_projects_router

pytestmark = pytest.mark.asyncio


async def test_list_office_projects_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    class Store:
        def list_project_snapshots(self, *, limit: int) -> list[tuple[dict, dict]]:
            (tmp_path / "probe").exists()
            assert limit == 20
            return []

    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "test-user")
    monkeypatch.setattr(office_projects_router, "_store_for_user", lambda _user_id: Store())

    response = await office_projects_router.list_office_projects(limit=20)

    assert response.projects == []


async def test_office_pptx_selection_surface_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_id = f"ofp_{'1' * 32}"
    revision_id = f"ofr_{'2' * 32}"

    def probe() -> None:
        (tmp_path / "probe").exists()

    class Store:
        def load_project(self, _project_id: str) -> dict:
            probe()
            return {
                "format": "pptx",
                "current_revision_id": revision_id,
            }

        def read_revision_artifact(
            self,
            _project_id: str,
            _revision_id: str,
        ) -> tuple[dict, bytes]:
            probe()
            return {"format": "pptx"}, b"pptx"

    surface = {
        "schema": "vassilflow.office.pptx_object_selection.v1",
        "format": "pptx",
        "source_sha256": "a" * 64,
        "slide": {
            "index": 1,
            "path": "/slide[1]",
            "title": None,
            "width_emu": 100,
            "height_emu": 100,
        },
        "object_count": 0,
        "objects_returned": 0,
        "objects_truncated": False,
        "objects": [],
    }
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "test-user")
    monkeypatch.setattr(office_projects_router, "_store_for_user", lambda _user_id: Store())

    def build(_artifact: bytes, *, slide_index: int) -> dict:
        probe()
        assert slide_index == 1
        return surface

    monkeypatch.setattr(
        office_projects_router,
        "build_pptx_selection_surface",
        build,
    )

    response = await office_projects_router.get_office_pptx_selection_surface(
        project_id,
        revision_id,
        slide=1,
    )

    assert response.project_id == project_id
    assert response.revision_id == revision_id
    assert response.is_current is True


async def test_office_project_write_workflows_run_outside_event_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_id = f"ofp_{'1' * 32}"
    revision_id = f"ofr_{'2' * 32}"
    target_revision_id = f"ofr_{'3' * 32}"
    review_id = f"ofv_{'4' * 32}"
    selection_id = f"ofs_{'5' * 32}"
    artifact = {"sha256": "a" * 64, "size_bytes": 10}

    def probe() -> None:
        (tmp_path / "probe").exists()

    class Workflow:
        def render_revision(self, _project_id: str, _revision_id: str) -> None:
            probe()

        def restore_revision(self, _project_id: str, _target_revision_id: str, **_kwargs):
            probe()
            return SimpleNamespace(
                project=SimpleNamespace(
                    project_id=project_id,
                    revision_id=revision_id,
                    parent_revision_id=target_revision_id,
                    sequence=3,
                    artifact_sha256=artifact["sha256"],
                    artifact_size_bytes=artifact["size_bytes"],
                ),
                restored_from_revision_id=target_revision_id,
            )

    review_record = {
        "review_id": review_id,
        "revision_id": revision_id,
        "created_at": "2026-07-17T00:00:00Z",
        "status": "approved",
        "note": None,
        "render_set": {
            "evidence_ids": [f"ofe_{'6' * 32}"],
            "page_count": 1,
            "sha256": "b" * 64,
        },
    }
    final_record = {
        "selection_id": selection_id,
        "revision_id": revision_id,
        "review_id": review_id,
        "created_at": "2026-07-17T00:00:00Z",
        "artifact": artifact,
    }

    class Store:
        def commit_project_review(self, **_kwargs):
            probe()
            return SimpleNamespace(review_id=review_id)

        def load_project_review(self, _project_id: str, _review_id: str):
            probe()
            return review_record

        def commit_final_selection(self, **_kwargs) -> None:
            probe()

        def load_final_selection(self, _project_id: str):
            probe()
            return final_record

    render_set = office_projects_router.OfficeRenderSetResponse(
        complete=True,
        page_count=1,
        rendered_page_count=1,
        evidence_ids=[f"ofe_{'6' * 32}"],
        evidence=[],
    )
    monkeypatch.setattr(office_projects_router, "get_effective_user_id", lambda: "test-user")
    monkeypatch.setattr(office_projects_router, "_workflow_for_user", lambda _user_id: Workflow())
    monkeypatch.setattr(office_projects_router, "_store_for_user", lambda _user_id: Store())
    monkeypatch.setattr(office_projects_router, "_render_set_response", lambda *_args: render_set)

    rendered = await office_projects_router.render_office_project_revision(
        project_id,
        revision_id,
    )
    reviewed = await office_projects_router.review_office_project_revision(
        project_id,
        revision_id,
        office_projects_router.OfficeProjectReviewRequest(
            status="approved",
            evidence_ids=[f"ofe_{'6' * 32}"],
        ),
    )
    selected = await office_projects_router.select_office_project_final(
        project_id,
        office_projects_router.OfficeFinalSelectionRequest(
            revision_id=revision_id,
            review_id=review_id,
            expected_current_revision_id=revision_id,
        ),
    )
    restored = await office_projects_router.restore_office_project_revision(
        project_id,
        target_revision_id,
        office_projects_router.OfficeRestoreRequest(
            expected_current_revision_id=revision_id,
        ),
    )

    assert rendered.complete is True
    assert reviewed.review_id == review_id
    assert selected.selection_id == selection_id
    assert restored.restored_from_revision_id == target_revision_id
