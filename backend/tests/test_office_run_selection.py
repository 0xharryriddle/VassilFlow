from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.gateway.office_selection import OfficePptxObjectSelectionInput
from app.gateway.services import resolve_office_selection_for_run
from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.models import PptxTextReplacement
from vassilflow.community.office.revisions import OfficeRevisionStore
from vassilflow.community.office.selection import build_pptx_selection_surface
from vassilflow.config.paths import get_paths

_CORPUS = Path(__file__).parent / "fixtures" / "office" / "pptx" / "roundtrip" / "seed-v1.pptx"


def _seed_project(
    user_id: str,
) -> tuple[str, str, str, bytes, bytes]:
    source = _CORPUS.read_bytes()
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
    commit = store.commit_edit(
        source=source,
        result=result,
        suffix=".pptx",
        source_path="/mnt/user-data/uploads/source.pptx",
        output_path="/mnt/user-data/outputs/result.pptx",
        thread_id="thread-office-selection",
        receipt=receipt,
        source_validation=office_engine.validate(source, suffix=".pptx"),
        result_validation=office_engine.validate(result, suffix=".pptx"),
    )
    baseline_revision_id = store.list_revisions(commit.project_id)[-1]["revision_id"]
    return commit.project_id, commit.revision_id, baseline_revision_id, source, result


def _input(
    *,
    project_id: str,
    revision_id: str,
    document: bytes,
) -> OfficePptxObjectSelectionInput:
    surface = build_pptx_selection_surface(document, slide_index=1)
    selected = next(item for item in surface["objects"] if item["path"] == "/slide[1]/shape[@id=3]")
    return OfficePptxObjectSelectionInput(
        project_id=project_id,
        revision_id=revision_id,
        source_sha256=surface["source_sha256"],
        slide_index=1,
        object_path=selected["path"],
        object_fingerprint=selected["object_fingerprint"],
    )


def _request(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id=user_id)))


def test_office_run_selection_resolves_current_user_scoped_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    project_id, revision_id, _baseline_revision_id, _source, result = _seed_project("alice")

    resolved = asyncio.run(
        resolve_office_selection_for_run(
            _input(
                project_id=project_id,
                revision_id=revision_id,
                document=result,
            ),
            assistant_id="office",
            request=_request("alice"),
            owner_user_id=None,
        )
    )

    assert resolved is not None
    assert resolved["project_id"] == project_id
    assert resolved["revision_id"] == revision_id
    assert resolved["object_path"] == "/slide[1]/shape[@id=3]"
    assert resolved["object"]["text_body"]["paragraphs"][0]["text"] == "AlphaBeta"


def test_office_run_selection_is_user_scoped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    project_id, revision_id, _baseline_revision_id, _source, result = _seed_project("alice")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            resolve_office_selection_for_run(
                _input(
                    project_id=project_id,
                    revision_id=revision_id,
                    document=result,
                ),
                assistant_id="office",
                request=_request("bob"),
                owner_user_id=None,
            )
        )

    assert exc_info.value.status_code == 404


def test_office_run_selection_rejects_historical_revision_for_editing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VASSILFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("vassilflow.config.paths._paths", None)
    project_id, _revision_id, baseline_revision_id, source, _result = _seed_project("alice")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            resolve_office_selection_for_run(
                _input(
                    project_id=project_id,
                    revision_id=baseline_revision_id,
                    document=source,
                ),
                assistant_id="office",
                request=_request("alice"),
                owner_user_id=None,
            )
        )

    assert exc_info.value.status_code == 409
    assert "current project revision" in exc_info.value.detail


def test_office_run_selection_requires_office_agent() -> None:
    selection = OfficePptxObjectSelectionInput(
        project_id=f"ofp_{'1' * 32}",
        revision_id=f"ofr_{'2' * 32}",
        source_sha256="a" * 64,
        slide_index=1,
        object_path="/slide[1]/shape[@id=3]",
        object_fingerprint="b" * 64,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            resolve_office_selection_for_run(
                selection,
                assistant_id="lead_agent",
                request=_request("alice"),
                owner_user_id=None,
            )
        )

    assert exc_info.value.status_code == 400
