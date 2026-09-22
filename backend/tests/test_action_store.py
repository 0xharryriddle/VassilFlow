from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vassilflow.actions import (
    ACTION_SCHEMA,
    ActionConflictError,
    ActionIntegrityError,
    ActionStoreError,
    FileActionStore,
)

_ACTION_ID = f"act_{'1' * 32}"
_SECOND_ACTION_ID = f"act_{'2' * 32}"


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def test_action_store_persists_running_and_terminal_projections(tmp_path: Path) -> None:
    store = FileActionStore(
        tmp_path / "actions",
        owner_user_id="alice",
        action_id_factory=lambda: _ACTION_ID,
        clock=_Clock(),
    )

    running = store.start(
        operation="sample.edit",
        source="agent_run",
        assistant_id="sample",
        thread_id="thread-1",
        run_id="run-1",
        references=[
            {"kind": "sample.project", "id": "opj_1", "role": "target"},
        ],
        metadata={"operation_count": 2},
    )

    assert running["schema"] == ACTION_SCHEMA
    assert running["status"] == "running"
    assert running["completed_at"] is None
    assert store.get(_ACTION_ID) == running

    succeeded = store.finish(
        _ACTION_ID,
        status="succeeded",
        references=[
            {"kind": "sample.project", "id": "opj_1", "role": "target"},
            {"kind": "sample.revision", "id": "orv_2", "role": "created"},
        ],
        before_artifact={"sha256": "a" * 64, "size_bytes": 10},
        after_artifact={"sha256": "b" * 64, "size_bytes": 12},
        evidence=[
            {"kind": "sample.revision", "id": "orv_2", "role": "receipt"},
        ],
        metadata={"changed_target_count": 1},
    )

    assert succeeded["status"] == "succeeded"
    assert succeeded["run_id"] == "run-1"
    assert succeeded["metadata"] == {
        "operation_count": 2,
        "changed_target_count": 1,
    }
    assert store.get(_ACTION_ID) == succeeded


def test_action_store_finish_is_idempotent_but_never_replaces_outcome(
    tmp_path: Path,
) -> None:
    store = FileActionStore(
        tmp_path / "actions",
        owner_user_id="alice",
        action_id_factory=lambda: _ACTION_ID,
        clock=_Clock(),
    )
    store.start(operation="sample.project.review", source="user_api")
    first = store.finish(
        _ACTION_ID,
        status="rejected",
        error={"type": "SampleRevisionConflictError", "message": "Review is stale."},
    )
    repeated = store.finish(
        _ACTION_ID,
        status="rejected",
        error={"type": "SampleRevisionConflictError", "message": "Review is stale."},
    )

    assert repeated == first
    with pytest.raises(ActionConflictError):
        store.finish(_ACTION_ID, status="succeeded")


def test_action_store_enforces_source_identity_and_failure_error(
    tmp_path: Path,
) -> None:
    store = FileActionStore(tmp_path / "actions", owner_user_id="alice")

    with pytest.raises(ActionStoreError, match="identity is incomplete"):
        store.start(operation="sample.edit", source="agent_run")
    with pytest.raises(ActionStoreError, match="cannot claim Agent run identity"):
        store.start(
            operation="sample.project.render",
            source="user_api",
            thread_id="not-a-real-run",
        )

    action = store.start(operation="sample.project.render", source="user_api")
    with pytest.raises(ActionStoreError, match="requires an error"):
        store.finish(action["action_id"], status="failed")


def test_action_store_lists_by_operation_and_resource(tmp_path: Path) -> None:
    action_ids = iter((_ACTION_ID, _SECOND_ACTION_ID))
    store = FileActionStore(
        tmp_path / "actions",
        owner_user_id="alice",
        action_id_factory=lambda: next(action_ids),
        clock=_Clock(),
    )
    first = store.start(
        operation="sample.edit",
        source="user_api",
        references=[{"kind": "sample.project", "id": "opj_1"}],
    )
    second = store.start(
        operation="sample.project.render",
        source="user_api",
        references=[{"kind": "sample.project", "id": "opj_2"}],
    )

    assert [item["action_id"] for item in store.list()] == [
        second["action_id"],
        first["action_id"],
    ]
    assert [item["action_id"] for item in store.list(operation="sample.edit")] == [first["action_id"]]
    assert [
        item["action_id"]
        for item in store.list(
            resource_kind="sample.project",
            resource_id="opj_2",
        )
    ] == [second["action_id"]]


def test_action_store_rejects_tampered_owner_and_symlinked_action(
    tmp_path: Path,
    symlink_or_skip,
) -> None:
    store = FileActionStore(
        tmp_path / "actions",
        owner_user_id="alice",
        action_id_factory=lambda: _ACTION_ID,
    )
    store.start(operation="sample.edit", source="user_api")
    started_path = tmp_path / "actions" / _ACTION_ID / "started.json"
    payload = json.loads(started_path.read_text(encoding="utf-8"))
    payload["owner_user_id"] = "bob"
    started_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ActionIntegrityError, match="owner"):
        store.get(_ACTION_ID)

    other = tmp_path / "other"
    other.mkdir()
    symlink_path = tmp_path / "actions" / _SECOND_ACTION_ID
    symlink_or_skip(symlink_path, other, target_is_directory=True)
    with pytest.raises(ActionIntegrityError, match="unsafe"):
        store.get(_SECOND_ACTION_ID)


def test_action_repair_claim_waits_for_renewable_worker_lease(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 7, 29, 8, 0, tzinfo=UTC)]
    claim_id = f"arc_{'3' * 32}"
    store = FileActionStore(
        tmp_path / "actions",
        owner_user_id="alice",
        action_id_factory=lambda: _ACTION_ID,
        lease_id_factory=lambda: f"acl_{'2' * 32}",
        repair_claim_id_factory=lambda: claim_id,
        clock=lambda: now[0],
        lease_duration=timedelta(minutes=5),
    )
    store.start(operation="sample.edit", source="user_api")

    assert store.reconciliation_state(_ACTION_ID) == "active"
    assert store.claim_reconciliation(_ACTION_ID) is None

    now[0] += timedelta(minutes=4)
    renewed = store.renew(_ACTION_ID)
    assert renewed["expires_at"] == "2026-07-29T08:09:00+00:00"

    now[0] += timedelta(minutes=6)
    assert store.reconciliation_state(_ACTION_ID) == "eligible"
    assert store.claim_reconciliation(_ACTION_ID) == claim_id
    assert store.reconciliation_state(_ACTION_ID) == "claimed"

    with pytest.raises(ActionConflictError, match="owned by repair"):
        store.finish(_ACTION_ID, status="succeeded")

    repaired = store.finish_reconciliation(
        _ACTION_ID,
        claim_id,
        status="succeeded",
        metadata={"reconciled": True},
    )

    assert repaired["status"] == "succeeded"
    assert not (tmp_path / "actions" / _ACTION_ID / "lease.json").exists()
    assert not (tmp_path / "actions" / _ACTION_ID / "repair_claim.json").exists()
