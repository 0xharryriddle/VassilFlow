"""Deterministic timer and worker handoff regressions, without timer threads."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vassilflow.agents.memory import queue as queue_module
from vassilflow.agents.memory.queue import MemoryUpdateQueue
from vassilflow.config.memory_config import MemoryConfig


class _Timer:
    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.cancelled = False
        self.started = False
        self.daemon = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        # Deliberately also permit canceled timers: cancel() cannot stop a
        # callback that was already dispatched and is waiting for the lock.
        self.function(*self.args, **self.kwargs)


@pytest.fixture
def scheduled_queue(monkeypatch):
    state = SimpleNamespace(queue=MemoryUpdateQueue(), now=100.0, timers=[], updater=MagicMock())
    state.updater.update_memory.return_value = True

    def timer(*args, **kwargs):
        instance = _Timer(*args, **kwargs)
        state.timers.append(instance)
        return instance

    monkeypatch.setattr(queue_module, "get_memory_config", lambda: MemoryConfig(enabled=True, debounce_seconds=10))
    monkeypatch.setattr(queue_module.threading, "Timer", timer)
    monkeypatch.setattr(queue_module.time, "monotonic", lambda: state.now)
    monkeypatch.setattr(queue_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr("vassilflow.agents.memory.updater.MemoryUpdater", lambda: state.updater)
    return state


@pytest.mark.parametrize("finish_time,expected_delay", [(112.0, 7.0), (125.0, 0.0)])
def test_worker_handoff_preserves_latest_debounce_deadline(scheduled_queue, finish_time, expected_delay):
    state = scheduled_queue
    queue = state.queue

    def update(**kwargs):
        if kwargs["thread_id"] == "active":
            state.now = 105.0
            queue.add("pending", ["first"], user_id="alice", correction_detected=True)
            state.now = 109.0
            queue.add("pending", ["latest"], user_id="alice", reinforcement_detected=True)
            assert len(state.timers) == 1
            state.now = finish_time
        return True

    state.updater.update_memory.side_effect = update
    queue.add_nowait("active", ["active"], user_id="alice")
    state.timers[0].fire()

    assert len(state.timers) == 2
    assert state.timers[1].interval == expected_delay
    assert state.updater.update_memory.call_count == 1
    state.timers[1].fire()
    pending = state.updater.update_memory.call_args.kwargs
    assert pending["messages"] == ["latest"]
    assert pending["user_id"] == "alice"
    assert pending["correction_detected"] is True
    assert pending["reinforcement_detected"] is True
    assert queue.pending_count == 0
    assert queue.is_processing is False
    assert len(state.timers) == 2


@pytest.mark.parametrize("flush_method", ["flush", "flush_nowait", "add_nowait"])
def test_immediate_request_during_worker_coalesces_one_followup(scheduled_queue, flush_method):
    state = scheduled_queue
    queue = state.queue

    def update(**kwargs):
        if kwargs["thread_id"] == "active":
            queue.add("pending", ["first"], user_id="alice")
            for _ in range(20):
                if flush_method == "add_nowait":
                    queue.add_nowait("pending", ["immediate"], user_id="alice")
                else:
                    getattr(queue, flush_method)()
            # Later ordinary enqueues must not postpone an explicit flush.
            queue.add("pending", ["latest"], user_id="alice")
            assert len(state.timers) == 1
            assert state.updater.update_memory.call_count == 1
        return True

    state.updater.update_memory.side_effect = update
    queue.add_nowait("active", ["active"])
    state.timers[0].fire()

    assert len(state.timers) == 2
    assert state.timers[1].interval == 0
    state.timers[1].fire()
    assert state.updater.update_memory.call_count == 2
    assert state.updater.update_memory.call_args.kwargs["messages"] == ["latest"]
    assert queue.pending_count == 0


@pytest.mark.parametrize("cancel_method", ["replacement", "clear", "discard"])
def test_canceled_callback_cannot_process_newer_work(scheduled_queue, cancel_method):
    state = scheduled_queue
    queue = state.queue
    queue.add("old", ["old"])
    old_timer = state.timers[0]
    state.now += 5
    if cancel_method == "clear":
        queue.clear()
    elif cancel_method == "discard":
        queue.discard_thread("old")
    queue.add("new", ["new"])
    current_timer = state.timers[-1]

    assert old_timer.cancelled
    old_timer.fire()
    state.updater.update_memory.assert_not_called()
    assert queue._timer is current_timer
    current_timer.fire()
    assert state.updater.update_memory.call_args.kwargs["thread_id"] == "new"
    assert queue.pending_count == 0


def test_discard_during_worker_cancels_only_selected_owner(scheduled_queue):
    state = scheduled_queue
    queue = state.queue

    def update(**kwargs):
        if kwargs["user_id"] == "alice":
            queue.add_nowait("shared", ["alice pending"], user_id="alice")
            queue.add_nowait("shared", ["bob pending"], user_id="bob")
            assert queue.discard_thread("shared", user_id="alice") == 2
            assert kwargs["is_cancelled"]()
            queue.add_nowait("shared", ["late alice"], user_id="alice")
            assert queue.pending_count == 1
        return True

    state.updater.update_memory.side_effect = update
    queue.add_nowait("shared", ["alice active"], user_id="alice")
    state.timers[0].fire()
    assert len(state.timers) == 2
    state.timers[1].fire()
    assert [call.kwargs["user_id"] for call in state.updater.update_memory.call_args_list] == ["alice", "bob"]


def test_clear_during_worker_resets_immediate_request_for_future_work(scheduled_queue):
    state = scheduled_queue
    queue = state.queue

    def update(**kwargs):
        if kwargs["thread_id"] == "active":
            queue.add_nowait("cancelled", ["cancelled"])
            queue.clear()
            assert kwargs["is_cancelled"]()
            queue.add("new", ["new"])
        return True

    state.updater.update_memory.side_effect = update
    queue.add_nowait("active", ["active"])
    state.timers[0].fire()
    assert len(state.timers) == 2
    assert state.timers[1].interval == 10
    state.timers[1].fire()
    assert [call.kwargs["thread_id"] for call in state.updater.update_memory.call_args_list] == ["active", "new"]


def test_worker_failure_still_schedules_pending_work(scheduled_queue):
    state = scheduled_queue
    queue = state.queue

    def update(**kwargs):
        if kwargs["thread_id"] == "active":
            queue.add_nowait("pending", ["pending"])
            raise RuntimeError("synthetic updater failure")
        return True

    state.updater.update_memory.side_effect = update
    queue.add_nowait("active", ["active"])
    state.timers[0].fire()
    assert queue.is_processing is False
    assert len(state.timers) == 2
    state.timers[1].fire()
    assert state.updater.update_memory.call_count == 2
    assert queue.pending_count == 0


def test_empty_flush_does_not_schedule_or_accelerate_future_updates(scheduled_queue):
    state = scheduled_queue
    state.queue.flush_nowait()
    state.queue.flush()
    assert state.timers == []
    state.queue.add("later", ["later"])
    assert len(state.timers) == 1
    assert state.timers[0].interval == 10


def test_racing_flush_and_enqueue_never_start_a_second_worker(scheduled_queue):
    state = scheduled_queue
    queue = state.queue
    entered = threading.Event()
    release = threading.Event()

    def update(**kwargs):
        if kwargs["thread_id"] == "active":
            entered.set()
            assert release.wait(5)
        return True

    state.updater.update_memory.side_effect = update
    queue.add_nowait("active", ["active"])
    worker = threading.Thread(target=state.timers[0].fire)
    worker.start()
    try:
        assert entered.wait(5)
        for index in range(20):
            queue.add("pending", [index])
            queue.flush()
            queue.flush_nowait()
        assert state.updater.update_memory.call_count == 1
        assert len(state.timers) == 1
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert len(state.timers) == 2
    state.timers[1].fire()
    assert state.updater.update_memory.call_count == 2
    assert state.updater.update_memory.call_args.kwargs["messages"] == [19]
    assert queue.pending_count == 0
