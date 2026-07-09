from pathlib import Path

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from vassilflow.skills.catalog import SkillCatalog
from vassilflow.skills.describe import build_describe_skill_tool, get_skill_index_prompt_section
from vassilflow.skills.types import Skill, SkillCategory


def _skill(name: str, description: str, *, allowed_tools: list[str] | None = None) -> Skill:
    return Skill(
        name=name,
        description=description,
        license=None,
        skill_dir=Path(f"/tmp/{name}"),
        skill_file=Path(f"/tmp/{name}/SKILL.md"),
        relative_path=Path(name),
        category=SkillCategory.PUBLIC,
        allowed_tools=allowed_tools,
        enabled=True,
    )


def test_skill_catalog_searches_exact_and_free_text():
    data = _skill("data-analysis", "Analyze CSV and spreadsheet data")
    podcast = _skill("podcast-generation", "Generate audio scripts")
    catalog = SkillCatalog((data, podcast))

    assert catalog.search("select:podcast-generation") == [podcast]
    assert catalog.search("spreadsheet") == [data]
    assert catalog.search("+podcast scripts") == [podcast]


def test_describe_skill_tool_returns_metadata_command():
    skill = _skill("data-analysis", "Analyze CSV files", allowed_tools=["read_file", "python"])
    tool = build_describe_skill_tool(SkillCatalog((skill,)), container_base_path="/mnt/skills")

    result = tool.invoke(
        {
            "type": "tool_call",
            "name": "describe_skill",
            "args": {"name": "select:data-analysis"},
            "id": "call-1",
        }
    )

    assert isinstance(result, Command)
    messages = result.update["messages"]
    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call-1"
    assert "## Skill: data-analysis" in message.content
    assert "Allowed tools: read_file, python" in message.content
    assert "Location: /mnt/skills/public/data-analysis/SKILL.md" in message.content


def test_skill_index_prompt_lists_names_without_full_metadata():
    section = get_skill_index_prompt_section(skill_names=frozenset({"skill-b", "skill-a"}))

    assert "<skill_index>" in section
    assert "skill-a, skill-b" in section
    assert "describe_skill" in section
    assert "<available_skills>" not in section
