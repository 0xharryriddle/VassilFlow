from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from vassilflow.community.office.errors import OfficeOperationError
from vassilflow.community.office.selection import (
    PPTX_SELECTION_SCHEMA,
    build_pptx_selection_surface,
    resolve_pptx_selection,
)

_CORPUS = Path(__file__).parent / "fixtures" / "office" / "pptx" / "roundtrip" / "seed-v1.pptx"


def _presentation() -> bytes:
    return _CORPUS.read_bytes()


def test_pptx_selection_surface_uses_stable_objects_and_preview_geometry() -> None:
    document = _presentation()

    first = build_pptx_selection_surface(document, slide_index=1)
    second = build_pptx_selection_surface(document, slide_index=1)

    assert first == second
    assert first["schema"] == PPTX_SELECTION_SCHEMA
    assert first["source_sha256"] == hashlib.sha256(document).hexdigest()
    assert first["slide"] == {
        "index": 1,
        "path": "/slide[1]",
        "title": None,
        "width_emu": 12191999,
        "height_emu": 6858000,
    }
    assert first["object_count"] == 6
    assert first["objects_returned"] == 6
    assert first["objects_truncated"] is False

    split_run = next(item for item in first["objects"] if item["path"] == "/slide[1]/shape[@id=3]")
    assert split_run["identity_source"] == "cNvPr.id"
    assert split_run["selection_status"] == "selectable"
    assert split_run["text_preview"] == "AlphaBeta"
    assert split_run["text_truncated"] is False
    assert split_run["allowed_operations"] == [
        "replace_pptx_text",
        "format_pptx_runs",
        "format_pptx_paragraphs",
        "format_pptx_shapes",
        "format_pptx_lines",
    ]
    assert split_run["overlay"] == {
        "left_percent": 6.0,
        "top_percent": 19.333333,
        "width_percent": 42.750004,
        "height_percent": 14.666667,
    }
    assert len(split_run["object_fingerprint"]) == 64


def test_pptx_selection_resolver_returns_bounded_formatting_context() -> None:
    document = _presentation()
    surface = build_pptx_selection_surface(document, slide_index=1)
    selected = next(item for item in surface["objects"] if item["path"] == "/slide[1]/shape[@id=3]")

    resolved = resolve_pptx_selection(
        document,
        slide_index=1,
        source_sha256=surface["source_sha256"],
        object_path=selected["path"],
        object_fingerprint=selected["object_fingerprint"],
    )

    assert resolved["object_path"] == selected["path"]
    assert resolved["source_sha256"] == surface["source_sha256"]
    assert resolved["allowed_operations"] == selected["allowed_operations"]
    assert resolved["object"]["path"] == selected["path"]
    assert resolved["object"]["text_body"]["paragraphs"][0]["text"] == "AlphaBeta"
    assert [segment["text"] for segment in resolved["object"]["text_body"]["paragraphs"][0]["segments"]] == ["Alpha", "Beta"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha256", "0" * 64),
        ("object_fingerprint", "0" * 64),
        ("object_path", "/slide[1]/shape[@id=999]"),
    ],
)
def test_pptx_selection_resolver_rejects_stale_or_spoofed_identity(
    field: str,
    value: str,
) -> None:
    document = _presentation()
    surface = build_pptx_selection_surface(document, slide_index=1)
    selected = surface["objects"][0]
    request = {
        "slide_index": 1,
        "source_sha256": surface["source_sha256"],
        "object_path": selected["path"],
        "object_fingerprint": selected["object_fingerprint"],
    }
    request[field] = value

    with pytest.raises(OfficeOperationError):
        resolve_pptx_selection(document, **request)


def test_pptx_selection_rejects_missing_slide() -> None:
    with pytest.raises(OfficeOperationError, match="slide was not found"):
        build_pptx_selection_surface(_presentation(), slide_index=14)
