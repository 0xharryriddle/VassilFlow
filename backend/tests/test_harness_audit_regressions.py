"""Offline regressions for run finalization, budget and memory isolation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime

from vassilflow.agents.factory import create_vassilflow_agent
from vassilflow.agents.memory.queue import MemoryUpdateQueue
from vassilflow.agents.middlewares.memory_middleware import MemoryMiddleware
from vassilflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
from vassilflow.config.memory_config import MemoryConfig
from vassilflow.config.token_budget_config import TokenBudgetConfig
from vassilflow.runtime.runs.manager import ConflictError, RunManager
from vassilflow.runtime.runs.schemas import RunStatus
from vassilflow.runtime.runs.store.memory import MemoryRunStore
from vassilflow.runtime.runs.worker import RunContext, run_agent


def _bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


@pytest.mark.parametrize("timeout", [True, False, float("nan"), float("inf"), -float("inf"), 0, -1, "5"])
def test_replacement_timeout_requires_finite_positive_number(timeout):
    with pytest.raises(ValueError, match="finite positive"):
        RunManager(replacement_timeout=timeout)


@pytest.mark.anyio
async def test_history_fetches_enough_distinct_persisted_runs():
    store = MemoryRunStore()
    await store.put("old-process", thread_id="thread", status="success", created_at="2000-01-01T00:00:00+00:00")
    manager = RunManager(store=store)
    first = await manager.create("thread")
    second = await manager.create("thread")

    records = await manager.list_by_thread("thread", limit=3)

    assert len(records) == 3
    assert {record.run_id for record in records} == {first.run_id, second.run_id, "old-process"}
    assert records[-1].run_id == "old-process"
    assert next(record for record in records if record.run_id == first.run_id) is first


@pytest.mark.anyio
async def test_replacement_waits_for_actual_worker_rollback_before_successor_checkpoint():
    started, rolling_back, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class DelayedSaver(InMemorySaver):
        async def adelete_thread(self, thread_id):
            rolling_back.set()
            await release.wait()
            await super().adelete_thread(thread_id)

    class WaitingGraph:
        async def astream(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()
            yield {}

    saver, manager = DelayedSaver(), RunManager()
    config = {"configurable": {"thread_id": "thread", "checkpoint_ns": ""}}
    previous = await manager.create_or_reject("thread")
    previous.task = asyncio.create_task(run_agent(_bridge(), manager, previous, ctx=RunContext(checkpointer=saver), agent_factory=lambda config: WaitingGraph(), graph_input={}, config=config))
    await started.wait()
    admission = asyncio.create_task(manager.create_or_reject("thread", multitask_strategy="rollback"))
    try:
        await asyncio.wait_for(rolling_back.wait(), 1)
        assert not admission.done(), "A replacement must wait for the predecessor's rollback"
        # Finalization must not hold the global registry lock.
        unrelated = await asyncio.wait_for(manager.create_or_reject("unrelated"), 1)
        assert unrelated.status == RunStatus.pending
        release.set()
        successor = await asyncio.wait_for(admission, 1)
        assert previous.task.done()

        class WritingGraph:
            async def astream(self, *args, **kwargs):
                checkpoint = empty_checkpoint()
                checkpoint["channel_values"] = {"messages": ["successor"]}
                checkpoint["channel_versions"] = {"messages": 1}
                await saver.aput(config, checkpoint, {"step": 1}, {"messages": 1})
                yield {"messages": [AIMessage(content="successor")]}

        await run_agent(_bridge(), manager, successor, ctx=RunContext(checkpointer=saver), agent_factory=lambda config: WritingGraph(), graph_input={}, config=config)
        checkpoint = await saver.aget_tuple(config)
        assert checkpoint is not None
        assert checkpoint.checkpoint["channel_values"]["messages"] == ["successor"]
    finally:
        release.set()
        await asyncio.gather(previous.task, admission, return_exceptions=True)


async def _start_slow_finalizer(manager):
    started, finalizing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    record = await manager.create_or_reject("thread")

    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            finalizing.set()
            await manager.set_status(record.run_id, RunStatus.error)
            await release.wait()

    record.task = asyncio.create_task(worker())
    await started.wait()
    return record, finalizing, release


@pytest.mark.anyio
async def test_replacement_timeout_keeps_finalizing_worker_as_barrier():
    manager = RunManager(replacement_timeout=0.01)
    previous, finalizing, release = await _start_slow_finalizer(manager)
    try:
        with pytest.raises(ConflictError, match="finaliz"):
            await manager.create_or_reject("thread", multitask_strategy="rollback")
        assert finalizing.is_set()
        assert not previous.task.done()
        assert await manager.has_inflight("thread")
        assert not any(record.status == RunStatus.pending for record in await manager.list_by_thread("thread"))
        with pytest.raises(ConflictError):
            await manager.create_or_reject("thread")
        # A retry must not cancel the cleanup a second time.
        with pytest.raises(ConflictError):
            await manager.create_or_reject("thread", multitask_strategy="rollback")
        assert not previous.task.done()
    finally:
        release.set()
        await previous.task
    assert not await manager.has_inflight("thread")


@pytest.mark.anyio
async def test_shutdown_drains_terminal_worker_without_interrupting_rollback_again():
    manager = RunManager()
    previous, finalizing, release = await _start_slow_finalizer(manager)
    await manager.cancel(previous.run_id, action="rollback")
    await asyncio.wait_for(finalizing.wait(), 1)
    shutdown = asyncio.create_task(manager.shutdown(timeout=1))
    try:
        await asyncio.sleep(0)
        assert not shutdown.done()
        assert not previous.task.done()
        assert previous.abort_action == "rollback"
        release.set()
        await shutdown
        assert previous.task.done()
        assert previous.status == RunStatus.error
    finally:
        release.set()
        await asyncio.gather(previous.task, shutdown, return_exceptions=True)


@pytest.mark.anyio
async def test_cancelled_replacement_admission_does_not_cancel_predecessor_cleanup():
    manager = RunManager()
    previous, finalizing, release = await _start_slow_finalizer(manager)
    admission = asyncio.create_task(manager.create_or_reject("thread", multitask_strategy="rollback"))
    try:
        await asyncio.wait_for(finalizing.wait(), 1)
        admission.cancel()
        with pytest.raises(asyncio.CancelledError):
            await admission
        assert not previous.task.done()
        assert not any(record.status == RunStatus.pending for record in await manager.list_by_thread("thread"))
        with pytest.raises(ConflictError):
            await manager.create_or_reject("thread")
    finally:
        release.set()
        await asyncio.gather(previous.task, admission, return_exceptions=True)
    assert (await manager.create_or_reject("thread")).status == RunStatus.pending


@pytest.mark.anyio
async def test_cancel_before_worker_attachment_does_not_run_graph_or_rollback():
    manager = RunManager()
    record = await manager.create_or_reject("thread")
    await manager.cancel(record.run_id, action="rollback")
    saver = SimpleNamespace(aget_tuple=AsyncMock(return_value=None), adelete_thread=AsyncMock())
    factory = MagicMock()

    await run_agent(_bridge(), manager, record, ctx=RunContext(checkpointer=saver), agent_factory=factory, graph_input={}, config={})

    factory.assert_not_called()
    saver.aget_tuple.assert_not_awaited()
    saver.adelete_thread.assert_not_awaited()
    assert record.status == RunStatus.interrupted


@pytest.mark.anyio
async def test_cancel_during_snapshot_read_preserves_existing_checkpoint():
    reading = asyncio.Event()

    class SlowSnapshotSaver(InMemorySaver):
        async def aget_tuple(self, config):
            reading.set()
            await asyncio.Event().wait()

    saver = SlowSnapshotSaver()
    config = {"configurable": {"thread_id": "thread", "checkpoint_ns": ""}}
    original = empty_checkpoint()
    original["channel_values"] = {"messages": ["preserve me"]}
    original["channel_versions"] = {"messages": 1}
    saver.put(config, original, {"step": 1}, {"messages": 1})
    manager = RunManager()
    record = await manager.create_or_reject("thread")
    record.task = asyncio.create_task(run_agent(_bridge(), manager, record, ctx=RunContext(checkpointer=saver), agent_factory=AsyncMock(), graph_input={}, config=config))
    await asyncio.wait_for(reading.wait(), 1)
    await manager.cancel(record.run_id, action="rollback")
    await asyncio.wait_for(record.task, 1)

    restored = saver.get_tuple(config)
    assert restored is not None
    assert restored.checkpoint["channel_values"]["messages"] == ["preserve me"]


class _LocalModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _answer(tokens, **kwargs):
    return AIMessage(content="answer", usage_metadata={"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens}, **kwargs)


@pytest.mark.anyio
async def test_budget_excludes_history_in_concurrent_invocations_without_runtime_run_id():
    budget = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
    graph = create_vassilflow_agent(model=_LocalModel(responses=[_answer(600)]), middleware=[budget])

    results = await asyncio.gather(*(graph.ainvoke({"messages": [_answer(previous, id=f"old-{previous}"), HumanMessage(content="New turn")]}) for previous in (5000, 7000)))

    assert all(result["messages"][-1].text == "answer" for result in results)
    assert not budget._cumulative_usage
    assert not budget._seen_messages
    assert not budget._pending_warnings
    assert not budget._warned
    assert all("_token_budget_run_id" not in result for result in results)


@pytest.mark.anyio
async def test_budget_warning_survives_runtime_wrapper_changes():
    captured = []

    class CapturingModel(_LocalModel):
        async def _agenerate(self, messages, **kwargs):
            captured.append(list(messages))
            return await super()._agenerate(messages, **kwargs)

    @tool
    async def local_lookup() -> str:
        """Return offline evidence."""
        return "evidence"

    budget = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000, warn_threshold=0.8))
    graph = create_vassilflow_agent(model=CapturingModel(responses=[_answer(850, tool_calls=[{"name": "local_lookup", "args": {}, "id": "lookup"}]), _answer(100)]), tools=[local_lookup], middleware=[budget])
    result = await graph.ainvoke({"messages": [HumanMessage(content="Look up evidence")]})

    assert len(captured) == 2
    assert any(message.name == "budget_warning" and "850" in message.text for message in captured[1])
    assert "EXCEEDED" not in result["messages"][-1].text
    assert not budget._cumulative_usage


@pytest.mark.no_auto_user
def test_memory_middleware_queues_authoritative_runtime_owner():
    queue = MemoryUpdateQueue()
    config = MemoryConfig(enabled=True)
    middleware = MemoryMiddleware(memory_config=config)
    state = {"messages": [HumanMessage(content="Remember this preference."), AIMessage(content="Remembered.")]}
    with patch("vassilflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=queue), patch("vassilflow.agents.memory.queue.get_memory_config", return_value=config), patch.object(queue, "_reset_timer"):
        for owner in ("alice", "bob"):
            middleware.after_agent(state, Runtime(context={"thread_id": "same-thread", "user_id": owner}))

    assert [context.user_id for context in queue._queue] == ["alice", "bob"]
