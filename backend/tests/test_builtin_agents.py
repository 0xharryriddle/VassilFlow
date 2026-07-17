from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.gateway.agent_catalog import build_builtin_agent_product
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

OFFICE_TOOL_PROVIDERS = {
    "office_inspect": "vassilflow.community.office.tools:office_inspect_tool",
    "office_generate": "vassilflow.community.office.tools:office_generate_tool",
    "office_edit": "vassilflow.community.office.tools:office_edit_tool",
    "office_render": "vassilflow.community.office.tools:office_render_tool",
}


def _config(*tools: tuple[str, str]) -> AppConfig:
    return AppConfig(
        sandbox=SandboxConfig(use="test"),
        tools=[
            ToolConfig(
                name=name,
                group=group,
                use=OFFICE_TOOL_PROVIDERS[name],
            )
            for name, group in tools
        ],
    )


def _office_config() -> AppConfig:
    return _config(
        ("office_inspect", "file:read"),
        ("office_generate", "file:write"),
        ("office_edit", "file:write"),
        ("office_render", "file:write"),
    )


def test_office_registry_is_stable_and_server_owned() -> None:
    agents = list_builtin_agents()

    assert [agent.name for agent in agents] == ["office"]
    office = get_builtin_agent("OFFICE")
    assert office is not None
    assert office.required_tools == (
        "office_inspect",
        "office_generate",
        "office_edit",
        "office_render",
    )
    assert set(office.required_tools).issubset(office.allowed_tools)
    assert office.tool_groups == ("file:read", "file:write")


def test_office_availability_requires_tools_inside_runtime_groups() -> None:
    office = get_builtin_agent("office")
    assert office is not None

    available = evaluate_builtin_agent(office, _office_config())
    wrong_group = evaluate_builtin_agent(
        office,
        _config(
            ("office_inspect", "file:read"),
            ("office_generate", "file:write"),
            ("office_edit", "file:write"),
            ("office_render", "other"),
        ),
    )

    assert available.available is True
    assert available.missing_tools == ()
    assert wrong_group.available is False
    assert wrong_group.missing_tools == ("office_render",)


def test_office_availability_rejects_unresolvable_tool_provider() -> None:
    office = get_builtin_agent("office")
    assert office is not None
    config = _office_config()
    config.tools[3] = ToolConfig(
        name="office_render",
        group="file:write",
        use="vassilflow.community.office.tools:missing_tool",
    )

    availability = evaluate_builtin_agent(office, config)

    assert availability.available is False
    assert availability.missing_tools == ("office_render",)


def test_office_runtime_config_is_resolved_without_user_files() -> None:
    config = resolve_builtin_agent_config("office", _office_config())

    assert config is not None
    assert config.name == "office"
    assert config.tool_groups == ["file:read", "file:write"]
    assert config.skills == []


def test_office_runtime_fails_closed_when_capabilities_are_missing() -> None:
    with pytest.raises(BuiltinAgentUnavailableError, match="office_render"):
        resolve_builtin_agent_config(
            "office",
            _config(
                ("office_inspect", "file:read"),
                ("office_edit", "file:write"),
            ),
        )


def test_office_product_launch_reflects_runtime_availability() -> None:
    office = get_builtin_agent("office")
    assert office is not None

    available = build_builtin_agent_product(office, _office_config())
    unavailable = build_builtin_agent_product(office, _config())

    assert available.model_dump()["launch"] == {
        "kind": "chat",
        "path": "/workspace/agents/office/chats/new",
        "project_kind": None,
    }
    assert available.status == "available"
    assert available.management.can_delete is False
    assert unavailable.status == "unavailable"
    assert unavailable.missing_requirements == [
        "office_inspect",
        "office_generate",
        "office_edit",
        "office_render",
    ]


def test_assistants_compat_deduplicates_builtin_and_custom_ids(monkeypatch) -> None:
    from app.gateway.routers import assistants_compat
    from vassilflow.config import agents_config

    monkeypatch.setattr(assistants_compat, "get_app_config", _office_config)
    monkeypatch.setattr(
        agents_config,
        "list_custom_agents",
        lambda: [AgentConfig(name="office"), AgentConfig(name="writer")],
    )

    assistant_ids = [assistant.assistant_id for assistant in assistants_compat._list_assistants()]

    assert assistant_ids == ["lead_agent", "office", "writer"]


def test_office_runtime_uses_builtin_profile_without_update_tool(monkeypatch) -> None:
    from vassilflow.agents.lead_agent import agent as lead_agent_module

    app_config = MagicMock()
    app_config.tools = _office_config().tools
    app_config.get_model_config.return_value = SimpleNamespace(
        supports_thinking=False,
        supports_vision=False,
    )
    app_config.tool_search.enabled = False
    app_config.skills.deferred_discovery = False
    app_config.skills.container_path = "/mnt/skills"

    seen_groups: list[list[str] | None] = []
    captured_prompt: dict[str, object] = {}

    def get_tools(**kwargs):
        seen_groups.append(kwargs.get("groups"))
        return [
            SimpleNamespace(name=name)
            for name in (
                "office_inspect",
                "office_generate",
                "office_edit",
                "office_render",
            )
        ]

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda *args, **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
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
        {"configurable": {"agent_name": "office"}},
        app_config=app_config,
    )

    assert seen_groups == [["file:read", "file:write"]]
    assert [tool.name for tool in result["tools"]] == [
        "office_inspect",
        "office_generate",
        "office_edit",
        "office_render",
    ]
    assert captured_prompt["agent_name"] == "office"
    assert captured_prompt["available_skills"] == set()


def test_office_prompt_has_builtin_soul_without_custom_self_update() -> None:
    from vassilflow.agents.lead_agent.prompt import (
        _build_self_update_section,
        get_agent_soul,
    )

    soul = get_agent_soul("office")
    assert "structured Office tools" in soul
    assert "analysis_mode=pptx_quality_preflight" in soul
    assert "separate from rendered visual review" in soul
    assert "versioned semantic intent" in soul
    assert "generation receipt" in soul
    assert "semantic change receipt as the source of truth" in soul
    assert "exact source/result hashes and operation IDs" in soul
    assert "pass both project_id and parent_revision_id exactly as returned" in soul
    assert "IDs must never be invented" in soul
    assert "manifest and preview pages become durable revision evidence" in soul
    assert _build_self_update_section("office") == ""
