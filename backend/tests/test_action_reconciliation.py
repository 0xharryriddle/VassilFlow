"""Tests for evidence-backed repair of stale running Actions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vassilflow.actions import (
    ActionReconciliationDecision,
    ActionRepairService,
    FileActionStore,
)


class _CommittedReconciler:
    key = "test.committed"
    operations = frozenset({"test.commit"})

    def reconcile(self, _action):
        return ActionReconciliationDecision(
            verdict="committed",
            detail_code="test_commit_found",
            status="succeeded",
        )


def test_repair_requires_apply_before_writing_outcome(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 7, 29, 0, 0, tzinfo=UTC)]
    store = FileActionStore(
        tmp_path / "actions",
        owner_user_id="user-1",
        clock=lambda: now[0],
        action_id_factory=lambda: f"act_{'1' * 32}",
    )
    action = store.start(
        operation="test.commit",
        source="user_api",
    )
    now[0] += timedelta(minutes=10)
    service = ActionRepairService(
        store,
        (_CommittedReconciler(),),
        clock=lambda: now[0],
    )

    plan = service.repair(stale_after=timedelta(minutes=5))

    assert plan.deferred_active == 1
    assert plan.repairable == 0
    now[0] += timedelta(minutes=21)
    plan = service.repair(stale_after=timedelta(minutes=5))

    assert plan.repairable == 1
    assert plan.reconciled == 0
    assert store.get(action["action_id"])["status"] == "running"

    applied = service.repair(
        stale_after=timedelta(minutes=5),
        apply=True,
    )

    assert applied.reconciled == 1
    repaired = store.get(action["action_id"])
    assert repaired["status"] == "succeeded"
    assert repaired["metadata"]["reconciled"] is True


@pytest.mark.parametrize("status", ["succeeded", "partial"])
def test_repair_preserves_domain_evidence_and_outcome(tmp_path, status):
    now = [datetime(2026, 7, 29, tzinfo=UTC)]
    store = FileActionStore(tmp_path / "actions", owner_user_id="alice", clock=lambda: now[0])
    action = store.start(operation="sample.commit", source="user_api")
    artifact = {"sha256": "a" * 64, "size_bytes": 20}

    class Reconciler:
        key = "sample.committed"
        operations = frozenset({"sample.commit"})

        def reconcile(self, candidate):
            assert candidate["action_id"] == action["action_id"]
            return ActionReconciliationDecision(
                verdict="committed",
                detail_code="sample_commit_found",
                status=status,
                after_artifact=artifact,
                references=({"kind": "sample.revision", "id": "revision-1", "role": "created"},),
                error={"type": "materialization_unverified", "message": "Working copy was not verified."} if status == "partial" else None,
            )

    now[0] += timedelta(minutes=31)
    report = ActionRepairService(store, (Reconciler(),), clock=lambda: now[0]).repair(apply=True)
    assert report.reconciled == 1
    result = store.get(action["action_id"])
    assert result["status"] == status
    assert result["after_artifact"] == artifact
    assert result["references"] == [{"kind": "sample.revision", "id": "revision-1", "role": "created"}]


def test_repair_without_domain_adapter_keeps_outcome_indeterminate(tmp_path):
    now = [datetime(2026, 7, 29, tzinfo=UTC)]
    store = FileActionStore(tmp_path / "actions", owner_user_id="alice", clock=lambda: now[0])
    action = store.start(operation="sample.commit", source="user_api")
    now[0] += timedelta(minutes=31)

    report = ActionRepairService(store, (), clock=lambda: now[0]).repair(apply=True)

    assert report.indeterminate == 1
    assert report.reconciled == 0
    assert store.get(action["action_id"])["status"] == "running"
