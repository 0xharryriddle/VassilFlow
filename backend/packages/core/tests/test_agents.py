"""Offline integration checks against real compiled LangGraph agents."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from vassilflow_core.agents import create_agent


class ToolModel(FakeMessagesListChatModel):
    """Deterministic model exercising the actual model/tool graph edges."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name: str, args: dict | None = None, *, call_id: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}])


def test_sync_graph_executes_tool_and_streams_values():
    invocations = []

    @tool
    def multiply(left: int, right: int) -> int:
        """Multiply two numbers."""
        invocations.append((left, right))
        return left * right

    model = ToolModel(responses=[call("multiply", {"left": 6, "right": 7}), AIMessage(content="42")])
    graph = create_agent(model, [multiply], system_prompt="Answer using the arithmetic tool.")
    assert isinstance(graph, CompiledStateGraph)
    result = graph.invoke({"messages": [HumanMessage(content="What is 6 times 7?")]})
    assert result["messages"][-1].content == "42"
    assert next(message for message in result["messages"] if isinstance(message, ToolMessage)).content == "42"

    snapshots = list(graph.stream({"messages": [HumanMessage(content="Again")]}, stream_mode="values"))
    assert snapshots[-1]["messages"][-1].content == "42"
    assert any(any(isinstance(message, ToolMessage) for message in snapshot["messages"]) for snapshot in snapshots)
    assert invocations == [(6, 7), (6, 7)]


@pytest.mark.asyncio
async def test_async_graph_executes_async_tool_and_streams():
    invocations = []

    @tool
    async def lookup(key: str) -> str:
        """Look up a local domain fact."""
        invocations.append(key)
        return "The support window is 09:00–17:00."

    model = ToolModel(responses=[call("lookup", {"key": "hours"}), AIMessage(content="09:00–17:00")])
    graph = create_agent(model, [lookup])
    result = await graph.ainvoke({"messages": [HumanMessage(content="Opening hours?")]})
    assert result["messages"][-1].content == "09:00–17:00"
    snapshots = [
        snapshot
        async for snapshot in graph.astream({"messages": [HumanMessage(content="Again")]}, stream_mode="values")
    ]
    assert snapshots[-1]["messages"][-1].content == "09:00–17:00"
    assert invocations == ["hours", "hours"]


@pytest.mark.parametrize("invalid", [0, -1, True, False, 1.5, "2", None])
def test_model_call_limit_requires_positive_integer(invalid):
    with pytest.raises(ValueError, match="positive integer"):
        create_agent(ToolModel(responses=[AIMessage(content="unused")]), max_model_calls=invalid)


def test_model_must_be_supplied_as_an_initialized_instance():
    with pytest.raises(TypeError, match="initialized BaseChatModel"):
        create_agent("openai:unused")


def test_reused_graph_gets_an_independent_model_call_limit_per_invocation():
    invocations = []

    @tool
    def repeat() -> str:
        """Return another observation."""
        invocations.append("called")
        return "Continue"

    graph = create_agent(
        ToolModel(responses=[call("repeat", call_id="first"), call("repeat", call_id="second")]),
        [repeat],
        max_model_calls=2,
    )
    for _ in range(2):
        before = len(invocations)
        with pytest.raises(ModelCallLimitExceededError):
            graph.invoke({"messages": [HumanMessage(content="Keep working")]}, config={"recursion_limit": 30})
        assert len(invocations) - before == 2


@pytest.mark.asyncio
async def test_concurrent_runs_keep_histories_and_model_call_limits_separate():
    entered = []
    both_entered = asyncio.Event()

    @tool
    async def echo(label: str) -> str:
        """Return the request label once both independent runs are active."""
        entered.append(label)
        if len(entered) == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=5)
        return label

    class ConcurrentModel(ToolModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            last = messages[-1]
            response = (
                AIMessage(content=last.content)
                if isinstance(last, ToolMessage)
                else call("echo", {"label": last.content}, call_id=last.content)
            )
            return ChatResult(generations=[ChatGeneration(message=response)])

    graph = create_agent(ConcurrentModel(responses=[]), [echo], max_model_calls=2)
    outputs = await asyncio.gather(
        graph.ainvoke({"messages": [HumanMessage(content="domain-a")]}),
        graph.ainvoke({"messages": [HumanMessage(content="domain-b")]}),
    )
    assert sorted(entered) == ["domain-a", "domain-b"]
    for label, output in zip(["domain-a", "domain-b"], outputs, strict=True):
        assert output["messages"][-1].content == label
        assert [message.content for message in output["messages"] if isinstance(message, HumanMessage)] == [label]


def test_checkpointer_retains_messages_but_resets_run_model_limit():
    graph = create_agent(
        ToolModel(responses=[AIMessage(content="First response"), AIMessage(content="Second response")]),
        checkpointer=InMemorySaver(),
        max_model_calls=1,
    )
    config = {"configurable": {"thread_id": "customer-a"}}
    graph.invoke({"messages": [HumanMessage(content="First question")]}, config=config)
    result = graph.invoke({"messages": [HumanMessage(content="Second question")]}, config=config)
    assert [message.content for message in result["messages"] if isinstance(message, HumanMessage)] == [
        "First question",
        "Second question",
    ]
    assert result["messages"][-1].content == "Second response"
    assert graph.get_state(config).values["messages"] == result["messages"]
    assert graph.get_state({"configurable": {"thread_id": "customer-b"}}).values == {}


@dataclass
class DomainContext:
    account_id: str


def test_dataclass_context_reaches_tool_without_global_configuration():
    @tool
    def account(runtime: ToolRuntime[DomainContext]) -> str:
        """Read the current account identifier."""
        return runtime.context.account_id

    graph = create_agent(
        ToolModel(responses=[call("account"), AIMessage(content="Done")]),
        [account],
        context_schema=DomainContext,
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Which account?")]}, context=DomainContext(account_id="retail-42")
    )
    assert next(message for message in result["messages"] if isinstance(message, ToolMessage)).content == "retail-42"


class DomainState(AgentState):
    domain: str


class ObserveDomain(AgentMiddleware):
    def __init__(self):
        self.domains = []

    def before_agent(self, state, runtime):
        self.domains.append(state["domain"])


def test_custom_state_and_middleware_are_preserved():
    observer = ObserveDomain()
    graph = create_agent(
        ToolModel(responses=[AIMessage(content="Done")]),
        middleware=[observer],
        state_schema=DomainState,
    )
    result = graph.invoke({"messages": [HumanMessage(content="Hello")], "domain": "manufacturing"})
    assert result["domain"] == "manufacturing"
    assert observer.domains == ["manufacturing"]
