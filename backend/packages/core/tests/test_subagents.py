"""Offline delegation tests using real parent and child LangGraph graphs."""

import asyncio
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from langchain.agents import AgentState
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import PrivateAttr

from vassilflow_core.agents import create_agent
from vassilflow_core.subagents import create_subagent_tool


def graph_for(node, *, context_schema=None, checkpointer=False):
    graph = StateGraph(AgentState, context_schema=context_schema)
    graph.add_node("work", node)
    graph.add_edge(START, "work")
    graph.add_edge("work", END)
    return graph.compile(checkpointer=checkpointer)


async def answer(state):
    return {"messages": [AIMessage(content=f"Answer: {state['messages'][0].content}")]}


def tool_for(agent=None, **kwargs):
    return create_subagent_tool(
        name="research",
        description="Research a self-contained task.",
        agent=agent if agent is not None else graph_for(answer),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_direct_async_invocation_and_artifact_do_not_expose_child_history():
    async def usage_answer(state):
        return {
            "messages": [
                AIMessage(
                    content="Internal reasoning",
                    usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
                ),
                AIMessage(
                    content=[{"type": "text", "text": "Final answer"}],
                    usage_metadata={"input_tokens": 9, "output_tokens": 3, "total_tokens": 12},
                ),
            ]
        }

    delegated = tool_for(graph_for(usage_answer))
    assert set(delegated.tool_call_schema.model_json_schema()["properties"]) == {"task"}
    assert await delegated.ainvoke({"task": "Question"}) == "Final answer"
    message = await delegated.ainvoke(
        {"type": "tool_call", "name": "research", "id": "delegation-1", "args": {"task": "Question"}}
    )
    assert isinstance(message, ToolMessage)
    assert message.content == "Final answer"
    assert str(UUID(message.artifact.pop("invocation_id")))
    assert message.artifact == {
        "agent": "research",
        "status": "completed",
        "usage": {"input_tokens": 14, "output_tokens": 5, "total_tokens": 19},
        "tool_artifacts": [],
    }
    assert "Internal reasoning" not in json.dumps(message.artifact)


def test_sync_invocation_is_explicitly_unsupported():
    with pytest.raises(NotImplementedError, match="sync invocation"):
        tool_for().invoke({"task": "Question"})


@dataclass
class AccountContext:
    account: str


class ParentModel(FakeMessagesListChatModel):
    _seen: list = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class TraceRecorder(BaseCallbackHandler):
    def __init__(self):
        self.starts = []

    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs):
        self.starts.append({"run_id": run_id, **kwargs})


@pytest.mark.asyncio
async def test_parent_graph_passes_context_and_domain_config_without_history_or_checkpoints():
    observed = []

    async def child_work(state, config: RunnableConfig, runtime: Runtime[AccountContext]):
        observed.append((state, config, runtime.context))
        return {"messages": [AIMessage(content=f"Data for {runtime.context.account}")]}

    delegated = tool_for(graph_for(child_work, context_schema=AccountContext))
    parent_model = ParentModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "research",
                        "args": {"task": "Only this child task"},
                        "id": "delegate-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Parent answer"),
        ]
    )
    checkpoints = InMemorySaver()
    parent = create_agent(parent_model, [delegated], checkpointer=checkpoints, context_schema=AccountContext)
    recorder = TraceRecorder()
    run_id = uuid4()
    result = await parent.ainvoke(
        {"messages": [HumanMessage(content="Parent private history")]},
        config={
            "run_id": run_id,
            "configurable": {
                "thread_id": "parent-thread",
                "domain": "retail",
                "__pregel_foreign_marker": "must-not-reach-child",
            },
            "tags": ["domain:retail"],
            "metadata": {"request_label": "support"},
            "callbacks": [recorder],
        },
        context=AccountContext(account="a-42"),
    )
    child_state, child_config, child_context = observed[0]
    assert [message.content for message in child_state["messages"]] == ["Only this child task"]
    assert child_context == AccountContext(account="a-42")
    assert child_config["configurable"]["domain"] == "retail"
    assert "thread_id" not in child_config["configurable"]
    assert "__pregel_foreign_marker" not in child_config["configurable"]
    assert "domain:retail" in child_config["tags"]
    assert child_config["metadata"]["request_label"] == "support"
    assert child_config.get("run_id") != run_id
    assert set(checkpoints.storage) == {"parent-thread"}
    assert set(checkpoints.storage["parent-thread"]) == {""}
    tool_message = next(message for message in result["messages"] if isinstance(message, ToolMessage))
    assert tool_message.content == "Data for a-42"
    assert str(UUID(tool_message.artifact.pop("invocation_id")))
    assert tool_message.artifact == {"agent": "research", "status": "completed", "usage": None, "tool_artifacts": []}
    assert any(start.get("name") == "research" for start in recorder.starts)


@pytest.mark.parametrize("checkpoint", [None, True, InMemorySaver()])
def test_child_requires_explicitly_disabled_checkpoint_inheritance(checkpoint):
    with pytest.raises(ValueError, match="checkpointer=False"):
        tool_for(graph_for(answer, checkpointer=checkpoint))


@pytest.mark.asyncio
async def test_child_retrieval_artifacts_preserve_sources_and_separate_invocation_scopes():
    async def child_work(state):
        artifact = {"sources": [{"id": "S1", "source": state["messages"][0].content}]}
        return {
            "messages": [
                ToolMessage(content="Retrieved text", name="retrieve", tool_call_id="retrieve-1", artifact=artifact),
                AIMessage(content="The answer is supported by [S1]."),
            ]
        }

    delegated = tool_for(graph_for(child_work))
    results = [
        await delegated.ainvoke(
            {"type": "tool_call", "name": "research", "id": f"call-{index}", "args": {"task": source}}
        )
        for index, source in enumerate(["policy-a.md", "policy-b.md"])
    ]
    assert results[0].artifact["invocation_id"] != results[1].artifact["invocation_id"]
    for result, source in zip(results, ["policy-a.md", "policy-b.md"], strict=True):
        assert result.artifact["tool_artifacts"] == [
            {
                "tool_name": "retrieve",
                "tool_call_id": "retrieve-1",
                "artifact": {"sources": [{"id": "S1", "source": source}]},
            }
        ]
        assert "Retrieved text" not in json.dumps(result.artifact)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_concurrency": 0},
        {"max_concurrency": True},
        {"max_concurrency": 1.5},
        {"recursion_limit": 0},
        {"timeout_seconds": 0},
        {"timeout_seconds": -1},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": True},
    ],
)
def test_invalid_execution_limits_fail_at_construction(kwargs):
    with pytest.raises(ValueError):
        tool_for(**kwargs)


@pytest.mark.asyncio
async def test_concurrency_bound_is_shared_by_calls_to_one_tool():
    active = 0
    peak = 0
    two_running = asyncio.Event()
    release = asyncio.Event()

    async def work(state):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            two_running.set()
        try:
            await release.wait()
            return {"messages": [AIMessage(content="Done")]}
        finally:
            active -= 1

    delegated = tool_for(graph_for(work), max_concurrency=2)
    calls = [asyncio.create_task(delegated.ainvoke({"task": str(index)})) for index in range(4)]
    await asyncio.wait_for(two_running.wait(), 2)
    assert active == 2
    release.set()
    assert await asyncio.gather(*calls) == ["Done"] * 4
    assert peak == 2
    assert active == 0


@pytest.mark.asyncio
async def test_timeout_cancels_running_child_and_releases_slot():
    cancelled = asyncio.Event()

    async def work(state):
        if state["messages"][0].content == "hang":
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return {"messages": [AIMessage(content="Done")]}

    delegated = tool_for(graph_for(work), max_concurrency=1, timeout_seconds=0.08)
    with pytest.raises(TimeoutError):
        await delegated.ainvoke({"task": "hang"})
    assert cancelled.is_set()
    assert await delegated.ainvoke({"task": "fast"}) == "Done"


@pytest.mark.asyncio
async def test_timeout_waits_for_cooperative_child_cleanup():
    cleaning_up = asyncio.Event()
    allow_cleanup = asyncio.Event()

    async def work(state):
        try:
            await asyncio.Event().wait()
        finally:
            cleaning_up.set()
            await allow_cleanup.wait()

    delegated = tool_for(graph_for(work), max_concurrency=1, timeout_seconds=0.08)
    running = asyncio.create_task(delegated.ainvoke({"task": "Question"}))
    try:
        await asyncio.wait_for(cleaning_up.wait(), 2)
        # The timeout requests cancellation; it cannot skip awaited cleanup or
        # promise that the caller returns at an exact wall-clock deadline.
        assert not running.done()
    finally:
        allow_cleanup.set()
        with pytest.raises(TimeoutError):
            await running


@pytest.mark.asyncio
async def test_timeout_includes_waiting_for_a_concurrency_slot():
    entered = asyncio.Event()
    started = []

    async def work(state):
        task = state["messages"][0].content
        started.append(task)
        entered.set()
        if task == "hold":
            # A slow cancellation cleanup keeps the first task in the slot
            # while the second call's own queue timeout expires.
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.12)
        return {"messages": [AIMessage(content="Done")]}

    delegated = tool_for(graph_for(work), max_concurrency=1, timeout_seconds=0.08)
    holding = asyncio.create_task(delegated.ainvoke({"task": "hold"}))
    await asyncio.wait_for(entered.wait(), 2)
    with pytest.raises(TimeoutError):
        await delegated.ainvoke({"task": "queued"})
    with pytest.raises(TimeoutError):
        await holding
    assert started == ["hold"]
    assert await delegated.ainvoke({"task": "reused"}) == "Done"


@pytest.mark.asyncio
async def test_external_cancellation_cleans_up_and_allows_reuse():
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def work(state):
        if state["messages"][0].content == "cancel":
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return {"messages": [AIMessage(content="Done")]}

    delegated = tool_for(graph_for(work), max_concurrency=1)
    running = asyncio.create_task(delegated.ainvoke({"task": "cancel"}))
    await asyncio.wait_for(entered.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert cancelled.is_set()
    assert await delegated.ainvoke({"task": "reused"}) == "Done"


@pytest.mark.asyncio
async def test_child_errors_propagate_and_release_slot():
    async def work(state):
        if state["messages"][0].content == "fail":
            raise RuntimeError("domain service unavailable")
        return {"messages": [AIMessage(content="Done")]}

    delegated = tool_for(graph_for(work), max_concurrency=1)
    with pytest.raises(RuntimeError, match="domain service unavailable"):
        await delegated.ainvoke({"task": "fail"})
    assert await delegated.ainvoke({"task": "retry"}) == "Done"


@pytest.mark.asyncio
async def test_interrupted_child_draft_is_not_reported_as_completed():
    async def draft(state):
        return {"messages": [AIMessage(content="Draft awaiting approval")]}

    async def approval(state):
        interrupt("Approve this draft?")
        return {"messages": [AIMessage(content="Approved answer")]}

    graph = StateGraph(AgentState)
    graph.add_node("draft", draft)
    graph.add_node("approval", approval)
    graph.add_edge(START, "draft")
    graph.add_edge("draft", "approval")
    graph.add_edge("approval", END)
    agent = graph.compile(checkpointer=False)
    result = await agent.ainvoke({"messages": [HumanMessage(content="Question")]})
    assert result["__interrupt__"]
    assert result["messages"][-1].content == "Draft awaiting approval"

    with pytest.raises(ValueError, match="interrupted"):
        await tool_for(agent).ainvoke({"task": "Question"})


@pytest.mark.parametrize("breakpoint", ["interrupt_before", "interrupt_after"])
def test_static_breakpoints_are_rejected_for_stateless_delegation(breakpoint):
    graph = StateGraph(AgentState)
    graph.add_node("work", answer)
    graph.add_edge(START, "work")
    graph.add_edge("work", END)
    with pytest.raises(ValueError, match="static breakpoints"):
        tool_for(graph.compile(checkpointer=False, **{breakpoint: ["work"]}))


@pytest.mark.asyncio
@pytest.mark.parametrize("breakpoint", ["interrupt_before", "interrupt_after"])
@pytest.mark.parametrize("wrapper", ["direct", "retry", "sequence"])
async def test_nested_stateless_breakpoint_cannot_complete_an_outer_draft(breakpoint, wrapper):
    inner = StateGraph(AgentState)
    inner.add_node("approval", answer)
    inner.add_edge(START, "approval")
    inner.add_edge("approval", END)
    nested = inner.compile(checkpointer=False, **{breakpoint: ["approval"]})
    if wrapper == "retry":
        nested = nested.with_retry(stop_after_attempt=1)
    elif wrapper == "sequence":
        nested = RunnableLambda(lambda state: state) | nested
    outer = StateGraph(AgentState)
    outer.add_node("draft", answer)
    outer.add_node("nested", nested)
    outer.add_edge(START, "draft")
    outer.add_edge("draft", "nested")
    outer.add_edge("nested", END)
    agent = outer.compile(checkpointer=False)

    # Native stateless nested breakpoints can return the outer draft without an
    # interrupt marker. They therefore must be rejected before invocation.
    result = await agent.ainvoke({"messages": [HumanMessage(content="Draft")]})
    assert not result.get("__interrupt__")
    assert result["messages"][-1].content == "Answer: Draft"
    with pytest.raises(ValueError, match="static breakpoints"):
        tool_for(agent)


@pytest.mark.asyncio
async def test_dynamic_interrupt_from_nested_graph_reaches_completion_validation():
    async def approval(state):
        interrupt("Approval required")
        return {"messages": [AIMessage(content="Approved")]}

    nested = graph_for(approval)
    outer = StateGraph(AgentState)
    outer.add_node("draft", answer)
    outer.add_node("nested", nested)
    outer.add_edge(START, "draft")
    outer.add_edge("draft", "nested")
    outer.add_edge("nested", END)
    with pytest.raises(ValueError, match="interrupted"):
        await tool_for(outer.compile(checkpointer=False)).ainvoke({"task": "Question"})


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [HumanMessage(content="No answer")],
        [AIMessage(content="")],
        [AIMessage(content="answer", additional_kwargs={"function_call": {"name": "lookup", "arguments": "{}"}})],
        [
            AIMessage(
                content="pending", tool_calls=[{"name": "search", "args": {}, "id": "call-1", "type": "tool_call"}]
            )
        ],
    ],
)
@pytest.mark.asyncio
async def test_child_without_completed_text_does_not_report_success(messages):
    async def unfinished(state):
        return {"messages": messages}

    with pytest.raises(ValueError, match="final assistant|pending tool calls"):
        await tool_for(graph_for(unfinished)).ainvoke({"task": "Question"})


def test_same_tool_can_run_on_multiple_event_loop_lifetimes():
    async def work(state):
        await asyncio.sleep(0.01)
        return {"messages": [AIMessage(content="Done")]}

    delegated = tool_for(graph_for(work), max_concurrency=1)

    async def invoke_pair():
        return await asyncio.gather(delegated.ainvoke({"task": "First"}), delegated.ainvoke({"task": "Second"}))

    assert asyncio.run(invoke_pair()) == ["Done", "Done"]
    assert asyncio.run(invoke_pair()) == ["Done", "Done"]
