"""Tests for direct user Action provenance failure semantics."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.gateway.action_provenance import (
    UserActionHandle,
    finish_user_action,
)
from vassilflow.actions import ActionStoreError, FileActionStore


@pytest.mark.anyio
async def test_terminal_write_failure_leaves_action_running(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = FileActionStore(
        tmp_path / "actions",
        owner_user_id="user-1",
        action_id_factory=lambda: f"act_{'1' * 32}",
    )
    action = store.start(
        operation="sample.restore",
        source="user_api",
    )

    def fail_finish(*_args, **_kwargs):
        raise ActionStoreError("terminal storage unavailable")

    monkeypatch.setattr(store, "finish", fail_finish)
    handle = UserActionHandle(
        action_id=action["action_id"],
        store=store,
    )

    with pytest.raises(HTTPException) as exc_info:
        await finish_user_action(
            handle,
            status="succeeded",
        )

    assert exc_info.value.status_code == 500
    assert "operation may have completed" in exc_info.value.detail
    assert store.get(action["action_id"])["status"] == "running"
