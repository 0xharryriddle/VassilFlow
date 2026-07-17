"""Regression anchor for Office Template API filesystem offloading."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.gateway.routers.office_templates as office_templates_router

pytestmark = pytest.mark.asyncio


async def test_list_office_templates_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Store:
        def list_templates(self, *, limit: int) -> list[dict]:
            (tmp_path / "probe").exists()
            assert limit == 20
            return []

    monkeypatch.setattr(
        office_templates_router,
        "get_effective_user_id",
        lambda: "test-user",
    )
    monkeypatch.setattr(
        office_templates_router,
        "_store_for_user",
        lambda _user_id: Store(),
    )

    response = await office_templates_router.list_office_templates(limit=20)

    assert response.templates == []


async def test_instantiate_office_template_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Store:
        root = tmp_path / "office"

    class Service:
        def __init__(self, _template_store, _revision_store) -> None:
            pass

        def instantiate(self, template_id, version, **_kwargs):
            (tmp_path / "probe").exists()
            assert template_id == f"oft_{'1' * 32}"
            assert version == 1
            return SimpleNamespace(
                receipt={
                    "operation_count": 1,
                    "semantic_changes": {"changed_target_count": 1},
                },
                preflight={"summary": {"finding_count": 0}},
                project=SimpleNamespace(
                    project_id=f"ofp_{'2' * 32}",
                    revision_id=f"ofr_{'3' * 32}",
                    baseline_revision_id=f"ofr_{'4' * 32}",
                    artifact_sha256="a" * 64,
                    artifact_size_bytes=123,
                ),
                project_title="Project",
                bound_slot_keys=("headline",),
                omitted_optional_slot_keys=(),
                render_evidence_status="available",
                render_evidence=(SimpleNamespace(evidence_id=f"ofe_{'5' * 32}"),),
            )

    monkeypatch.setattr(
        office_templates_router,
        "get_effective_user_id",
        lambda: "test-user",
    )
    monkeypatch.setattr(
        office_templates_router,
        "_store_for_user",
        lambda _user_id: Store(),
    )
    monkeypatch.setattr(
        office_templates_router,
        "OfficeTemplateInstantiationService",
        Service,
    )

    response = await office_templates_router.instantiate_office_template(
        template_id=f"oft_{'1' * 32}",
        version=1,
        bindings_json=('{"bindings":[{"key":"headline","type":"text","value":"Q4"}]}'),
        title="Project",
        files=None,
    )

    assert response.project_id == f"ofp_{'2' * 32}"
