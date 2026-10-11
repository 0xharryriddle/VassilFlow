"""Build native LangGraph agents from explicitly supplied components."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents import AgentState
from langchain.agents import create_agent as _create_langchain_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from .middleware import DanglingToolCallMiddleware


def create_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool | Callable[..., Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    checkpointer: BaseCheckpointSaver | bool | None = None,
    context_schema: type | None = None,
    state_schema: type[AgentState] | None = None,
    max_model_calls: int = 20,
    name: str | None = None,
) -> CompiledStateGraph:
    """Create a graph with interrupted-tool recovery and a per-run model limit.

    All model, tool, persistence and domain behavior is supplied by the caller.
    No application configuration, provider SDK, storage directory, sandbox or
    implicit tool is loaded. The returned graph retains LangGraph's native
    ``invoke``, ``ainvoke``, ``stream`` and ``astream`` APIs.

    ``max_model_calls`` counts model calls for one graph invocation, including
    runs that resume a persisted thread. Reaching the limit raises LangChain's
    ``ModelCallLimitExceededError`` instead of returning an invented answer.
    The limit does not cap tokens or elapsed time. Callers may additionally
    supply LangGraph's ``recursion_limit`` in invocation config or an outer
    timeout. Caller middleware runs alongside the two built-in middleware.

    Pass ``checkpointer=False`` when composing a stateless delegated graph to
    prevent it inheriting the parent's checkpointer. No checkpointer is created
    by this factory. Custom ``state_schema`` and ``context_schema`` are passed
    through to LangChain unchanged.
    """
    if not isinstance(model, BaseChatModel):
        raise TypeError("model must be an initialized BaseChatModel instance")
    if isinstance(max_model_calls, bool) or not isinstance(max_model_calls, int) or max_model_calls < 1:
        raise ValueError("max_model_calls must be a positive integer")

    return _create_langchain_agent(
        model=model,
        tools=list(tools) if tools is not None else None,
        system_prompt=system_prompt,
        middleware=[
            DanglingToolCallMiddleware(),
            ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="error"),
            *middleware,
        ],
        checkpointer=checkpointer,
        context_schema=context_schema,
        state_schema=state_schema or AgentState,
        name=name,
    )


__all__ = ["create_agent"]
