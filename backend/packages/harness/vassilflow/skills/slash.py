from __future__ import annotations

import re
from dataclasses import dataclass

from vassilflow.skills.types import Skill, skill_reference_matches

RESERVED_SLASH_SKILL_NAMES = frozenset({"bootstrap", "help", "memory", "models", "new", "status"})
_SLASH_SKILL_RE = re.compile(r"^/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s+|$)")


@dataclass(frozen=True, slots=True)
class SlashSkillReference:
    """Parsed slash-skill command with the skill name and remaining task text."""

    name: str
    remaining_text: str


@dataclass(frozen=True, slots=True)
class ResolvedSlashSkill:
    """Slash-skill activation resolved against enabled runtime-visible skills."""

    skill: Skill
    remaining_text: str
    container_file_path: str


def parse_slash_skill_reference(text: str) -> SlashSkillReference | None:
    """Parse strict `/skill-name task` syntax, ignoring reserved control commands."""
    match = _SLASH_SKILL_RE.match(text)
    if not match:
        return None
    name = match.group(1)
    if name in RESERVED_SLASH_SKILL_NAMES:
        return None
    return SlashSkillReference(
        name=name,
        remaining_text=text[match.end() :].lstrip(),
    )


def resolve_slash_skill(
    text: str,
    skills: list[Skill],
    *,
    available_skills: set[str] | None = None,
    container_base_path: str = "/mnt/skills",
) -> ResolvedSlashSkill | None:
    """Resolve text into an enabled, whitelisted skill activation if possible."""
    reference = parse_slash_skill_reference(text)
    if reference is None:
        return None

    def is_available(skill: Skill) -> bool:
        return available_skills is None or any(skill_reference_matches(skill.name, skill.category, allowed) for allowed in available_skills)

    matches = [candidate for candidate in skills if candidate.name == reference.name and candidate.enabled and is_available(candidate)]
    if len(matches) != 1:
        return None
    skill = matches[0]

    return ResolvedSlashSkill(
        skill=skill,
        remaining_text=reference.remaining_text,
        container_file_path=skill.get_container_file_path(container_base_path),
    )
