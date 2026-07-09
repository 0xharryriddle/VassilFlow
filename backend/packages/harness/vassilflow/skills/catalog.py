"""Searchable skill catalog for deferred skill discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property

from vassilflow.skills.types import Skill

MAX_RESULTS = 5


def _compile_catalog_regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)


@dataclass(frozen=True)
class SkillCatalog:
    """Immutable catalog of skills the model can search on demand."""

    skills: tuple[Skill, ...]

    @cached_property
    def names(self) -> frozenset[str]:
        return frozenset(skill.name for skill in self.skills)

    def search(self, query: str) -> list[Skill]:
        query = query.strip()
        if not query:
            return []

        if query.startswith("select:"):
            wanted = {name.strip() for name in query[7:].split(",") if name.strip()}
            return [skill for skill in self.skills if skill.name in wanted]

        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            if not parts:
                return []
            required = parts[0].lower()
            candidates = [skill for skill in self.skills if required in skill.name.lower()]
            if len(parts) > 1:
                pattern = _compile_catalog_regex(parts[1])
                candidates.sort(key=lambda skill: _catalog_regex_score(pattern, skill), reverse=True)
            return candidates[:MAX_RESULTS]

        regex = _compile_catalog_regex(query)
        scored: list[tuple[int, Skill]] = []
        for skill in self.skills:
            searchable = f"{skill.name} {skill.description or ''}"
            if regex.search(searchable):
                scored.append((2 if regex.search(skill.name) else 1, skill))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [skill for _, skill in scored[:MAX_RESULTS]]


def _catalog_regex_score(pattern: re.Pattern[str], skill: Skill) -> int:
    return len(pattern.findall(f"{skill.name} {skill.description or ''}"))
