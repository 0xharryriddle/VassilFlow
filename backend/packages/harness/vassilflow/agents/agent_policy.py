"""Resolve and apply Agent capability policies to assembled tools."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from vassilflow.config.agent_contract import (
    AgentRuntimePolicy,
    serialize_agent_runtime_policy,
)
from vassilflow.tools.mcp_metadata import is_mcp_tool

if TYPE_CHECKING:
    from vassilflow.config.agents_config import AgentConfig
    from vassilflow.config.app_config import AppConfig
    from vassilflow.config.builtin_agents import BuiltinAgentDefinition


# Framework tools are inert unless their owning middleware/config enables them.
# Keeping this list explicit prevents MCP, ACP, skill-management, and future
# global tools from leaking through a custom Agent's tool-group boundary.
CUSTOM_AGENT_FRAMEWORK_TOOLS = frozenset(
    {
        "ask_clarification",
        "describe_skill",
        "present_files",
        "task",
        "tool_search",
        "update_agent",
        "view_image",
        "write_todos",
    }
)


def resolve_agent_runtime_policy(
    *,
    agent_config: AgentConfig | None,
    builtin_agent: BuiltinAgentDefinition | None,
    app_config: AppConfig,
) -> AgentRuntimePolicy | None:
    """Build the effective policy from the canonical Agent definition."""

    if builtin_agent is not None:
        return builtin_agent.to_runtime_policy()
    if agent_config is None or agent_config.tool_groups is None:
        return None

    groups = frozenset(agent_config.tool_groups)
    configured = {tool.name for tool in app_config.tools if tool.group in groups}
    return AgentRuntimePolicy(
        allowed_tool_names=frozenset(configured | CUSTOM_AGENT_FRAMEWORK_TOOLS),
        data_access=None,
    )


def filter_tools_by_agent_policy(
    tools: Iterable[BaseTool],
    policy: AgentRuntimePolicy | None,
) -> list[BaseTool]:
    """Filter the complete tool assembly using the Agent's exact allowlist."""

    values = list(tools)
    if policy is None:
        return values
    return [tool for tool in values if is_tool_allowed_by_agent_policy(tool, policy)]


def is_tool_allowed_by_agent_policy(
    tool: BaseTool | object,
    policy: AgentRuntimePolicy,
) -> bool:
    """Apply name and provenance constraints to one assembled tool."""

    name = getattr(tool, "name", None)
    allowed = policy.allowed_tool_names
    if allowed is not None and name not in allowed:
        return False
    if is_mcp_tool(tool) and not policy.allow_mcp_tools:
        return False
    if name == "invoke_acp_agent" and not policy.allow_acp_agents:
        return False
    return True


def inject_agent_runtime_policy(
    config: dict,
    policy: AgentRuntimePolicy | None,
) -> None:
    """Expose the server-owned policy to tools and delegated executions."""

    if policy is None:
        return
    serialized = serialize_agent_runtime_policy(policy)
    metadata = config.setdefault("metadata", {})
    metadata.update(serialized)

    context = config.setdefault("context", {})
    if isinstance(context, dict):
        context["agent_policy"] = dict(serialized)

    configurable = config.get("configurable")
    runtime = configurable.get("__pregel_runtime") if isinstance(configurable, dict) else None
    runtime_context = getattr(runtime, "context", None)
    if isinstance(runtime_context, dict):
        runtime_context["agent_policy"] = dict(serialized)
