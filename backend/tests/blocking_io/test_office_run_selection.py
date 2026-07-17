"""Regression anchor for Office run-selection filesystem offloading."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.gateway.services as gateway_services

pytestmark = pytest.mark.asyncio


async def test_office_run_selection_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_id = f"ofp_{'1' * 32}"
    revision_id = f"ofr_{'2' * 32}"

    def probe() -> None:
        (tmp_path / "probe").exists()

    class Store:
        def __init__(self, _root: Path) -> None:
            probe()

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
            return {
                "format": "pptx",
                "artifact": {"size_bytes": 4},
            }, b"pptx"

    def resolve(_artifact: bytes, **_kwargs) -> dict:
        probe()
        return {
            "schema": "selection-v1",
            "format": "pptx",
            "object_path": "/slide[1]/shape[@id=3]",
        }

    selection = SimpleNamespace(
        model_dump=lambda: {
            "kind": "pptx_object",
            "project_id": project_id,
            "revision_id": revision_id,
            "source_sha256": "a" * 64,
            "slide_index": 1,
            "object_path": "/slide[1]/shape[@id=3]",
            "object_fingerprint": "b" * 64,
        }
    )
    request = SimpleNamespace(
        state=SimpleNamespace(user=SimpleNamespace(id="alice")),
    )
    monkeypatch.setattr(gateway_services, "OfficeRevisionStore", Store)
    monkeypatch.setattr(gateway_services, "resolve_pptx_selection", resolve)
    monkeypatch.setattr(
        gateway_services,
        "get_paths",
        lambda: SimpleNamespace(user_office_dir=lambda _user_id: tmp_path),
    )

    result = await gateway_services.resolve_office_selection_for_run(
        selection,
        assistant_id="office",
        request=request,
        owner_user_id=None,
    )

    assert result is not None
    assert result["project_id"] == project_id
