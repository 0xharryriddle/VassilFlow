"""Core behavior tests for present_files path normalization."""

import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

present_file_tool_module = importlib.import_module("vassilflow.tools.builtins.present_file_tool")


def _make_runtime(outputs_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        state={"thread_data": {"outputs_path": outputs_path}},
        context={"thread_id": "thread-1"},
        config={},
    )


def _make_office_runtime(tmp_path: Path, *, vision: bool, reviewed: dict[str, str] | None = None) -> tuple[SimpleNamespace, Path, Path]:
    user_data = tmp_path / "threads" / "thread-1" / "user-data"
    workspace_dir = user_data / "workspace"
    outputs_dir = user_data / "outputs"
    workspace_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)
    office_path = outputs_dir / "deck.pptx"
    office_path.write_bytes(b"current-office-output")
    runtime = SimpleNamespace(
        state={
            "thread_data": {
                "workspace_path": str(workspace_dir),
                "outputs_path": str(outputs_dir),
            },
            "visual_reviewed_images": reviewed or {},
        },
        context={"thread_id": "thread-1"},
        config={},
        tools=[SimpleNamespace(name="view_image")] if vision else [],
    )
    return runtime, office_path, outputs_dir


def _write_render_manifest(
    outputs_dir: Path,
    office_path: Path,
    *,
    page_count: int = 1,
    pages: list[int] | None = None,
    review_status: str = "pending",
) -> dict[str, str]:
    render_dir = outputs_dir / "deck-render"
    render_dir.mkdir()
    page_hashes: dict[str, str] = {}
    records = []
    for page in pages or [1]:
        page_path = render_dir / f"page-{page:03d}.png"
        page_bytes = f"page-{page}".encode()
        page_path.write_bytes(page_bytes)
        virtual_path = f"/mnt/user-data/outputs/deck-render/{page_path.name}"
        page_sha256 = hashlib.sha256(page_bytes).hexdigest()
        page_hashes[virtual_path] = page_sha256
        records.append({"page": page, "path": virtual_path, "sha256": page_sha256})
    manifest = {
        "complete": True,
        "format": "pptx",
        "source_path": "/mnt/user-data/outputs/deck.pptx",
        "source_sha256": hashlib.sha256(office_path.read_bytes()).hexdigest(),
        "page_count": page_count,
        "pages": records,
        "visual_review_status": review_status,
        "gateway_page_access": "available",
    }
    (render_dir / "render-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return page_hashes


def test_present_files_normalizes_host_outputs_path(tmp_path):
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    outputs_dir.mkdir(parents=True)
    artifact_path = outputs_dir / "report.md"
    artifact_path.write_text("ok")

    result = present_file_tool_module.present_file_tool.func(
        runtime=_make_runtime(str(outputs_dir)),
        filepaths=[str(artifact_path)],
        tool_call_id="tc-1",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/report.md"]
    assert result.update["messages"][0].content == "Successfully presented files"


def test_present_files_keeps_virtual_outputs_path(tmp_path, monkeypatch):
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    outputs_dir.mkdir(parents=True)
    artifact_path = outputs_dir / "summary.json"
    artifact_path.write_text("{}")

    monkeypatch.setattr(
        present_file_tool_module,
        "get_paths",
        lambda: SimpleNamespace(resolve_virtual_path=lambda thread_id, path, *, user_id=None: artifact_path),
    )

    result = present_file_tool_module.present_file_tool.func(
        runtime=_make_runtime(str(outputs_dir)),
        filepaths=["/mnt/user-data/outputs/summary.json"],
        tool_call_id="tc-2",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/summary.json"]


def test_present_files_uses_config_thread_id_when_context_missing(tmp_path, monkeypatch):
    outputs_dir = tmp_path / "threads" / "thread-from-config" / "user-data" / "outputs"
    outputs_dir.mkdir(parents=True)
    artifact_path = outputs_dir / "summary.json"
    artifact_path.write_text("{}")

    monkeypatch.setattr(
        present_file_tool_module,
        "get_paths",
        lambda: SimpleNamespace(resolve_virtual_path=lambda thread_id, path: artifact_path),
    )

    runtime = SimpleNamespace(
        state={"thread_data": {"outputs_path": str(outputs_dir)}},
        context={},
        config={"configurable": {"thread_id": "thread-from-config"}},
    )

    result = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=["/mnt/user-data/outputs/summary.json"],
        tool_call_id="tc-config",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/summary.json"]
    assert result.update["messages"][0].content == "Successfully presented files"


def test_present_files_rejects_paths_outside_outputs(tmp_path):
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    workspace_dir = tmp_path / "threads" / "thread-1" / "user-data" / "workspace"
    outputs_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    leaked_path = workspace_dir / "notes.txt"
    leaked_path.write_text("leak")

    result = present_file_tool_module.present_file_tool.func(
        runtime=_make_runtime(str(outputs_dir)),
        filepaths=[str(leaked_path)],
        tool_call_id="tc-3",
    )

    assert "artifacts" not in result.update
    assert result.update["messages"][0].content == f"Error: Only files in /mnt/user-data/outputs can be presented: {leaked_path}"


def test_present_files_requires_current_complete_office_render(tmp_path):
    runtime, office_path, _ = _make_office_runtime(tmp_path, vision=True)

    result = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=[str(office_path)],
        tool_call_id="tc-office-render",
    )

    assert "artifacts" not in result.update
    assert "Render the complete Office output" in result.update["messages"][0].content


def test_present_files_blocks_vision_model_until_every_page_was_reviewed(tmp_path):
    runtime, office_path, outputs_dir = _make_office_runtime(tmp_path, vision=True)
    page_hashes = _write_render_manifest(outputs_dir, office_path)

    blocked = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=[str(office_path)],
        tool_call_id="tc-office-pending",
    )
    assert "artifacts" not in blocked.update
    assert "Call view_image for every rendered page in a prior model step" in blocked.update["messages"][0].content

    runtime.state["visual_reviewed_images"] = page_hashes
    presented = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=[str(office_path)],
        tool_call_id="tc-office-reviewed",
    )
    assert presented.update["artifacts"] == ["/mnt/user-data/outputs/deck.pptx"]
    assert presented.update["messages"][0].content == "Successfully presented files"


def test_present_files_rejects_stale_visual_review_hash(tmp_path):
    runtime, office_path, outputs_dir = _make_office_runtime(
        tmp_path,
        vision=True,
        reviewed={"/mnt/user-data/outputs/deck-render/page-001.png": "0" * 64},
    )
    _write_render_manifest(outputs_dir, office_path)

    result = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=[str(office_path)],
        tool_call_id="tc-office-stale-review",
    )

    assert "artifacts" not in result.update
    assert "Visual review is incomplete" in result.update["messages"][0].content


def test_present_files_allows_external_review_with_explicit_warning(tmp_path):
    runtime, office_path, outputs_dir = _make_office_runtime(tmp_path, vision=False)
    _write_render_manifest(outputs_dir, office_path, review_status="external_review_required")

    result = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=[str(office_path)],
        tool_call_id="tc-office-external",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/deck.pptx"]
    message = result.update["messages"][0].content
    assert "visual_review_status=external_review_required" in message
    assert "do not claim that visual QA passed" in message


def test_present_files_rejects_incomplete_office_page_coverage(tmp_path):
    runtime, office_path, outputs_dir = _make_office_runtime(tmp_path, vision=False)
    _write_render_manifest(outputs_dir, office_path, page_count=2, pages=[1], review_status="external_review_required")

    result = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=[str(office_path)],
        tool_call_id="tc-office-incomplete",
    )

    assert "artifacts" not in result.update
    assert "render missing pages 2" in result.update["messages"][0].content
