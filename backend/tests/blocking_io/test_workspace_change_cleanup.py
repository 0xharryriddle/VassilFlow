"""Regression anchors for offloading workspace snapshot cache cleanup.

Both cleanup paths execute from async functions. The strict Blockbuster gate
must fail if recursive deletion is moved back onto the event loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


async def test_capture_snapshot_offloads_cache_cleanup_after_scan_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vassilflow.workspace_changes import recorder

    cache_dir = tmp_path / "snapshot-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(recorder, "build_thread_workspace_roots", lambda _thread_id, user_id=None: [])
    monkeypatch.setattr(recorder.tempfile, "mkdtemp", lambda prefix: str(cache_dir))

    def fail_scan(*_args, **_kwargs):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(recorder, "scan_workspace_roots", fail_scan)

    with pytest.raises(RuntimeError, match="scan failed"):
        await recorder.capture_workspace_snapshot("thread-1")

    assert not cache_dir.exists()


async def test_record_changes_offloads_cache_cleanup_after_scan_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vassilflow.runtime.events.store.memory import MemoryRunEventStore
    from vassilflow.workspace_changes import recorder
    from vassilflow.workspace_changes.types import WorkspaceSnapshot

    cache_dir = tmp_path / "snapshot-cache"
    cache_dir.mkdir()
    before = WorkspaceSnapshot(text_cache_dir=str(cache_dir))
    monkeypatch.setattr(recorder, "build_thread_workspace_roots", lambda _thread_id, user_id=None: [])

    def fail_scan(*_args, **_kwargs):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(recorder, "scan_workspace_roots", fail_scan)

    with pytest.raises(RuntimeError, match="scan failed"):
        await recorder.record_workspace_changes(
            MemoryRunEventStore(),
            "thread-1",
            "run-1",
            before,
        )

    assert not cache_dir.exists()
