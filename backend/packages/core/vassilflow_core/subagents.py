"""Bounded, in-process delegation to explicitly supplied stateless agent graphs."""

import asyncio
import math
import threading
import weakref
from typing import Any
from uuid import uuid4

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableParallel, RunnableSequence
from langchain_core.runnables.base import RunnableBindingBase
from langchain_core.runnables.config import set_config_context
from langchain_core.tools import StructuredTool
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field


class _TaskInput(BaseModel):
    task: str = Field(min_length=1, description="The self-contained task for the delegated agent.")


def _validate_no_static_breakpoints(agent: CompiledStateGraph) -> None:
    """Check explicit nested graphs, including stateless ones omitted by get_subgraphs."""
    pending: list[Runnable] = [agent]
    visited: set[int] = set()
    while pending:
        runnable = pending.pop()
        if id(runnable) in visited:
            continue
        visited.add(id(runnable))
        if isinstance(runnable, CompiledStateGraph):
            if runnable.interrupt_before_nodes or runnable.interrupt_after_nodes:
                raise ValueError("Stateless child agents cannot use static breakpoints, including in nested graphs")
            for node in runnable.nodes.values():
                pending.extend(nested for nested in (node.bound, *node.subgraphs) if isinstance(nested, Runnable))
        elif isinstance(runnable, RunnableBindingBase):
            pending.append(runnable.bound)
        elif isinstance(runnable, RunnableSequence):
            pending.extend(runnable.steps)
        elif isinstance(runnable, RunnableParallel):
            pending.extend(runnable.steps__.values())


def _child_config(config: RunnableConfig, *, name: str, recursion_limit: int, callbacks: Any) -> RunnableConfig:
    """Keep caller-owned configuration, excluding parent graph execution state."""
    excluded = {"thread_id", "checkpoint_id", "checkpoint_ns", "checkpoint_map", "run_id"}
    return {
        "callbacks": callbacks if callbacks is not None else config.get("callbacks"),
        "tags": [*config.get("tags", []), f"subagent:{name}"],
        "metadata": dict(config.get("metadata", {})),
        "configurable": {
            key: value
            for key, value in config.get("configurable", {}).items()
            if key not in excluded and not key.startswith("__")
        },
        "recursion_limit": recursion_limit,
        "run_name": name,
    }


def _completed_result(state: dict, *, name: str, invocation_id: str) -> tuple[str, dict[str, Any]]:
    if state.get("__interrupt__"):
        raise ValueError(f"Subagent {name!r} interrupted before completing; stateless delegation cannot resume it")
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], AIMessage):
        raise ValueError(f"Subagent {name!r} did not return a final assistant response")
    final = messages[-1]
    if (
        final.tool_calls
        or final.invalid_tool_calls
        or final.additional_kwargs.get("tool_calls")
        or final.additional_kwargs.get("function_call")
    ):
        raise ValueError(f"Subagent {name!r} stopped with pending tool calls")
    if isinstance(final.content, str):
        text = final.content
    else:
        parts = []
        for block in final.content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        text = "\n".join(parts)
    if not text.strip():
        raise ValueError(f"Subagent {name!r} returned no final assistant text")

    usage = None
    seen_ids = set()
    for message in messages:
        if not isinstance(message, AIMessage) or not message.usage_metadata:
            continue
        if message.id is not None and message.id in seen_ids:
            continue
        if message.id is not None:
            seen_ids.add(message.id)
        if usage is None:
            usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for key in usage:
            value = message.usage_metadata.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                usage[key] += value
    tool_artifacts = [
        {"tool_name": message.name, "tool_call_id": message.tool_call_id, "artifact": message.artifact}
        for message in messages
        if isinstance(message, ToolMessage) and message.artifact is not None
    ]
    return text, {
        "agent": name,
        "invocation_id": invocation_id,
        "status": "completed",
        "usage": usage,
        "tool_artifacts": tool_artifacts,
    }


def create_subagent_tool(
    *,
    name: str,
    description: str,
    agent: CompiledStateGraph,
    max_concurrency: int = 2,
    timeout_seconds: float = 60,
    recursion_limit: int = 40,
) -> StructuredTool:
    """Expose a stateless child graph as an asynchronous tool with ``task`` input.

    Compile the child with ``checkpointer=False``. Each call starts with only
    its task message and explicitly inherits domain context, callbacks, tags,
    metadata and public configurable values. Parent conversation and checkpoint
    identities are excluded. Only final assistant text reaches the parent;
    token usage and child tool artifacts are returned separately. Every result
    has a unique ``invocation_id`` so citation IDs in child artifacts can be
    scoped to that call. User-defined artifacts retain LangChain's arbitrary
    Python values; callers own their serialization for external transports.

    Explicit graphs with static breakpoints, including nested graph nodes, are
    rejected; dynamic interrupts raise ``ValueError`` rather than returning a
    draft as completed. Callers own graphs hidden inside arbitrary Python nodes:
    do not conceal an interrupted outcome by returning an earlier draft.

    The concurrency bound covers awaiting invocations per tool instance, per
    event loop. It is not a process-wide or distributed limit. The timeout
    includes waiting for a slot and requests cooperative cancellation; cleanup
    can delay its return. Running synchronous executor work cannot be forcibly
    stopped and may outlive the released slot. Such integrations must enforce
    their own I/O deadlines and resource limits. Cancellation, timeout and
    execution errors propagate. Use ``ainvoke`` or ``astream`` on a parent graph
    containing this async-only tool.

    Direct ``tool.ainvoke({"task": ...})`` returns text. Calling with a native
    ToolCall additionally returns a ToolMessage containing the usage artifact.
    No application config, background executor or storage is created.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string")
    if not isinstance(agent, CompiledStateGraph):
        raise TypeError("agent must be a compiled LangGraph graph")
    if agent.checkpointer is not False:
        raise ValueError("The child agent must be compiled with checkpointer=False")
    _validate_no_static_breakpoints(agent)
    for label, value in (("max_concurrency", max_concurrency), ("recursion_limit", recursion_limit)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{label} must be a positive integer")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be a finite positive number")

    # Both references are weak: a contended Semaphore retains its event loop,
    # so a strong dictionary value would otherwise keep the weak key alive.
    gates: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
    gates_lock = threading.Lock()

    def current_gate() -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        with gates_lock:
            reference = gates.get(loop)
            gate = reference() if reference is not None else None
            if gate is None:
                gate = asyncio.Semaphore(max_concurrency)
                gates[loop] = weakref.ref(gate)
            return gate

    async def delegate(
        task: str, config: RunnableConfig, runtime: ToolRuntime = None, callbacks: Any = None
    ) -> tuple[str, dict[str, Any]]:
        if not task.strip():
            raise ValueError("task must contain non-whitespace text")
        invocation_id = str(uuid4())
        child_config = _child_config(config, name=name, recursion_limit=recursion_limit, callbacks=callbacks)
        context = runtime.context if runtime is not None else None
        async with asyncio.timeout(timeout_seconds):
            async with current_gate():
                # Passing a filtered config alone is insufficient: LangGraph's
                # ensure_config also reads the ambient parent's config ContextVar.
                with set_config_context(child_config) as execution_context:
                    child_task = asyncio.create_task(
                        agent.ainvoke({"messages": [HumanMessage(content=task)]}, config=child_config, context=context),
                        context=execution_context,
                    )
                    result = await child_task
                return _completed_result(result, name=name, invocation_id=invocation_id)

    return StructuredTool.from_function(
        coroutine=delegate,
        name=name,
        description=description,
        args_schema=_TaskInput,
        response_format="content_and_artifact",
    )


__all__ = ["create_subagent_tool"]
