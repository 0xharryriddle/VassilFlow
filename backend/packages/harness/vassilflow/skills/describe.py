"""Deferred skill metadata retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

from vassilflow.skills.catalog import SkillCatalog
from vassilflow.skills.types import Skill, SkillCategory

if TYPE_CHECKING:
    from langchain.tools import BaseTool


@dataclass(frozen=True)
class SkillSearchSetup:
    """Deferred skill-discovery setup for one agent build."""

    describe_skill_tool: BaseTool | None
    skill_names: frozenset[str]


def build_describe_skill_tool(
    catalog: SkillCatalog,
    *,
    container_base_path: str = "/mnt/skills",
) -> BaseTool:
    """Build a describe_skill tool over a fixed skill catalog."""

    @tool
    def describe_skill(
        name: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Fetch metadata for installed skills before loading their SKILL.md file.

        Query forms:
        - "select:data-analysis,deep-research" fetches exact names.
        - "chart visualization" searches names and descriptions.
        - "+podcast gen" requires "podcast" in the name and ranks by the rest.
        """
        matched = catalog.search(name)
        content = _render_skill_metadata(matched, container_base_path) if matched else f"No skills matched: {name}"
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=content,
                        tool_call_id=tool_call_id,
                        name="describe_skill",
                    )
                ],
            }
        )

    return describe_skill


def build_skill_search_setup(
    skills: list[Skill],
    *,
    enabled: bool,
    container_base_path: str = "/mnt/skills",
) -> SkillSearchSetup:
    if not enabled or not skills:
        return SkillSearchSetup(None, frozenset())

    catalog = SkillCatalog(tuple(skills))
    return SkillSearchSetup(
        describe_skill_tool=build_describe_skill_tool(catalog, container_base_path=container_base_path),
        skill_names=catalog.names,
    )


def _render_skill_metadata(skills: list[Skill], container_base_path: str) -> str:
    blocks: list[str] = []
    for skill in skills:
        mutability = "[custom, editable]" if skill.category == SkillCategory.CUSTOM else "[built-in]"
        tools_line = ", ".join(skill.allowed_tools) if skill.allowed_tools else "(all)"
        location = skill.get_container_file_path(container_base_path)
        blocks.append(
            f"## Skill: {skill.name}\n"
            f"- Description: {skill.description} {mutability}\n"
            f"- Allowed tools: {tools_line}\n"
            f"- Location: {location}"
        )
    return "\n\n".join(blocks)


def get_skill_index_prompt_section(
    *,
    skill_names: frozenset[str] = frozenset(),
    container_base_path: str = "/mnt/skills",
    skill_evolution_section: str = "",
) -> str:
    if not skill_names:
        return ""

    names = ", ".join(sorted(skill_names))
    evolution = f"\n{skill_evolution_section}" if skill_evolution_section else ""

    return f"""<skill_system>
You have access to skills that provide optimized workflows for specific tasks.

**Skill Discovery:**
1. Check <skill_index> for a skill name that matches your task
2. Call describe_skill(name) to fetch its description and capabilities
3. If the skill matches, call read_file on the returned location to load full instructions
4. Follow the skill's instructions precisely

**Explicit Slash Skill Activation:**
- If the user starts a request with `/<skill-name>`, that skill was explicitly requested.
- The runtime injects the activated skill content; do not call `read_file` for that SKILL.md again unless the injected skill references supporting resources you need.
{evolution}
<skill_index>
{names}
</skill_index>

Skills are located at: {container_base_path}
</skill_system>"""
