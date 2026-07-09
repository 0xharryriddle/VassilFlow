import sys
from types import ModuleType, SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from vassilflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
    build_subagent_runtime_middlewares,
)
from vassilflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
from vassilflow.agents.middlewares.tool_result_meta import TOOL_META_KEY
from vassilflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from vassilflow.config.app_config import AppConfig, CircuitBreakerConfig
from vassilflow.config.guardrails_config import GuardrailsConfig
from vassilflow.config.loop_detection_config import LoopDetectionConfig
from vassilflow.config.model_config import ModelConfig
from vassilflow.config.sandbox_config import SandboxConfig
from vassilflow.config.tool_progress_config import ToolProgressConfig


def _request(name: str = "web_search", tool_call_id: str | None = "tc-1"):
    tool_call = {"name": name}
    if tool_call_id is not None:
        tool_call["id"] = tool_call_id
    return SimpleNamespace(tool_call=tool_call)


def _module(name: str, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _make_app_config(
    *,
    supports_vision: bool = False,
    guardrails: GuardrailsConfig | None = None,
    loop_detection: LoopDetectionConfig | None = None,
    tool_progress: ToolProgressConfig | None = None,
) -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="test-model",
                display_name="test-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="test-model",
                supports_vision=supports_vision,
            )
        ],
        sandbox=SandboxConfig(use="test"),
        guardrails=guardrails or GuardrailsConfig(enabled=False),
        loop_detection=loop_detection or LoopDetectionConfig(),
        tool_progress=tool_progress or ToolProgressConfig(),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=7, recovery_timeout_sec=11),
    )


def _stub_runtime_middleware_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMiddleware:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class FakeLLMErrorHandlingMiddleware:
        def __init__(self, *, app_config):
            self.app_config = app_config

    monkeypatch.setitem(
        sys.modules,
        "vassilflow.agents.middlewares.llm_error_handling_middleware",
        _module(
            "vassilflow.agents.middlewares.llm_error_handling_middleware",
            LLMErrorHandlingMiddleware=FakeLLMErrorHandlingMiddleware,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "vassilflow.agents.middlewares.thread_data_middleware",
        _module("vassilflow.agents.middlewares.thread_data_middleware", ThreadDataMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "vassilflow.sandbox.middleware",
        _module("vassilflow.sandbox.middleware", SandboxMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "vassilflow.agents.middlewares.dangling_tool_call_middleware",
        _module("vassilflow.agents.middlewares.dangling_tool_call_middleware", DanglingToolCallMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "vassilflow.agents.middlewares.sandbox_audit_middleware",
        _module("vassilflow.agents.middlewares.sandbox_audit_middleware", SandboxAuditMiddleware=FakeMiddleware),
    )


def test_build_subagent_runtime_middlewares_threads_app_config_to_llm_middleware(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class FakeMiddleware:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class FakeLLMErrorHandlingMiddleware:
        def __init__(self, *, app_config):
            captured["app_config"] = app_config

    app_config = _make_app_config()

    monkeypatch.setitem(
        sys.modules,
        "vassilflow.agents.middlewares.llm_error_handling_middleware",
        _module(
            "vassilflow.agents.middlewares.llm_error_handling_middleware",
            LLMErrorHandlingMiddleware=FakeLLMErrorHandlingMiddleware,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "vassilflow.agents.middlewares.thread_data_middleware",
        _module("vassilflow.agents.middlewares.thread_data_middleware", ThreadDataMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "vassilflow.sandbox.middleware",
        _module("vassilflow.sandbox.middleware", SandboxMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "vassilflow.agents.middlewares.dangling_tool_call_middleware",
        _module("vassilflow.agents.middlewares.dangling_tool_call_middleware", DanglingToolCallMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "vassilflow.agents.middlewares.sandbox_audit_middleware",
        _module("vassilflow.agents.middlewares.sandbox_audit_middleware", SandboxAuditMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "vassilflow.agents.middlewares.input_sanitization_middleware",
        _module("vassilflow.agents.middlewares.input_sanitization_middleware", InputSanitizationMiddleware=FakeMiddleware),
    )

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, lazy_init=False)

    assert captured["app_config"] is app_config
    # 9 baseline (InputSanitization, ToolOutputBudget, ThreadData, Sandbox,
    # DanglingToolCall, LLMErrorHandling, SandboxAudit, ReadBeforeWrite,
    # ToolErrorHandling)
    # + 1 LoopDetectionMiddleware and + 1 SafetyFinishReasonMiddleware (enabled by default).
    from vassilflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
    from vassilflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
    from vassilflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware

    assert len(middlewares) == 11
    assert isinstance(middlewares[0], FakeMiddleware)  # InputSanitizationMiddleware stub
    assert isinstance(middlewares[1], ToolOutputBudgetMiddleware)
    assert any(isinstance(m, ToolErrorHandlingMiddleware) for m in middlewares)
    assert isinstance(middlewares[-2], LoopDetectionMiddleware)
    assert isinstance(middlewares[-1], SafetyFinishReasonMiddleware)


def test_build_subagent_runtime_middlewares_wires_tool_progress_before_error_handling(monkeypatch: pytest.MonkeyPatch):
    app_config = _make_app_config(tool_progress=ToolProgressConfig(enabled=True))
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, lazy_init=False)

    progress_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, ToolProgressMiddleware))
    error_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, ToolErrorHandlingMiddleware))
    assert progress_idx < error_idx


def test_wrap_tool_call_passthrough_on_success():
    middleware = ToolErrorHandlingMiddleware()
    req = _request()
    expected = ToolMessage(content="ok", tool_call_id="tc-1", name="web_search")

    result = middleware.wrap_tool_call(req, lambda _req: expected)

    assert result is expected
    assert result.additional_kwargs[TOOL_META_KEY]["status"] == "success"


def test_wrap_tool_call_stamps_skill_read_metadata():
    middleware = ToolErrorHandlingMiddleware()
    req = SimpleNamespace(
        tool_call={
            "name": "read_file",
            "id": "tc-skill",
            "args": {"path": "/mnt/skills/public/data-analysis/SKILL.md"},
        }
    )
    expected = ToolMessage(
        content="---\nname: data-analysis\ndescription: Analyze tabular data\n---\n# Skill\n",
        tool_call_id="tc-skill",
        name="read_file",
    )

    result = middleware.wrap_tool_call(req, lambda _req: expected)

    assert result.additional_kwargs["skill_context_entry"] == {
        "path": "/mnt/skills/public/data-analysis/SKILL.md",
        "description": "Analyze tabular data",
    }


def test_wrap_tool_call_does_not_stamp_non_skill_read_metadata():
    middleware = ToolErrorHandlingMiddleware()
    req = SimpleNamespace(
        tool_call={
            "name": "read_file",
            "id": "tc-file",
            "args": {"path": "/mnt/user-data/workspace/SKILL.md"},
        }
    )
    expected = ToolMessage(content="# Not a skill", tool_call_id="tc-file", name="read_file")

    result = middleware.wrap_tool_call(req, lambda _req: expected)

    assert "skill_context_entry" not in result.additional_kwargs


def test_wrap_tool_call_returns_error_tool_message_on_exception():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="web_search", tool_call_id="tc-42")

    def _boom(_req):
        raise RuntimeError("network down")

    result = middleware.wrap_tool_call(req, _boom)

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "tc-42"
    assert result.name == "web_search"
    assert result.status == "error"
    assert "Tool 'web_search' failed" in result.text
    assert "network down" in result.text
    assert result.additional_kwargs[TOOL_META_KEY]["status"] == "error"
    assert result.additional_kwargs[TOOL_META_KEY]["source"] == "exception"


def test_wrap_tool_call_uses_fallback_tool_call_id_when_missing():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="mcp_tool", tool_call_id=None)

    def _boom(_req):
        raise ValueError("bad request")

    result = middleware.wrap_tool_call(req, _boom)

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "missing_tool_call_id"
    assert result.name == "mcp_tool"
    assert result.status == "error"


def test_wrap_tool_call_reraises_graph_interrupt():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="ask_clarification", tool_call_id="tc-int")

    def _interrupt(_req):
        raise GraphInterrupt(())

    with pytest.raises(GraphInterrupt):
        middleware.wrap_tool_call(req, _interrupt)


@pytest.mark.anyio
async def test_awrap_tool_call_returns_error_tool_message_on_exception():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="mcp_tool", tool_call_id="tc-async")

    async def _boom(_req):
        raise TimeoutError("request timed out")

    result = await middleware.awrap_tool_call(req, _boom)

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "tc-async"
    assert result.name == "mcp_tool"
    assert result.status == "error"
    assert "request timed out" in result.text
    assert result.additional_kwargs[TOOL_META_KEY]["status"] == "error"
    assert result.additional_kwargs[TOOL_META_KEY]["source"] == "exception"


@pytest.mark.anyio
async def test_awrap_tool_call_reraises_graph_interrupt():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="ask_clarification", tool_call_id="tc-int-async")

    async def _interrupt(_req):
        raise GraphInterrupt(())

    with pytest.raises(GraphInterrupt):
        await middleware.awrap_tool_call(req, _interrupt)


def test_subagent_runtime_middlewares_include_view_image_for_vision_model(monkeypatch):
    app_config = _make_app_config(supports_vision=True)
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model")

    assert any(isinstance(middleware, ViewImageMiddleware) for middleware in middlewares)


def test_subagent_runtime_middlewares_include_view_image_for_default_vision_model(monkeypatch):
    app_config = _make_app_config(supports_vision=True)
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name=None)

    assert any(isinstance(middleware, ViewImageMiddleware) for middleware in middlewares)


def test_subagent_runtime_middlewares_skip_view_image_for_text_model(monkeypatch):
    app_config = _make_app_config(supports_vision=False)
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model")

    assert not any(isinstance(middleware, ViewImageMiddleware) for middleware in middlewares)


def test_subagent_runtime_middlewares_attach_deferred_filter_when_setup_has_names(monkeypatch):
    """A subagent built with deferred MCP tools gets DeferredToolFilterMiddleware, positioned before SafetyFinishReasonMiddleware (mirrors the lead ordering)."""
    from langchain_core.tools import tool as as_tool

    from vassilflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from vassilflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
    from vassilflow.tools.builtins.tool_search import build_deferred_tool_setup
    from vassilflow.tools.mcp_metadata import tag_mcp_tool

    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)

    @as_tool
    def mcp_thing(x: str) -> str:
        "deferred mcp tool"
        return x

    setup = build_deferred_tool_setup([tag_mcp_tool(mcp_thing)], enabled=True)
    assert setup.deferred_names  # sanity: populated setup

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, deferred_setup=setup)

    filters = [m for m in middlewares if isinstance(m, DeferredToolFilterMiddleware)]
    assert len(filters) == 1
    filter_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, DeferredToolFilterMiddleware))
    safety_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, SafetyFinishReasonMiddleware))
    assert filter_idx < safety_idx


def test_subagent_runtime_middlewares_skip_deferred_filter_without_names(monkeypatch):
    """No deferred setup (disabled / no MCP tool) -> no DeferredToolFilterMiddleware."""
    from vassilflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from vassilflow.tools.builtins.tool_search import DeferredToolSetup

    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)

    for setup in (None, DeferredToolSetup(None, frozenset(), None)):
        middlewares = build_subagent_runtime_middlewares(app_config=app_config, deferred_setup=setup)
        assert not any(isinstance(m, DeferredToolFilterMiddleware) for m in middlewares)


def test_subagent_runtime_middlewares_include_loop_detection_before_safety(monkeypatch):
    from vassilflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
    from vassilflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config)

    loop_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, LoopDetectionMiddleware))
    safety_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, SafetyFinishReasonMiddleware))
    assert loop_idx < safety_idx


def test_subagent_runtime_middlewares_skip_loop_detection_when_disabled(monkeypatch):
    from vassilflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

    app_config = _make_app_config(loop_detection=LoopDetectionConfig(enabled=False))
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config)

    assert not any(isinstance(m, LoopDetectionMiddleware) for m in middlewares)


def test_guardrail_provider_framework_hint_defaults_to_vassilflow(monkeypatch):
    from vassilflow.guardrails.provider import GuardrailDecision

    captured: dict[str, object] = {}

    class FakeGuardrailProvider:
        name = "fake"

        def __init__(self, *, framework: str):
            captured["framework"] = framework

        def evaluate(self, request):
            return GuardrailDecision(allow=True)

        async def aevaluate(self, request):
            return GuardrailDecision(allow=True)

    monkeypatch.setitem(
        sys.modules,
        "test_guardrails_provider",
        _module("test_guardrails_provider", FakeGuardrailProvider=FakeGuardrailProvider),
    )
    _stub_runtime_middleware_imports(monkeypatch)
    app_config = _make_app_config(
        guardrails=GuardrailsConfig.model_validate(
            {
                "enabled": True,
                "provider": {"use": "test_guardrails_provider:FakeGuardrailProvider"},
            }
        )
    )

    build_subagent_runtime_middlewares(app_config=app_config)

    assert captured["framework"] == "vassilflow"


def test_guardrail_provider_framework_hint_can_be_overridden(monkeypatch):
    from vassilflow.guardrails.provider import GuardrailDecision

    captured: dict[str, object] = {}

    class FakeGuardrailProvider:
        name = "fake"

        def __init__(self, *, framework: str):
            captured["framework"] = framework

        def evaluate(self, request):
            return GuardrailDecision(allow=True)

        async def aevaluate(self, request):
            return GuardrailDecision(allow=True)

    monkeypatch.setitem(
        sys.modules,
        "test_guardrails_provider",
        _module("test_guardrails_provider", FakeGuardrailProvider=FakeGuardrailProvider),
    )
    _stub_runtime_middleware_imports(monkeypatch)
    app_config = _make_app_config(
        guardrails=GuardrailsConfig.model_validate(
            {
                "enabled": True,
                "provider": {
                    "use": "test_guardrails_provider:FakeGuardrailProvider",
                    "config": {"framework": "vassilflow"},
                },
            }
        )
    )

    build_subagent_runtime_middlewares(app_config=app_config)

    assert captured["framework"] == "vassilflow"
