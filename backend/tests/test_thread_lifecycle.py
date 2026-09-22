"""Tests for domain-neutral thread lifecycle fan-out."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vassilflow.runtime.lifecycle_journal import (
    FileThreadLifecycleJournal,
    LifecycleJournalConflictError,
)
from vassilflow.runtime.thread_lifecycle import (
    ThreadBranched,
    ThreadDeleted,
    ThreadLifecycleDispatcher,
    ThreadLifecycleDispatchError,
)


class _FailingHandler:
    key = "test.failing"

    async def on_thread_deleted(self, _event: ThreadDeleted) -> None:
        raise RuntimeError("delete projection failed")

    async def on_thread_branched(self, _event: ThreadBranched) -> None:
        raise RuntimeError("branch projection failed")


class _RecordingHandler:
    key = "test.recording"

    def __init__(self) -> None:
        self.deleted: list[ThreadDeleted] = []
        self.branched: list[ThreadBranched] = []

    async def on_thread_deleted(self, event: ThreadDeleted) -> None:
        self.deleted.append(event)

    async def on_thread_branched(self, event: ThreadBranched) -> None:
        self.branched.append(event)


@pytest.mark.anyio
async def test_delete_dispatch_attempts_handlers_after_a_failure() -> None:
    recorder = _RecordingHandler()
    dispatcher = ThreadLifecycleDispatcher(
        (_FailingHandler(), recorder),
    )
    event = ThreadDeleted(user_id="user-1", thread_id="thread-1")

    with pytest.raises(ThreadLifecycleDispatchError) as exc_info:
        await dispatcher.thread_deleted(event)

    assert recorder.deleted == [event]
    assert exc_info.value.event_name == "thread_deleted"
    assert len(exc_info.value.failures) == 1


@pytest.mark.anyio
async def test_branch_dispatch_attempts_handlers_after_a_failure() -> None:
    recorder = _RecordingHandler()
    dispatcher = ThreadLifecycleDispatcher(
        (_FailingHandler(), recorder),
    )
    event = ThreadBranched(
        user_id="user-1",
        source_thread_id="thread-1",
        target_thread_id="thread-2",
        assistant_id="sample",
        workspace_clone_mode="current_thread_best_effort",
    )

    with pytest.raises(ThreadLifecycleDispatchError) as exc_info:
        await dispatcher.thread_branched(event)

    assert recorder.branched == [event]
    assert exc_info.value.event_name == "thread_branched"
    assert len(exc_info.value.failures) == 1


@pytest.mark.anyio
async def test_durable_retry_skips_completed_handlers(
    tmp_path: Path,
) -> None:
    recorder = _RecordingHandler()
    failing = _FailingHandler()
    journal = FileThreadLifecycleJournal(
        tmp_path / "lifecycle",
        owner_user_id="user-1",
    )
    dispatcher = ThreadLifecycleDispatcher(
        (failing, recorder),
        journal_factory=lambda _user_id: journal,
        running_attempt_lease=timedelta(0),
    )
    event = ThreadDeleted(user_id="user-1", thread_id="thread-1")

    with pytest.raises(ThreadLifecycleDispatchError):
        await dispatcher.thread_deleted(event)
    with pytest.raises(ThreadLifecycleDispatchError):
        await dispatcher.thread_deleted(event)

    assert recorder.deleted == [event]
    operation = journal.list()[0]
    states = {state["handler_key"]: state for state in operation["handler_states"]}
    assert states["test.recording"]["status"] == "succeeded"
    assert states["test.recording"]["attempt_count"] == 1
    assert states["test.failing"]["status"] == "failed"
    assert states["test.failing"]["attempt_count"] == 2


@pytest.mark.anyio
async def test_replay_recovers_stale_running_handler_attempt(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 7, 29, 0, 0, tzinfo=UTC)]
    attempt_ids = iter([f"lca_{'1' * 32}", f"lca_{'2' * 32}"])
    journal = FileThreadLifecycleJournal(
        tmp_path / "lifecycle",
        owner_user_id="user-1",
        clock=lambda: now[0],
        attempt_id_factory=lambda: next(attempt_ids),
    )
    operation = journal.record(
        event_name="thread_deleted",
        payload={"thread_id": "thread-1"},
        handler_keys=["test.recording"],
    )
    journal.begin_attempt(
        operation["operation_id"],
        "test.recording",
        running_lease=timedelta(minutes=5),
    )
    now[0] = datetime(2026, 7, 29, 0, 10, tzinfo=UTC)
    recorder = _RecordingHandler()
    dispatcher = ThreadLifecycleDispatcher(
        (recorder,),
        journal_factory=lambda _user_id: journal,
        running_attempt_lease=timedelta(minutes=5),
    )

    report = await dispatcher.replay_user("user-1")

    assert report.repaired == 1
    assert recorder.deleted == [ThreadDeleted(user_id="user-1", thread_id="thread-1")]
    assert journal.get(operation["operation_id"])["status"] == "succeeded"


@pytest.mark.anyio
async def test_heartbeat_prevents_reclaiming_a_long_running_handler(
    tmp_path: Path,
) -> None:
    class _BlockingHandler:
        key = "test.blocking"

        def __init__(self) -> None:
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def on_thread_deleted(
            self,
            _event: ThreadDeleted,
        ) -> None:
            self.calls += 1
            self.started.set()
            await self.release.wait()

        async def on_thread_branched(
            self,
            _event: ThreadBranched,
        ) -> None:
            return None

    now = [datetime(2026, 7, 29, 0, 0, tzinfo=UTC)]
    journal = FileThreadLifecycleJournal(
        tmp_path / "lifecycle",
        owner_user_id="user-1",
        clock=lambda: now[0],
    )
    handler = _BlockingHandler()
    dispatcher = ThreadLifecycleDispatcher(
        (handler,),
        journal_factory=lambda _user_id: journal,
        running_attempt_lease=timedelta(minutes=5),
        attempt_heartbeat_interval=timedelta(milliseconds=10),
    )
    task = asyncio.create_task(
        dispatcher.thread_deleted(
            ThreadDeleted(
                user_id="user-1",
                thread_id="thread-1",
            )
        )
    )
    await asyncio.wait_for(handler.started.wait(), timeout=1)

    try:
        now[0] += timedelta(minutes=10)
        for _attempt in range(100):
            operation = journal.list()[0]
            attempt = operation["handler_states"][0]["attempts"][0]
            if attempt["lease_renewed_at"] == ("2026-07-29T00:10:00+00:00"):
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("Lifecycle heartbeat did not renew the attempt lease")

        report = await asyncio.wait_for(
            dispatcher.replay_user("user-1"),
            timeout=1,
        )

        assert report.repaired == 0
        assert report.still_pending == 1
        assert handler.calls == 1
        assert attempt["generation"] == 1
        assert attempt["lease_renewed_at"] == ("2026-07-29T00:10:00+00:00")
        assert attempt["lease_expires_at"] == ("2026-07-29T00:15:00+00:00")
    finally:
        handler.release.set()
        await task

    assert journal.list()[0]["status"] == "succeeded"


def test_superseded_attempt_cannot_renew_or_finish(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 7, 29, 0, 0, tzinfo=UTC)]
    attempt_ids = iter(
        [
            f"lca_{'1' * 32}",
            f"lca_{'2' * 32}",
        ]
    )
    journal = FileThreadLifecycleJournal(
        tmp_path / "lifecycle",
        owner_user_id="user-1",
        clock=lambda: now[0],
        attempt_id_factory=lambda: next(attempt_ids),
    )
    operation = journal.record(
        event_name="thread_deleted",
        payload={"thread_id": "thread-1"},
        handler_keys=["test.recording"],
    )
    first_attempt = journal.begin_attempt(
        operation["operation_id"],
        "test.recording",
        running_lease=timedelta(minutes=5),
    )
    assert first_attempt is not None
    now[0] += timedelta(minutes=10)
    second_attempt = journal.begin_attempt(
        operation["operation_id"],
        "test.recording",
        running_lease=timedelta(minutes=5),
    )
    assert second_attempt is not None

    with pytest.raises(
        LifecycleJournalConflictError,
        match="no longer owns",
    ):
        journal.renew_attempt(
            operation["operation_id"],
            "test.recording",
            first_attempt,
            lease_duration=timedelta(minutes=5),
        )
    with pytest.raises(
        LifecycleJournalConflictError,
        match="superseded",
    ):
        journal.finish_attempt(
            operation["operation_id"],
            "test.recording",
            first_attempt,
            succeeded=True,
        )

    journal.finish_attempt(
        operation["operation_id"],
        "test.recording",
        second_attempt,
        succeeded=True,
    )

    restored = journal.get(operation["operation_id"])
    assert restored["status"] == "succeeded"
    assert [attempt["generation"] for attempt in restored["handler_states"][0]["attempts"]] == [1, 2]


@pytest.mark.anyio
async def test_retry_completes_an_idempotent_partial_handler(
    tmp_path: Path,
) -> None:
    class _PartialHandler:
        key = "test.partial"

        def __init__(self) -> None:
            self.resources: list[str] = []
            self.calls = 0

        async def on_thread_deleted(
            self,
            _event: ThreadDeleted,
        ) -> None:
            self.calls += 1
            for resource in ("project-1", "project-2"):
                if resource not in self.resources:
                    self.resources.append(resource)
                if self.calls == 1 and resource == "project-1":
                    raise RuntimeError("interrupted after one resource")

        async def on_thread_branched(
            self,
            _event: ThreadBranched,
        ) -> None:
            return None

    journal = FileThreadLifecycleJournal(
        tmp_path / "lifecycle",
        owner_user_id="user-1",
    )
    handler = _PartialHandler()
    dispatcher = ThreadLifecycleDispatcher(
        (handler,),
        journal_factory=lambda _user_id: journal,
        running_attempt_lease=timedelta(0),
    )
    event = ThreadDeleted(user_id="user-1", thread_id="thread-1")

    with pytest.raises(ThreadLifecycleDispatchError):
        await dispatcher.thread_deleted(event)
    report = await dispatcher.replay_user("user-1")

    assert report.repaired == 1
    assert handler.calls == 2
    assert handler.resources == ["project-1", "project-2"]


@pytest.mark.anyio
async def test_prepared_source_intent_is_visible_but_not_replayed(
    tmp_path: Path,
) -> None:
    journal = FileThreadLifecycleJournal(
        tmp_path / "lifecycle",
        owner_user_id="user-1",
    )
    operation = journal.prepare(
        event_name="thread_deleted",
        payload={"thread_id": "thread-1"},
        handler_keys=["test.recording"],
    )
    recorder = _RecordingHandler()
    dispatcher = ThreadLifecycleDispatcher(
        (recorder,),
        journal_factory=lambda _user_id: journal,
    )

    report = await dispatcher.replay_user("user-1")

    assert report.awaiting_source == 1
    assert report.still_pending == 1
    assert recorder.deleted == []

    journal.abort_source(
        operation["operation_id"],
        error_type="RuntimeError",
    )
    assert journal.list(unfinished_only=True) == []


def test_legacy_event_without_source_markers_remains_replayable(
    tmp_path: Path,
) -> None:
    journal = FileThreadLifecycleJournal(
        tmp_path / "lifecycle",
        owner_user_id="user-1",
    )
    operation = journal.record(
        event_name="thread_deleted",
        payload={"thread_id": "thread-legacy"},
        handler_keys=["test.recording"],
    )
    operation_dir = tmp_path / "lifecycle" / operation["operation_id"]
    (operation_dir / "source_prepared.json").unlink()
    (operation_dir / "source_committed.json").unlink()

    restored = journal.get(operation["operation_id"])

    assert restored["source_status"] == "committed"
    assert restored["status"] == "pending"


@pytest.mark.anyio
async def test_replay_limit_reports_remaining_operations(
    tmp_path: Path,
) -> None:
    journal = FileThreadLifecycleJournal(
        tmp_path / "lifecycle",
        owner_user_id="user-1",
    )
    for index in range(3):
        journal.record(
            event_name="thread_deleted",
            payload={"thread_id": f"thread-{index}"},
            handler_keys=["test.recording"],
        )
    recorder = _RecordingHandler()
    dispatcher = ThreadLifecycleDispatcher(
        (recorder,),
        journal_factory=lambda _user_id: journal,
    )

    first = await dispatcher.replay_user("user-1", limit=2)

    assert first.scanned == 2
    assert first.pending == 3
    assert first.repaired == 2
    assert first.still_pending == 1
    assert first.limit_reached is True

    second = await dispatcher.replay_user("user-1", limit=2)

    assert second.repaired == 1
    assert second.still_pending == 0
    assert second.limit_reached is False


@pytest.mark.anyio
async def test_branch_commit_persists_observed_clone_mode_and_time(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 7, 29, 7, 0, tzinfo=UTC)]
    journal = FileThreadLifecycleJournal(
        tmp_path / "lifecycle",
        owner_user_id="user-1",
        clock=lambda: now[0],
    )
    recorder = _RecordingHandler()
    dispatcher = ThreadLifecycleDispatcher(
        (recorder,),
        journal_factory=lambda _user_id: journal,
    )
    prepared = ThreadBranched(
        user_id="user-1",
        source_thread_id="thread-1",
        target_thread_id="thread-2",
        assistant_id="sample",
        workspace_clone_mode="pending",
    )
    intent = await dispatcher.prepare_thread_branched(prepared)
    now[0] += timedelta(seconds=2)

    await dispatcher.commit_thread_branched(
        intent,
        ThreadBranched(
            user_id="user-1",
            source_thread_id="thread-1",
            target_thread_id="thread-2",
            assistant_id="sample",
            workspace_clone_mode="current_thread_best_effort",
        ),
    )

    [event] = recorder.branched
    assert event.workspace_clone_mode == "current_thread_best_effort"
    assert event.recorded_at == "2026-07-29T07:00:02+00:00"
