"""Server-owned runtime registry for curated VassilFlow Agents."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from langchain.tools import BaseTool

from vassilflow.config.agent_contract import (
    AgentDataAccess,
    AgentRuntimePolicy,
    resolve_agent_identity,
)
from vassilflow.config.agents_config import AgentConfig
from vassilflow.reflection import resolve_variable

if TYPE_CHECKING:
    from vassilflow.config.app_config import AppConfig
    from vassilflow.config.tool_config import ToolConfig

logger = logging.getLogger(__name__)

AgentCategory = Literal[
    "general",
    "create",
    "research",
    "build",
    "analyze",
    "automate",
    "custom",
]
AgentLaunchKind = Literal["chat", "project"]


@dataclass(frozen=True)
class BuiltinAgentDefinition:
    """Immutable product and runtime contract for one curated Agent."""

    name: str
    display_name: str
    description: str
    category: AgentCategory
    icon: str
    launch_kind: AgentLaunchKind
    launch_path: str
    project_kind: str | None
    tool_groups: tuple[str, ...]
    required_tools: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    skills: tuple[str, ...]
    data_access: tuple[AgentDataAccess, ...]
    starter_prompts: tuple[str, ...]
    capability_adapters: tuple[str, ...]
    chat_extension: str | None
    soul: str

    def __post_init__(self) -> None:
        identity = resolve_agent_identity(self.name)
        if identity.agent_name != self.name:
            raise ValueError(f"Built-in Agent name must be canonical: {self.name!r}")
        if not self.launch_path.startswith("/workspace/"):
            raise ValueError("Built-in Agent launch paths must stay inside the workspace")
        if self.launch_kind == "project" and not self.project_kind:
            raise ValueError("Project Agents must declare a project kind")
        if self.launch_kind == "chat" and self.project_kind is not None:
            raise ValueError("Chat Agents cannot declare a project kind")
        if not set(self.required_tools).issubset(self.allowed_tools):
            raise ValueError("Every required tool must also be allowed by the Agent policy")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("Agent policy tool names must be unique")
        if len(set(self.capability_adapters)) != len(self.capability_adapters):
            raise ValueError("Agent capability adapter paths must be unique")
        if (
            self.chat_extension is not None
            and re.fullmatch(
                r"[a-z][a-z0-9_.-]{0,63}",
                self.chat_extension,
            )
            is None
        ):
            raise ValueError("Agent chat extension key is invalid")

    def to_runtime_config(self) -> AgentConfig:
        """Build a fresh runtime config without creating user-owned files."""

        return AgentConfig(
            name=self.name,
            description=self.description,
            tool_groups=list(self.tool_groups),
            skills=list(self.skills),
        )

    def to_runtime_policy(self) -> AgentRuntimePolicy:
        """Return the immutable capability boundary enforced by the harness."""

        return AgentRuntimePolicy(
            allowed_tool_names=frozenset(self.allowed_tools),
            data_access=frozenset(self.data_access),
        )


@dataclass(frozen=True)
class BuiltinAgentAvailability:
    """Capability evidence for advertising a built-in Agent."""

    available: bool
    missing_tools: tuple[str, ...]


class BuiltinAgentUnavailableError(ValueError):
    """Raised when a built-in Agent is invoked without its required tools."""


_BUILTIN_AGENTS: tuple[BuiltinAgentDefinition, ...] = ()
_BUILTIN_AGENTS_BY_NAME = {agent.name: agent for agent in _BUILTIN_AGENTS}


def list_builtin_agents() -> tuple[BuiltinAgentDefinition, ...]:
    """Return curated Agents in deterministic catalog order."""

    return _BUILTIN_AGENTS


def get_builtin_agent(name: str | None) -> BuiltinAgentDefinition | None:
    """Resolve a built-in Agent by its stable runtime name."""

    if not name:
        return None
    return _BUILTIN_AGENTS_BY_NAME.get(name.lower())


def is_builtin_agent(name: str | None) -> bool:
    return get_builtin_agent(name) is not None


def _configured_tool_is_launchable(
    tool_config: ToolConfig,
    definition: BuiltinAgentDefinition,
) -> bool:
    if tool_config.group not in definition.tool_groups:
        return False
    try:
        tool = resolve_variable(tool_config.use, BaseTool)
    except Exception:
        logger.warning(
            "Built-in Agent %r could not load required tool %r from %s",
            definition.name,
            tool_config.name,
            tool_config.use,
            exc_info=True,
        )
        return False
    if tool.name != tool_config.name:
        logger.warning(
            "Built-in Agent %r requires tool %r, but provider %s exposes %r",
            definition.name,
            tool_config.name,
            tool_config.use,
            tool.name,
        )
        return False
    return True


def evaluate_builtin_agent(
    definition: BuiltinAgentDefinition,
    app_config: AppConfig,
) -> BuiltinAgentAvailability:
    """Check that required tools are configured inside the Agent's tool groups."""

    configured_tools = {tool.name: tool for tool in app_config.tools}
    missing_tools = tuple(
        tool_name
        for tool_name in definition.required_tools
        if (
            tool_name not in configured_tools
            or not _configured_tool_is_launchable(
                configured_tools[tool_name],
                definition,
            )
        )
    )
    return BuiltinAgentAvailability(
        available=not missing_tools,
        missing_tools=missing_tools,
    )


def resolve_builtin_agent_config(
    name: str | None,
    app_config: AppConfig,
) -> AgentConfig | None:
    """Resolve a launchable built-in runtime config, failing closed when incomplete."""

    definition = get_builtin_agent(name)
    if definition is None:
        return None
    availability = evaluate_builtin_agent(definition, app_config)
    if not availability.available:
        missing = ", ".join(availability.missing_tools)
        message = f"Built-in Agent '{definition.name}' is unavailable because required tools are missing or outside its runtime groups: {missing}"
        raise BuiltinAgentUnavailableError(message)
    return definition.to_runtime_config()


def load_builtin_agent_soul(name: str | None) -> str | None:
    definition = get_builtin_agent(name)
    return definition.soul if definition is not None else None
