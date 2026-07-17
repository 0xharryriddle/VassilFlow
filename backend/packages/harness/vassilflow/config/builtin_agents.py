"""Server-owned runtime registry for curated VassilFlow Agents."""

from __future__ import annotations

import logging
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


@dataclass(frozen=True)
class BuiltinAgentDefinition:
    """Immutable product and runtime contract for one curated Agent."""

    name: str
    display_name: str
    description: str
    category: AgentCategory
    icon: str
    tool_groups: tuple[str, ...]
    required_tools: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    skills: tuple[str, ...]
    data_access: tuple[AgentDataAccess, ...]
    starter_prompts: tuple[str, ...]
    soul: str

    def __post_init__(self) -> None:
        identity = resolve_agent_identity(self.name)
        if identity.agent_name != self.name:
            raise ValueError(f"Built-in Agent name must be canonical: {self.name!r}")
        if not set(self.required_tools).issubset(self.allowed_tools):
            raise ValueError("Every required tool must also be allowed by the Agent policy")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("Agent policy tool names must be unique")

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


OFFICE_AGENT = BuiltinAgentDefinition(
    name="office",
    display_name="Office",
    description=("Generate editable presentations and inspect, quality-check, revise, render, and review Office files."),
    category="create",
    icon="files",
    tool_groups=("file:read", "file:write"),
    required_tools=(
        "office_inspect",
        "office_generate",
        "office_edit",
        "office_render",
    ),
    allowed_tools=(
        "office_inspect",
        "office_generate",
        "office_edit",
        "office_render",
        "ls",
        "read_file",
        "glob",
        "grep",
        "write_file",
        "str_replace",
        "present_files",
        "ask_clarification",
        "view_image",
        "write_todos",
    ),
    skills=(),
    data_access=("thread_uploads", "thread_workspace", "thread_outputs"),
    starter_prompts=(
        "Create a native editable PowerPoint presentation from a structured brief.",
        "Inspect an uploaded Office file and summarize its structure.",
        "Run a source-bound quality preflight on an uploaded PowerPoint file.",
        "Revise formatting in an uploaded document without changing the source file.",
        "Render an Office output and perform visual QA before presenting it.",
    ),
    soul="""You are Office, VassilFlow's specialist for DOCX, XLSX, and PPTX work.

Use the structured Office tools as the source of truth. Inspect before editing,
write revisions to a distinct workspace or output path, validate every committed
package, and render the complete result before presenting it. For static PPTX
quality checks, call office_inspect with analysis_mode=pptx_quality_preflight and
keep its findings and explicit unknowns separate from rendered visual review.
For a new presentation, translate the brief into the versioned semantic intent
accepted by office_generate. Use stable lowercase slide and element IDs, one of
the supported semantic layouts, real text, explicit image alt text, and bounded
theme tokens. Do not invent coordinates, raw XML, or unsupported object types.
Treat the generation receipt as the exact mapping from intent IDs to native
object paths. Keep the returned project and revision IDs, call office_render for
that exact revision, and review every rendered slide before delivery.
After every office_edit, treat its semantic change receipt as the source of truth:
retain the exact source/result hashes and operation IDs, and report only object
paths, relationship/part changes, and semantic deltas present in that receipt.
Keep the returned project and current revision IDs. For the next edit in the
same project, pass both project_id and parent_revision_id exactly as returned;
omitting both starts a separate project, and IDs must never be invented.
When trusted Office selection context is present, translate the requested change
into concrete operations limited to its object_path and allowed_operations, then
call office_edit with source_path=null. The runtime pauses before mutation and
shows the exact proposal for one-time user approval. After approval, reissue the
same arguments unchanged; after cancellation, do not retry. Omit project IDs or
pass only the exact project_id and revision_id supplied by that context. Never
expand a selected-object request to a sibling, ancestor, or slide background.
When rendering a project revision, pass its project_id and revision_id to
office_render so the manifest and preview pages become durable revision evidence.
When image review is available, inspect every rendered page. Otherwise state
that external visual review is still required. Never claim a visual check passed
without that evidence. Preserve user source files and report exact output paths
and material changes.""",
)

_BUILTIN_AGENTS = (OFFICE_AGENT,)
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
