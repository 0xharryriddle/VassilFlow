"""Offline graph/executor regressions for independently bounded delegated tasks."""

import asyncio
import importlib
import logging

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from vassilflow.agents.middlewares import tool_error_handling_middleware as runtime_middlewares
from vassilflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
from vassilflow.config.agent_contract import AgentRuntimePolicy
from vassilflow.config.app_config import AppConfig
from vassilflow.config.guardrails_config import GuardrailsConfig
from vassilflow.config.loop_detection_config import LoopDetectionConfig
from vassilflow.config.model_config import ModelConfig
from vassilflow.config.sandbox_config import SandboxConfig
from vassilflow.config.token_budget_config import TokenBudgetConfig
from vassilflow.config.token_usage_config import TokenUsageConfig
from vassilflow.subagents.config import SubagentConfig


def _app_config(enabled: bool | None = True) -> AppConfig:
    kwargs = {} if enabled is None else {"token_budget": TokenBudgetConfig(enabled=enabled, max_tokens=1000)}
    return AppConfig(
        models=[ModelConfig(name="offline-model", use="langchain_openai:ChatOpenAI", model="offline-model")],
        sandbox=SandboxConfig(use="test"),
        guardrails=GuardrailsConfig(enabled=False),
        loop_detection=LoopDetectionConfig(enabled=False),
        token_usage=TokenUsageConfig(enabled=False),
        **kwargs,
    )


@pytest.fixture
def isolated_runtime(monkeypatch):
    # Exercise the actual child-only composition and compiled graph while
    # leaving filesystem/sandbox infrastructure out of this offline test.
    monkeypatch.setattr(runtime_middlewares, "_build_runtime_middlewares", lambda **kwargs: [])


@pytest.mark.parametrize("enabled", [None, False])
def test_subagent_builder_keeps_budget_opt_in(isolated_runtime, enabled):
    middlewares = runtime_middlewares.build_subagent_runtime_middlewares(app_config=_app_config(enabled))
    assert not any(isinstance(middleware, TokenBudgetMiddleware) for middleware in middlewares)


def test_subagent_builder_inherits_enabled_budget(isolated_runtime):
    config = _app_config()
    middlewares = runtime_middlewares.build_subagent_runtime_middlewares(app_config=config)
    budgets = [middleware for middleware in middlewares if isinstance(middleware, TokenBudgetMiddleware)]
    assert len(budgets) == 1
    assert config.token_budget.max_tokens == 1000


@pytest.fixture
def executor_runtime(isolated_runtime, monkeypatch):
    executor_module = importlib.import_module("vassilflow.subagents.executor")
    monkeypatch.setattr(executor_module, "build_tracing_callbacks", lambda: [])
    monkeypatch.setattr(executor_module, "inject_langfuse_metadata", lambda *args, **kwargs: None)
    bound_tools: list[list[str]] = []
    executed_tools: list[int] = []

    class RepeatingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound_tools.append([item.name for item in tools])
            return self

    def make_model(**kwargs):
        messages = [
            AIMessage(
                id=f"model-{index}",
                content=f"Working on step {index}",
                tool_calls=[{"name": "work", "args": {"step": index}, "id": f"call-{index}"}],
                usage_metadata={"input_tokens": 500, "output_tokens": 100, "total_tokens": 600},
            )
            for index in (1, 2)
        ]
        messages.append(AIMessage(id="done", content="Finished all steps"))
        return RepeatingModel(messages=iter(messages), disable_streaming=True)

    monkeypatch.setattr(executor_module, "create_chat_model", make_model)

    @tool
    async def work(step: int) -> str:
        """Perform a local test step without external side effects."""
        executed_tools.append(step)
        await asyncio.sleep(0)
        return f"Step {step} complete"

    @tool
    async def forbidden() -> str:
        """A tool the inherited parent policy must hide."""
        raise AssertionError("parent policy must not permit this tool")

    def make_executor(enabled: bool = True):
        return executor_module.SubagentExecutor(
            config=SubagentConfig(name="bounded-child", description="offline regression", skills=[], max_turns=50),
            tools=[work, forbidden],
            app_config=_app_config(enabled),
            run_id="shared-parent-run",
            user_id="test-user",
            agent_policy=AgentRuntimePolicy(allowed_tool_names=frozenset({"work"})),
        )

    return executor_module, make_executor, bound_tools, executed_tools


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_subagent_async_model_loop_obeys_budget_and_keeps_usage(executor_runtime, enabled):
    executor_module, make_executor, bound_tools, executed_tools = executor_runtime
    executor = make_executor(enabled)
    assert executor.app_config.token_usage.enabled is False

    result = await executor._aexecute("Perform the steps")

    assert result.status == executor_module.SubagentStatus.COMPLETED
    assert all(names == ["work"] for names in bound_tools)
    assert len(bound_tools) == (2 if enabled else 3)
    assert executed_tools == ([1] if enabled else [1, 2])
    assert ("TOKEN BUDGET EXCEEDED" in result.result) is enabled
    assert sum(record["total_tokens"] for record in result.token_usage_records) == 1200
    assert len(result.token_usage_records) == 2
    assert all(record["caller"] == "subagent:bounded-child" for record in result.token_usage_records)


@pytest.mark.asyncio
async def test_concurrent_tasks_with_same_parent_id_have_independent_budgets(executor_runtime):
    executor_module, make_executor, bound_tools, executed_tools = executor_runtime
    executor = make_executor()

    results = await asyncio.gather(executor._aexecute("First task"), executor._aexecute("Second task"))

    assert results[0].task_id != results[1].task_id
    assert len(bound_tools) == 4
    assert executed_tools == [1, 1]
    for result in results:
        assert result.status == executor_module.SubagentStatus.COMPLETED
        assert "TOKEN BUDGET EXCEEDED" in result.result
        assert sum(record["total_tokens"] for record in result.token_usage_records) == 1200


@pytest.mark.asyncio
async def test_budget_stopped_child_usage_is_merged_into_parent_once(executor_runtime):
    from vassilflow.agents.middlewares.token_usage_middleware import TokenUsageMiddleware
    from vassilflow.tools.builtins.task_tool import _cache_subagent_usage, _summarize_usage, pop_cached_subagent_usage

    _, make_executor, _, _ = executor_runtime
    result = await make_executor()._aexecute("Perform the steps")
    call_id = "budget-parent-dispatch"
    _cache_subagent_usage(call_id, _summarize_usage(result.token_usage_records))
    dispatch = AIMessage(
        id="parent-dispatch",
        content="",
        tool_calls=[{"name": "task", "args": {}, "id": call_id}],
        usage_metadata={"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
    )
    state = {"messages": [dispatch, ToolMessage(content=result.result, tool_call_id=call_id), AIMessage(id="parent-reply", content="Done")]}
    try:
        update = await TokenUsageMiddleware().aafter_model(state, None)
        merged = next(message for message in update["messages"] if message.id == dispatch.id)
        assert merged.usage_metadata == {"input_tokens": 1080, "output_tokens": 220, "total_tokens": 1300}
        assert pop_cached_subagent_usage(call_id) is None
    finally:
        pop_cached_subagent_usage(call_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("report_usage", [True, False])
async def test_lead_checks_delegated_usage_before_executing_more_tools(monkeypatch, caplog, report_usage):
    from vassilflow.agents.lead_agent import agent as lead_agent
    from vassilflow.agents.middlewares.token_usage_middleware import TOKEN_USAGE_ATTRIBUTION_KEY, TokenUsageMiddleware
    from vassilflow.tools.builtins.task_tool import _cache_subagent_usage, _token_usage_cache_enabled, pop_cached_subagent_usage

    config = _app_config()
    config.token_usage.enabled = report_usage
    monkeypatch.setattr(lead_agent, "build_lead_runtime_middlewares", lambda **kwargs: [])
    # Preserve the actual lead builder's configuration and ordering; only run
    # the budget/accounting pair so the test needs no sandbox or persistence.
    middlewares = [middleware for middleware in lead_agent.build_middlewares({}, model_name="offline-model", app_config=config) if isinstance(middleware, (TokenBudgetMiddleware, TokenUsageMiddleware))]
    executed: list[str] = []
    call_id = f"lead-budget-task-{report_usage}"

    @tool
    async def task() -> str:
        """Return a completed delegated task with usage that exhausted the cap."""
        _cache_subagent_usage(
            call_id,
            {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100},
            enabled=_token_usage_cache_enabled(config),
        )
        return "Delegated result"

    @tool
    async def work() -> str:
        """Observe whether another tool ran after the total budget was spent."""
        executed.append("work")
        return "Extra work"

    class ParentModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    def response(message_id, tool_name=None):
        return AIMessage(
            id=message_id,
            content="Done" if tool_name is None else "",
            tool_calls=[] if tool_name is None else [{"name": tool_name, "args": {}, "id": call_id if tool_name == "task" else message_id}],
            usage_metadata={"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
        )

    graph = create_agent(
        model=ParentModel(messages=iter([response("dispatch", "task"), response("next-step", "work"), response("done")]), disable_streaming=True),
        tools=[task, work],
        middleware=middlewares,
    )
    try:
        with caplog.at_level(logging.INFO, logger="vassilflow.agents.middlewares.token_usage_middleware"):
            result = await graph.ainvoke({"messages": [HumanMessage(content="Delegate the task")]}, context={"run_id": "parent-budget"})

        assert executed == []
        ai_messages = [message for message in result["messages"] if isinstance(message, AIMessage)]
        assert len(ai_messages) == 2
        assert "TOKEN BUDGET EXCEEDED" in ai_messages[-1].content
        assert ai_messages[-1].tool_calls == []
        assert sum(message.usage_metadata["total_tokens"] for message in ai_messages) == 1300
        assert pop_cached_subagent_usage(call_id) is None
        if not report_usage:
            assert "LLM token usage" not in caplog.text
            assert all(TOKEN_USAGE_ATTRIBUTION_KEY not in message.additional_kwargs for message in ai_messages)
    finally:
        pop_cached_subagent_usage(call_id)


def test_subagent_usage_cache_stays_disabled_without_reporting_or_budget():
    from vassilflow.tools.builtins.task_tool import _token_usage_cache_enabled

    assert _token_usage_cache_enabled(_app_config(False)) is False
