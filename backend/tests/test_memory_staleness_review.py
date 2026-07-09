"""Tests for staleness review in the memory updater."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from vassilflow.agents.memory.updater import (
    MemoryUpdater,
    _build_staleness_section,
    _normalize_memory_update_data,
    _parse_fact_datetime,
    _select_stale_candidates,
)
from vassilflow.config.memory_config import MemoryConfig


def _memory_config(**overrides: object) -> MemoryConfig:
    config = MemoryConfig()
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _make_fact(
    fact_id: str,
    content: str = "test content",
    category: str = "knowledge",
    confidence: float = 0.9,
    days_ago: int = 100,
) -> dict:
    created = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {
        "id": fact_id,
        "content": content,
        "category": category,
        "confidence": confidence,
        "createdAt": created,
        "source": "thread-test",
    }


def _make_memory(facts: list[dict] | None = None) -> dict:
    return {
        "version": "1.0",
        "lastUpdated": "",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": facts or [],
    }


class TestParseFactDatetime:
    def test_z_suffix(self):
        result = _parse_fact_datetime("2025-06-01T12:00:00Z")
        assert result is not None
        assert result.year == 2025
        assert result.month == 6

    def test_offset_format(self):
        result = _parse_fact_datetime("2025-06-01T12:00:00+00:00")
        assert result is not None
        assert result.year == 2025

    def test_invalid_values(self):
        assert _parse_fact_datetime("") is None
        assert _parse_fact_datetime("not-a-date") is None

    def test_naive_datetime_gets_utc(self):
        result = _parse_fact_datetime("2025-06-01T12:00:00")
        assert result is not None
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0


class TestSelectStaleCandidates:
    def test_old_facts_selected(self):
        memory = _make_memory(
            [
                _make_fact("fact_old", days_ago=100),
                _make_fact("fact_new", days_ago=10),
            ]
        )
        candidates = _select_stale_candidates(memory, _memory_config(staleness_age_days=90))
        assert [fact["id"] for fact in candidates] == ["fact_old"]

    def test_protected_category_excluded(self):
        memory = _make_memory(
            [
                _make_fact("fact_correction", category="correction", days_ago=200),
                _make_fact("fact_knowledge", category="knowledge", days_ago=200),
            ]
        )
        candidates = _select_stale_candidates(
            memory,
            _memory_config(staleness_age_days=90, staleness_protected_categories=["correction"]),
        )
        assert [fact["id"] for fact in candidates] == ["fact_knowledge"]

    def test_custom_protected_categories(self):
        memory = _make_memory([_make_fact("fact_goal", category="goal", days_ago=200)])
        candidates = _select_stale_candidates(
            memory,
            _memory_config(staleness_age_days=90, staleness_protected_categories=["goal"]),
        )
        assert candidates == []

    def test_malformed_created_at_skipped(self):
        memory = _make_memory(
            [
                {
                    "id": "fact_bad_date",
                    "content": "bad date",
                    "category": "knowledge",
                    "confidence": 0.8,
                    "createdAt": "not-a-date",
                }
            ]
        )
        candidates = _select_stale_candidates(memory, _memory_config(staleness_age_days=90))
        assert candidates == []


class TestBuildStalenessSection:
    def test_empty_candidates(self):
        assert _build_staleness_section([], 90) == ""

    def test_includes_fact_details(self):
        section = _build_staleness_section(
            [_make_fact("fact_vue", "User uses Vue.js", "knowledge", 0.95, days_ago=120)],
            90,
        )
        assert "Staleness Review" in section
        assert "fact_vue" in section
        assert "User uses Vue.js" in section
        assert "0.95" in section
        assert "90 days" in section
        assert "<stale_facts>" in section


class TestApplyUpdatesStaleness:
    def test_stale_facts_removed(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_keep", "User knows Python", days_ago=100),
                _make_fact("fact_stale", "User uses Vue.js", days_ago=120),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [{"id": "fact_stale", "reason": "User switched to React"}],
        }

        with patch(
            "vassilflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, staleness_max_removals_per_cycle=10),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert [fact["id"] for fact in result["facts"]] == ["fact_keep"]

    def test_safety_cap_limits_removals_to_lowest_confidence(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_high", confidence=0.95, days_ago=100),
                _make_fact("fact_mid", confidence=0.80, days_ago=100),
                _make_fact("fact_low1", confidence=0.70, days_ago=100),
                _make_fact("fact_low2", confidence=0.65, days_ago=100),
                _make_fact("fact_low3", confidence=0.60, days_ago=100),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_high", "reason": "outdated"},
                {"id": "fact_mid", "reason": "outdated"},
                {"id": "fact_low1", "reason": "outdated"},
                {"id": "fact_low2", "reason": "outdated"},
                {"id": "fact_low3", "reason": "outdated"},
            ],
        }

        with patch(
            "vassilflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, staleness_max_removals_per_cycle=2),
        ):
            result = updater._apply_updates(current_memory, update_data)

        remaining_ids = {fact["id"] for fact in result["facts"]}
        assert remaining_ids == {"fact_high", "fact_mid", "fact_low1"}

    def test_contradiction_and_staleness_removals_combined(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_keep", days_ago=10),
                _make_fact("fact_contradicted", days_ago=10),
                _make_fact("fact_stale", days_ago=200),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": ["fact_contradicted"],
            "staleFactsToRemove": [{"id": "fact_stale", "reason": "old"}],
        }

        with patch(
            "vassilflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, staleness_max_removals_per_cycle=10),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert [fact["id"] for fact in result["facts"]] == ["fact_keep"]

    def test_protected_category_fact_refused_at_apply(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_stale", category="knowledge", days_ago=200),
                _make_fact("fact_correction", category="correction", days_ago=200),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_stale", "reason": "outdated"},
                {"id": "fact_correction", "reason": "model slip"},
            ],
        }

        with patch(
            "vassilflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                staleness_age_days=90,
                staleness_max_removals_per_cycle=10,
                staleness_protected_categories=["correction"],
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert [fact["id"] for fact in result["facts"]] == ["fact_correction"]

    def test_non_aged_fact_refused_at_apply(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_stale", days_ago=200),
                _make_fact("fact_fresh", days_ago=10),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_stale", "reason": "outdated"},
                {"id": "fact_fresh", "reason": "model slip"},
            ],
        }

        with patch(
            "vassilflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, staleness_age_days=90, staleness_max_removals_per_cycle=10),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert [fact["id"] for fact in result["facts"]] == ["fact_fresh"]

    def test_guardrail_runs_when_review_disabled(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_stale", days_ago=200),
                _make_fact("fact_fresh", days_ago=5),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_stale", "reason": "model slip"},
                {"id": "fact_fresh", "reason": "model slip"},
            ],
        }

        with patch(
            "vassilflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                staleness_review_enabled=False,
                staleness_age_days=90,
                staleness_max_removals_per_cycle=10,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert [fact["id"] for fact in result["facts"]] == ["fact_fresh"]


class TestNormalizeStaleFactsToRemove:
    def test_valid_entries(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_a", "reason": "User moved offices"},
                {"id": "fact_b", "reason": "Tech stack changed"},
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["staleFactsToRemove"] == [
            {"id": "fact_a", "reason": "User moved offices"},
            {"id": "fact_b", "reason": "Tech stack changed"},
        ]

    def test_missing_or_invalid_entries_ignored(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": ["bad", 42, {"id": "", "reason": "no id"}, {"id": "fact_ok", "reason": 123}],
        }
        result = _normalize_memory_update_data(data)
        assert result["staleFactsToRemove"] == [{"id": "fact_ok", "reason": ""}]


class TestPrepareUpdatePromptStaleness:
    def test_staleness_section_included_when_triggered(self):
        updater = MemoryUpdater()
        old_facts = [_make_fact(f"fact_{i}", days_ago=100) for i in range(5)]
        memory = _make_memory(old_facts)

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello, I am using React now"

        config = _memory_config(
            enabled=True,
            staleness_review_enabled=True,
            staleness_age_days=90,
            staleness_min_candidates=3,
        )

        with (
            patch("vassilflow.agents.memory.updater.get_memory_config", return_value=config),
            patch("vassilflow.agents.memory.updater.get_memory_data", return_value=memory),
        ):
            result = updater._prepare_update_prompt(
                messages=[msg],
                agent_name=None,
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        _, prompt = result
        assert "Staleness Review" in prompt
        assert "<stale_facts>" in prompt
        assert "staleFactsToRemove" in prompt

    def test_staleness_section_omitted_when_not_triggered(self):
        updater = MemoryUpdater()
        memory = _make_memory([])

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        config = _memory_config(
            enabled=True,
            staleness_review_enabled=True,
            staleness_age_days=90,
            staleness_min_candidates=3,
        )

        with (
            patch("vassilflow.agents.memory.updater.get_memory_config", return_value=config),
            patch("vassilflow.agents.memory.updater.get_memory_data", return_value=memory),
        ):
            result = updater._prepare_update_prompt(
                messages=[msg],
                agent_name=None,
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        _, prompt = result
        assert "Staleness Review" not in prompt
        assert "<stale_facts>" not in prompt
        assert "staleFactsToRemove" in prompt

    def test_staleness_section_omitted_when_disabled(self):
        updater = MemoryUpdater()
        memory = _make_memory([_make_fact(f"fact_{i}", days_ago=200) for i in range(10)])

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        config = _memory_config(enabled=True, staleness_review_enabled=False)

        with (
            patch("vassilflow.agents.memory.updater.get_memory_config", return_value=config),
            patch("vassilflow.agents.memory.updater.get_memory_data", return_value=memory),
        ):
            result = updater._prepare_update_prompt(
                messages=[msg],
                agent_name=None,
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        _, prompt = result
        assert "Staleness Review" not in prompt
