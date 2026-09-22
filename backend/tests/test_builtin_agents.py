from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.gateway.agent_catalog import build_builtin_agent_product
from vassilflow.capabilities import CapabilityReadinessCheck
from vassilflow.config.agents_config import AgentConfig
from vassilflow.config.app_config import AppConfig
from vassilflow.config.builtin_agents import (
    BuiltinAgentUnavailableError,
    evaluate_builtin_agent,
    get_builtin_agent,
    list_builtin_agents,
    resolve_builtin_agent_config,
)
from vassilflow.config.sandbox_config import SandboxConfig
from vassilflow.config.tool_config import ToolConfig

SAMPLE_TOOL_PROVIDERS = {
    "sample_inspect": "sample_agent_fixture:sample_inspect_tool",
    "sample_generate": "sample_agent_fixture:sample_generate_tool",
    "sample_edit": "sample_agent_fixture:sample_edit_tool",
    "sample_render": "sample_agent_fixture:sample_render_tool",
}


def _config(*tools: tuple[str, str]) -> AppConfig:
    return AppConfig(
        sandbox=SandboxConfig(use="test"),
        tools=[
            ToolConfig(
                name=name,
                group=group,
                use=SAMPLE_TOOL_PROVIDERS[name],
            )
            for name, group in tools
        ],
    )


def _sample_config() -> AppConfig:
    return _config(
        ("sample_inspect", "file:read"),
        ("sample_generate", "file:write"),
        ("sample_edit", "file:write"),
        ("sample_render", "file:write"),
    )


def test_sample_registry_is_stable_and_server_owned() -> None:
    agents = list_builtin_agents()

    assert [agent.name for agent in agents] == ["sample"]
    sample = get_builtin_agent("SAMPLE")
    assert sample is not None
    assert sample.required_tools == (
        "sample_inspect",
        "sample_generate",
        "sample_edit",
        "sample_render",
    )
    assert set(sample.required_tools).issubset(sample.allowed_tools)
    assert sample.tool_groups == ("file:read", "file:write")
    assert sample.launch_kind == "project"
    assert sample.launch_path == "/workspace/sample"
    assert sample.project_kind == "sample"
    assert sample.capability_adapters == ("sample_agent_fixture:SampleAgentCapabilityAdapter",)
    assert sample.chat_extension == "sample-selection"


def test_sample_availability_requires_tools_inside_runtime_groups() -> None:
    sample = get_builtin_agent("sample")
    assert sample is not None

    available = evaluate_builtin_agent(sample, _sample_config())
    wrong_group = evaluate_builtin_agent(
        sample,
        _config(
            ("sample_inspect", "file:read"),
            ("sample_generate", "file:write"),
            ("sample_edit", "file:write"),
            ("sample_render", "other"),
        ),
    )

    assert available.available is True
    assert available.missing_tools == ()
    assert wrong_group.available is False
    assert wrong_group.missing_tools == ("sample_render",)


def test_sample_availability_rejects_unresolvable_tool_provider() -> None:
    sample = get_builtin_agent("sample")
    assert sample is not None
    config = _sample_config()
    config.tools[3] = ToolConfig(
        name="sample_render",
        group="file:write",
        use="sample_agent_fixture:missing_tool",
    )

    availability = evaluate_builtin_agent(sample, config)

    assert availability.available is False
    assert availability.missing_tools == ("sample_render",)


def test_sample_runtime_config_is_resolved_without_user_files() -> None:
    config = resolve_builtin_agent_config("sample", _sample_config())

    assert config is not None
    assert config.name == "sample"
    assert config.tool_groups == ["file:read", "file:write"]
    assert config.skills == ["sample-skill"]


def test_sample_runtime_fails_closed_when_capabilities_are_missing() -> None:
    with pytest.raises(BuiltinAgentUnavailableError, match="sample_render"):
        resolve_builtin_agent_config(
            "sample",
            _config(
                ("sample_inspect", "file:read"),
                ("sample_edit", "file:write"),
            ),
        )


def test_sample_product_launch_reflects_runtime_availability() -> None:
    sample = get_builtin_agent("sample")
    assert sample is not None

    available = build_builtin_agent_product(sample, _sample_config())
    unavailable = build_builtin_agent_product(sample, _config())

    assert available.model_dump()["launch"] == {
        "kind": "project",
        "path": "/workspace/sample",
        "project_kind": "sample",
    }
    assert available.status == "available"
    assert available.chat_extension == "sample-selection"
    assert available.management.can_delete is False
    assert unavailable.status == "unavailable"
    assert unavailable.missing_requirements == [
        "sample_inspect",
        "sample_generate",
        "sample_edit",
        "sample_render",
    ]


def test_sample_product_distinguishes_degraded_and_required_readiness() -> None:
    sample = get_builtin_agent("sample")
    assert sample is not None
    renderer = CapabilityReadinessCheck(
        key="sample.renderer",
        status="unavailable",
        required=False,
        detail="Renderer unavailable.",
    )
    repository = CapabilityReadinessCheck(
        key="sample.projects",
        status="unavailable",
        required=True,
        detail="Project storage unavailable.",
    )

    degraded = build_builtin_agent_product(
        sample,
        _sample_config(),
        readiness=(renderer,),
    )
    unavailable = build_builtin_agent_product(
        sample,
        _sample_config(),
        readiness=(renderer, repository),
    )

    assert degraded.status == "degraded"
    assert degraded.degraded_requirements == ["sample.renderer"]
    assert degraded.missing_requirements == []
    assert degraded.readiness[0].detail == "Renderer unavailable."
    assert unavailable.status == "unavailable"
    assert unavailable.missing_requirements == ["sample.projects"]
    assert unavailable.degraded_requirements == ["sample.renderer"]


def test_assistants_compat_deduplicates_builtin_and_custom_ids(monkeypatch) -> None:
    from app.gateway.routers import assistants_compat
    from vassilflow.config import agents_config

    monkeypatch.setattr(assistants_compat, "get_app_config", _sample_config)
    monkeypatch.setattr(
        agents_config,
        "list_custom_agents",
        lambda: [AgentConfig(name="sample"), AgentConfig(name="writer")],
    )

    assistant_ids = [assistant.assistant_id for assistant in assistants_compat._list_assistants()]

    assert assistant_ids == ["lead_agent", "sample", "writer"]


def test_sample_runtime_uses_builtin_profile_without_update_tool(monkeypatch) -> None:
    from vassilflow.agents.lead_agent import agent as lead_agent_module

    app_config = MagicMock()
    app_config.tools = _sample_config().tools
    app_config.get_model_config.return_value = SimpleNamespace(
        supports_thinking=False,
        supports_vision=False,
    )
    app_config.tool_search.enabled = False
    app_config.skills.deferred_discovery = False
    app_config.skills.container_path = "/mnt/skills"

    seen_groups: list[list[str] | None] = []
    captured_prompt: dict[str, object] = {}
    captured_middlewares: dict[str, object] = {}

    def get_tools(**kwargs):
        seen_groups.append(kwargs.get("groups"))
        return [
            SimpleNamespace(name=name)
            for name in (
                "sample_inspect",
                "sample_generate",
                "sample_edit",
                "sample_render",
            )
        ]

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda *args, **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr(
        lead_agent_module,
        "build_middlewares",
        lambda *args, **kwargs: captured_middlewares.update(kwargs) or [],
    )
    monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        lead_agent_module,
        "_load_enabled_skills_for_tool_policy",
        lambda available_skills, *, app_config: [],
    )
    monkeypatch.setattr(
        lead_agent_module,
        "apply_prompt_template",
        lambda **kwargs: captured_prompt.update(kwargs) or "prompt",
    )
    monkeypatch.setattr("vassilflow.tools.get_available_tools", get_tools)

    result = lead_agent_module._make_lead_agent(
        {"configurable": {"agent_name": "sample"}},
        app_config=app_config,
    )

    assert seen_groups == [["file:read", "file:write"]]
    assert [tool.name for tool in result["tools"]] == [
        "sample_inspect",
        "sample_generate",
        "sample_edit",
        "sample_render",
    ]
    assert captured_prompt["agent_name"] == "sample"
    assert captured_prompt["available_skills"] == {"sample-skill"}
    assert [type(middleware).__name__ for middleware in captured_middlewares["capability_middlewares"]] == [
        "SampleSelectionContextMiddleware",
        "SampleSelectionApprovalMiddleware",
    ]


def test_sample_prompt_has_builtin_soul_without_custom_self_update() -> None:
    from vassilflow.agents.lead_agent.prompt import (
        _build_self_update_section,
        get_agent_soul,
    )

    soul = get_agent_soul("sample")
    assert "structured sample tools" in soul
    assert _build_self_update_section("sample") == ""


pytestmark = pytest.mark.usefixtures("sample_builtin_registry")
