"""Tests for custom agent support."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from vassilflow.config.agents_api_config import AgentsApiConfig, get_agents_api_config, set_agents_api_config
from vassilflow.config.app_config import AppConfig
from vassilflow.config.sandbox_config import SandboxConfig
from vassilflow.config.tool_config import ToolConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paths(base_dir: Path):
    """Return a Paths instance pointing to base_dir."""
    from vassilflow.config.paths import Paths

    return Paths(base_dir=base_dir)


def _write_agent(base_dir: Path, name: str, config: dict, soul: str = "You are helpful.") -> None:
    """Write an agent directory with config.yaml and SOUL.md."""
    agent_dir = base_dir / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    config_copy = dict(config)
    if "name" not in config_copy:
        config_copy["name"] = name

    with open(agent_dir / "config.yaml", "w") as f:
        yaml.dump(config_copy, f)

    (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")


# ===========================================================================
# 1. Paths class – agent path methods
# ===========================================================================


class TestPaths:
    def test_agents_dir(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.agents_dir == tmp_path / "agents"

    def test_agent_dir(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.agent_dir("code-reviewer") == tmp_path / "agents" / "code-reviewer"

    def test_agent_memory_file(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.agent_memory_file("code-reviewer") == tmp_path / "agents" / "code-reviewer" / "memory.json"

    def test_user_md_file(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.user_md_file == tmp_path / "USER.md"

    def test_paths_are_different_from_global(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.memory_file != paths.agent_memory_file("my-agent")
        assert paths.memory_file == tmp_path / "memory.json"
        assert paths.agent_memory_file("my-agent") == tmp_path / "agents" / "my-agent" / "memory.json"


# ===========================================================================
# 2. AgentConfig – Pydantic parsing
# ===========================================================================


class TestAgentConfig:
    def test_minimal_config(self):
        from vassilflow.config.agents_config import AgentConfig

        cfg = AgentConfig(name="my-agent")
        assert cfg.name == "my-agent"
        assert cfg.description == ""
        assert cfg.model is None
        assert cfg.tool_groups is None

    def test_full_config(self):
        from vassilflow.config.agents_config import AgentConfig

        cfg = AgentConfig(
            name="code-reviewer",
            description="Specialized for code review",
            model="deepseek-v3",
            tool_groups=["file:read", "bash"],
        )
        assert cfg.name == "code-reviewer"
        assert cfg.model == "deepseek-v3"
        assert cfg.tool_groups == ["file:read", "bash"]

    def test_config_from_dict(self):
        from vassilflow.config.agents_config import AgentConfig

        data = {"name": "test-agent", "description": "A test", "model": "gpt-4"}
        cfg = AgentConfig(**data)
        assert cfg.name == "test-agent"
        assert cfg.model == "gpt-4"
        assert cfg.tool_groups is None


# ===========================================================================
# 3. load_agent_config
# ===========================================================================


class TestLoadAgentConfig:
    def test_load_valid_config(self, tmp_path):
        config_dict = {"name": "code-reviewer", "description": "Code review agent", "model": "deepseek-v3"}
        _write_agent(tmp_path, "code-reviewer", config_dict)

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import load_agent_config

            cfg = load_agent_config("code-reviewer")

        assert cfg.name == "code-reviewer"
        assert cfg.description == "Code review agent"
        assert cfg.model == "deepseek-v3"

    def test_load_missing_agent_raises(self, tmp_path):
        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import load_agent_config

            with pytest.raises(FileNotFoundError):
                load_agent_config("nonexistent-agent")

    def test_load_missing_config_yaml_raises(self, tmp_path):
        # Create directory without config.yaml
        (tmp_path / "agents" / "broken-agent").mkdir(parents=True)

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import load_agent_config

            with pytest.raises(FileNotFoundError):
                load_agent_config("broken-agent")

    def test_load_config_infers_name_from_dir(self, tmp_path):
        """Config without 'name' field should use directory name."""
        agent_dir = tmp_path / "agents" / "inferred-name"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text("description: My agent\n")
        (agent_dir / "SOUL.md").write_text("Hello")

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import load_agent_config

            cfg = load_agent_config("inferred-name")

        assert cfg.name == "inferred-name"

    def test_directory_identity_overrides_stale_config_name(self, tmp_path):
        agent_dir = tmp_path / "agents" / "canonical-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text(
            "name: different-agent\ndescription: Kept\n",
            encoding="utf-8",
        )

        with patch(
            "vassilflow.config.agents_config.get_paths",
            return_value=_make_paths(tmp_path),
        ):
            from vassilflow.config.agents_config import load_agent_config

            cfg = load_agent_config("canonical-agent")

        assert cfg.name == "canonical-agent"
        assert cfg.description == "Kept"

    def test_load_config_with_tool_groups(self, tmp_path):
        config_dict = {"name": "restricted", "tool_groups": ["file:read", "file:write"]}
        _write_agent(tmp_path, "restricted", config_dict)

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import load_agent_config

            cfg = load_agent_config("restricted")

        assert cfg.tool_groups == ["file:read", "file:write"]

    def test_load_config_with_skills_empty_list(self, tmp_path):
        config_dict = {"name": "no-skills-agent", "skills": []}
        _write_agent(tmp_path, "no-skills-agent", config_dict)

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import load_agent_config

            cfg = load_agent_config("no-skills-agent")

        assert cfg.skills == []

    def test_load_config_with_skills_omitted(self, tmp_path):
        config_dict = {"name": "default-skills-agent"}
        _write_agent(tmp_path, "default-skills-agent", config_dict)

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import load_agent_config

            cfg = load_agent_config("default-skills-agent")

        assert cfg.skills is None

    def test_legacy_prompt_file_field_ignored(self, tmp_path):
        """Unknown fields like the old prompt_file should be silently ignored."""
        agent_dir = tmp_path / "agents" / "legacy-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text("name: legacy-agent\nprompt_file: system.md\n")
        (agent_dir / "SOUL.md").write_text("Soul content")

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import load_agent_config

            cfg = load_agent_config("legacy-agent")

        assert cfg.name == "legacy-agent"


# ===========================================================================
# 3b. resolve_agent_dir — memory-only directory fallback (#3390)
# ===========================================================================


class TestResolveAgentDirMemoryOnlyFallback:
    """Regression tests for #3390.

    When memory is enabled, the first conversation creates a user-isolated
    agent directory containing only ``memory.json`` (no ``config.yaml``).
    On the next turn ``resolve_agent_dir`` must fall through to the legacy
    shared layout instead of returning the incomplete user directory.
    """

    def test_user_dir_with_only_memory_falls_back_to_legacy(self, tmp_path):
        """User dir has memory.json but no config.yaml → use legacy dir."""
        from vassilflow.config.agents_config import resolve_agent_dir

        # Legacy agent with full config
        legacy_dir = tmp_path / "agents" / "my-agent"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "config.yaml").write_text("name: my-agent\n", encoding="utf-8")
        (legacy_dir / "SOUL.md").write_text("legacy soul", encoding="utf-8")

        # User dir created by memory write — no config.yaml
        user_dir = tmp_path / "users" / "u1" / "agents" / "my-agent"
        user_dir.mkdir(parents=True)
        (user_dir / "memory.json").write_text("{}", encoding="utf-8")

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)), patch("vassilflow.config.agents_config.get_effective_user_id", return_value="u1"):
            result = resolve_agent_dir("my-agent", user_id="u1")

        assert result == legacy_dir

    def test_user_dir_with_config_takes_priority(self, tmp_path):
        """User dir with config.yaml should still win over legacy."""
        from vassilflow.config.agents_config import resolve_agent_dir

        # Legacy
        legacy_dir = tmp_path / "agents" / "my-agent"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "config.yaml").write_text("name: my-agent\n", encoding="utf-8")

        # User dir with full config (migrated)
        user_dir = tmp_path / "users" / "u1" / "agents" / "my-agent"
        user_dir.mkdir(parents=True)
        (user_dir / "config.yaml").write_text("name: my-agent\nmodel: gpt-4\n", encoding="utf-8")
        (user_dir / "memory.json").write_text("{}", encoding="utf-8")

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)), patch("vassilflow.config.agents_config.get_effective_user_id", return_value="u1"):
            result = resolve_agent_dir("my-agent", user_id="u1")

        assert result == user_dir

    def test_load_config_falls_back_when_user_dir_is_memory_only(self, tmp_path):
        """End-to-end: load_agent_config works when user dir only has memory.json."""
        config_dict = {"name": "my-agent", "description": "Legacy agent", "model": "deepseek-v3"}
        _write_agent(tmp_path, "my-agent", config_dict)

        # Simulate memory write creating user dir without config
        user_dir = tmp_path / "users" / "u1" / "agents" / "my-agent"
        user_dir.mkdir(parents=True)
        (user_dir / "memory.json").write_text("{}", encoding="utf-8")

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)), patch("vassilflow.config.agents_config.get_effective_user_id", return_value="u1"):
            from vassilflow.config.agents_config import load_agent_config

            cfg = load_agent_config("my-agent", user_id="u1")

        assert cfg.name == "my-agent"
        assert cfg.model == "deepseek-v3"


# ===========================================================================
# 4. load_agent_soul
# ===========================================================================


class TestLoadAgentSoul:
    def test_reads_soul_file(self, tmp_path):
        expected_soul = "You are a specialized code review expert."
        _write_agent(tmp_path, "code-reviewer", {"name": "code-reviewer"}, soul=expected_soul)

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import AgentConfig, load_agent_soul

            cfg = AgentConfig(name="code-reviewer")
            soul = load_agent_soul(cfg.name)

        assert soul == expected_soul

    def test_missing_soul_file_returns_none(self, tmp_path):
        agent_dir = tmp_path / "agents" / "no-soul"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text("name: no-soul\n")
        # No SOUL.md created

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import AgentConfig, load_agent_soul

            cfg = AgentConfig(name="no-soul")
            soul = load_agent_soul(cfg.name)

        assert soul is None

    def test_empty_soul_file_returns_none(self, tmp_path):
        agent_dir = tmp_path / "agents" / "empty-soul"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text("name: empty-soul\n")
        (agent_dir / "SOUL.md").write_text("   \n   ")

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import AgentConfig, load_agent_soul

            cfg = AgentConfig(name="empty-soul")
            soul = load_agent_soul(cfg.name)

        assert soul is None


# ===========================================================================
# 5. list_custom_agents
# ===========================================================================


class TestListCustomAgents:
    def test_empty_when_no_agents_dir(self, tmp_path):
        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        assert agents == []

    def test_discovers_multiple_agents(self, tmp_path):
        _write_agent(tmp_path, "agent-a", {"name": "agent-a"})
        _write_agent(tmp_path, "agent-b", {"name": "agent-b", "description": "B"})

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        names = [a.name for a in agents]
        assert "agent-a" in names
        assert "agent-b" in names

    def test_skips_dirs_without_config_yaml(self, tmp_path):
        # Valid agent
        _write_agent(tmp_path, "valid-agent", {"name": "valid-agent"})
        # Invalid dir (no config.yaml)
        (tmp_path / "agents" / "invalid-dir").mkdir(parents=True)

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        assert len(agents) == 1
        assert agents[0].name == "valid-agent"

    def test_skips_non_directory_entries(self, tmp_path):
        # Create the agents dir with a file (not a dir)
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "not-a-dir.txt").write_text("hello")
        _write_agent(tmp_path, "real-agent", {"name": "real-agent"})

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        assert len(agents) == 1
        assert agents[0].name == "real-agent"

    def test_returns_sorted_by_name(self, tmp_path):
        _write_agent(tmp_path, "z-agent", {"name": "z-agent"})
        _write_agent(tmp_path, "a-agent", {"name": "a-agent"})
        _write_agent(tmp_path, "m-agent", {"name": "m-agent"})

        with patch("vassilflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from vassilflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        names = [a.name for a in agents]
        assert names == sorted(names)


# ===========================================================================
# 7. Memory isolation: _get_memory_file_path
# ===========================================================================


class TestMemoryFilePath:
    def test_global_memory_path(self, tmp_path):
        """None agent_name should return global memory file."""
        from vassilflow.agents.memory.storage import FileMemoryStorage
        from vassilflow.config.memory_config import MemoryConfig

        with (
            patch("vassilflow.agents.memory.storage.get_paths", return_value=_make_paths(tmp_path)),
            patch("vassilflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")),
        ):
            storage = FileMemoryStorage()
            path = storage._get_memory_file_path(None)
        assert path == tmp_path / "memory.json"

    def test_agent_memory_path(self, tmp_path):
        """Providing agent_name should return per-agent memory file."""
        from vassilflow.agents.memory.storage import FileMemoryStorage
        from vassilflow.config.memory_config import MemoryConfig

        with (
            patch("vassilflow.agents.memory.storage.get_paths", return_value=_make_paths(tmp_path)),
            patch("vassilflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")),
        ):
            storage = FileMemoryStorage()
            path = storage._get_memory_file_path("code-reviewer")
        assert path == tmp_path / "agents" / "code-reviewer" / "memory.json"

    def test_different_paths_for_different_agents(self, tmp_path):
        from vassilflow.agents.memory.storage import FileMemoryStorage
        from vassilflow.config.memory_config import MemoryConfig

        with (
            patch("vassilflow.agents.memory.storage.get_paths", return_value=_make_paths(tmp_path)),
            patch("vassilflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")),
        ):
            storage = FileMemoryStorage()
            path_global = storage._get_memory_file_path(None)
            path_a = storage._get_memory_file_path("agent-a")
            path_b = storage._get_memory_file_path("agent-b")

        assert path_global != path_a
        assert path_global != path_b
        assert path_a != path_b


# ===========================================================================
# 8. Gateway API – Agents endpoints
# ===========================================================================


def _office_app_config() -> AppConfig:
    return AppConfig(
        sandbox=SandboxConfig(use="test"),
        tools=[
            ToolConfig(
                name="office_inspect",
                group="file:read",
                use="vassilflow.community.office.tools:office_inspect_tool",
            ),
            ToolConfig(
                name="office_generate",
                group="file:write",
                use="vassilflow.community.office.tools:office_generate_tool",
            ),
            ToolConfig(
                name="office_edit",
                group="file:write",
                use="vassilflow.community.office.tools:office_edit_tool",
            ),
            ToolConfig(
                name="office_render",
                group="file:write",
                use="vassilflow.community.office.tools:office_render_tool",
            ),
        ],
    )


def _make_test_app(tmp_path: Path):
    """Create a FastAPI app with the agents router, patching paths to tmp_path."""
    from fastapi import FastAPI

    from app.gateway.deps import get_config
    from app.gateway.routers.agents import router

    app = FastAPI()
    app.dependency_overrides[get_config] = _office_app_config
    app.include_router(router)
    return app


@pytest.fixture()
def agent_client(tmp_path):
    """TestClient with agents router, using tmp_path as base_dir."""
    import app.gateway.routers.agents as agents_router

    paths_instance = _make_paths(tmp_path)
    previous_config = AgentsApiConfig(**get_agents_api_config().model_dump())

    with patch("vassilflow.config.agents_config.get_paths", return_value=paths_instance), patch.object(agents_router, "get_paths", return_value=paths_instance):
        set_agents_api_config(AgentsApiConfig(enabled=True))
        try:
            app = _make_test_app(tmp_path)
            with TestClient(app) as client:
                client._tmp_path = tmp_path  # type: ignore[attr-defined]
                yield client
        finally:
            set_agents_api_config(previous_config)


@pytest.fixture()
def disabled_agent_client(tmp_path):
    """TestClient with agents router while the management API is disabled."""
    import app.gateway.routers.agents as agents_router

    paths_instance = _make_paths(tmp_path)
    previous_config = AgentsApiConfig(**get_agents_api_config().model_dump())

    with patch("vassilflow.config.agents_config.get_paths", return_value=paths_instance), patch.object(agents_router, "get_paths", return_value=paths_instance):
        set_agents_api_config(AgentsApiConfig(enabled=False))
        try:
            app = _make_test_app(tmp_path)
            with TestClient(app) as client:
                yield client
        finally:
            set_agents_api_config(previous_config)


class TestAgentsAPI:
    def test_list_agents_contains_available_office_builtin(self, agent_client):
        response = agent_client.get("/api/agents")
        assert response.status_code == 200
        assert response.json()["agents"] == [
            {
                "name": "office",
                "description": "Generate editable presentations and inspect, quality-check, revise, render, and review Office files.",
                "model": None,
                "tool_groups": ["file:read", "file:write"],
                "skills": [],
                "soul": response.json()["agents"][0]["soul"],
                "product": {
                    "id": "builtin:office",
                    "display_name": "Office",
                    "origin": "builtin",
                    "category": "create",
                    "icon": "files",
                    "status": "available",
                    "required_tools": [
                        "office_inspect",
                        "office_generate",
                        "office_edit",
                        "office_render",
                    ],
                    "missing_requirements": [],
                    "data_access": [
                        "thread_uploads",
                        "thread_workspace",
                        "thread_outputs",
                    ],
                    "starter_prompts": [
                        "Create a native editable PowerPoint presentation from a structured brief.",
                        "Inspect an uploaded Office file and summarize its structure.",
                        "Run a source-bound quality preflight on an uploaded PowerPoint file.",
                        "Revise formatting in an uploaded document without changing the source file.",
                        "Render an Office output and perform visual QA before presenting it.",
                    ],
                    "launch": {
                        "kind": "chat",
                        "path": "/workspace/agents/office/chats/new",
                        "project_kind": None,
                    },
                    "management": {
                        "can_edit": False,
                        "can_delete": False,
                    },
                },
            }
        ]

    def test_get_office_builtin(self, agent_client):
        response = agent_client.get("/api/agents/office")

        assert response.status_code == 200
        assert response.json()["product"]["id"] == "builtin:office"
        assert response.json()["product"]["status"] == "available"

    def test_catalog_includes_personal_metadata_without_soul(self, agent_client):
        agent_client.post(
            "/api/agents",
            json={"name": "catalog-agent", "soul": "private prompt"},
        )

        response = agent_client.get("/api/agent-catalog")

        assert response.status_code == 200
        assert response.json()["custom_agent_management_enabled"] is True
        agents = {agent["name"]: agent for agent in response.json()["agents"]}
        assert agents["office"]["product"]["origin"] == "builtin"
        assert agents["catalog-agent"]["product"]["origin"] == "personal"
        assert agents["catalog-agent"]["soul"] is None

    def test_office_name_is_reserved(self, agent_client):
        check = agent_client.get("/api/agents/check?name=Office")
        create = agent_client.post(
            "/api/agents",
            json={"name": "office", "soul": "replace built-in"},
        )
        update = agent_client.put(
            "/api/agents/office",
            json={"description": "replace built-in"},
        )
        delete = agent_client.delete("/api/agents/office")

        assert check.json() == {"available": False, "name": "office"}
        assert create.status_code == 409
        assert update.status_code == 403
        assert delete.status_code == 403

    def test_default_agent_alias_is_reserved(self, agent_client):
        check = agent_client.get("/api/agents/check?name=Lead-Agent")
        create = agent_client.post(
            "/api/agents",
            json={"name": "lead-agent", "soul": "shadow default"},
        )
        get = agent_client.get("/api/agents/lead-agent")
        update = agent_client.put(
            "/api/agents/lead-agent",
            json={"description": "shadow default"},
        )
        delete = agent_client.delete("/api/agents/lead-agent")

        assert check.json() == {"available": False, "name": "lead_agent"}
        assert create.status_code == 409
        assert get.status_code == 404
        assert update.status_code == 403
        assert delete.status_code == 403

    def test_create_agent(self, agent_client):
        payload = {
            "name": "code-reviewer",
            "description": "Reviews code",
            "soul": "You are a code reviewer.",
        }
        response = agent_client.post("/api/agents", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "code-reviewer"
        assert data["description"] == "Reviews code"
        assert data["soul"] == "You are a code reviewer."
        assert data["product"] == {
            "id": "personal:code-reviewer",
            "display_name": "code-reviewer",
            "origin": "personal",
            "category": "custom",
            "icon": "bot",
            "status": "available",
            "required_tools": [],
            "missing_requirements": [],
            "data_access": [
                "thread_uploads",
                "thread_workspace",
                "thread_outputs",
            ],
            "starter_prompts": [],
            "launch": {
                "kind": "chat",
                "path": "/workspace/agents/code-reviewer/chats/new",
                "project_kind": None,
            },
            "management": {
                "can_edit": True,
                "can_delete": True,
            },
        }

    def test_create_agent_invalid_name(self, agent_client):
        payload = {"name": "Code Reviewer!", "soul": "test"}
        response = agent_client.post("/api/agents", json=payload)
        assert response.status_code == 422

    def test_create_agent_uses_canonical_name(self, agent_client):
        response = agent_client.post(
            "/api/agents",
            json={"name": " Report_AGENT ", "soul": "canonical"},
        )

        assert response.status_code == 201
        assert response.json()["name"] == "report-agent"

    def test_create_duplicate_agent_409(self, agent_client):
        payload = {"name": "my-agent", "soul": "test"}
        agent_client.post("/api/agents", json=payload)

        # Second create should fail
        response = agent_client.post("/api/agents", json=payload)
        assert response.status_code == 409

    def test_list_agents_after_create(self, agent_client):
        agent_client.post("/api/agents", json={"name": "agent-one", "soul": "p1"})
        agent_client.post("/api/agents", json={"name": "agent-two", "soul": "p2"})

        response = agent_client.get("/api/agents")
        assert response.status_code == 200
        names = [a["name"] for a in response.json()["agents"]]
        assert "agent-one" in names
        assert "agent-two" in names

        products = {a["name"]: a["product"] for a in response.json()["agents"]}
        assert products["agent-one"]["id"] == "personal:agent-one"
        assert products["agent-two"]["launch"]["path"] == "/workspace/agents/agent-two/chats/new"

    def test_list_agents_includes_soul(self, agent_client):
        agent_client.post("/api/agents", json={"name": "soul-agent", "soul": "My soul content"})

        response = agent_client.get("/api/agents")
        assert response.status_code == 200
        agents = response.json()["agents"]
        soul_agent = next(a for a in agents if a["name"] == "soul-agent")
        assert soul_agent["soul"] == "My soul content"

    def test_get_agent(self, agent_client):
        agent_client.post("/api/agents", json={"name": "test-agent", "soul": "Hello world"})

        response = agent_client.get("/api/agents/test-agent")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-agent"
        assert data["soul"] == "Hello world"

    def test_get_missing_agent_404(self, agent_client):
        response = agent_client.get("/api/agents/nonexistent")
        assert response.status_code == 404

    def test_update_agent_soul(self, agent_client):
        agent_client.post("/api/agents", json={"name": "update-me", "soul": "original"})

        response = agent_client.put("/api/agents/update-me", json={"soul": "updated"})
        assert response.status_code == 200
        assert response.json()["soul"] == "updated"

    def test_update_agent_description(self, agent_client):
        agent_client.post("/api/agents", json={"name": "desc-agent", "description": "old desc", "soul": "p"})

        response = agent_client.put("/api/agents/desc-agent", json={"description": "new desc"})
        assert response.status_code == 200
        assert response.json()["description"] == "new desc"

    def test_update_missing_agent_404(self, agent_client):
        response = agent_client.put("/api/agents/ghost-agent", json={"soul": "new"})
        assert response.status_code == 404

    def test_delete_agent(self, agent_client):
        agent_client.post("/api/agents", json={"name": "del-me", "soul": "bye"})

        response = agent_client.delete("/api/agents/del-me")
        assert response.status_code == 204

        # Verify it's gone
        response = agent_client.get("/api/agents/del-me")
        assert response.status_code == 404

    def test_delete_missing_agent_404(self, agent_client):
        response = agent_client.delete("/api/agents/does-not-exist")
        assert response.status_code == 404

    def test_create_agent_with_model_and_tool_groups(self, agent_client):
        payload = {
            "name": "specialized",
            "description": "Specialized agent",
            "model": "deepseek-v3",
            "tool_groups": ["file:read", "bash"],
            "soul": "You are specialized.",
        }
        response = agent_client.post("/api/agents", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["model"] == "deepseek-v3"
        assert data["tool_groups"] == ["file:read", "bash"]

    def test_create_persists_files_on_disk(self, agent_client, tmp_path):
        agent_client.post("/api/agents", json={"name": "disk-check", "soul": "disk soul"})

        # tests/conftest.py installs an autouse fixture that sets the
        # contextvar to "test-user-autouse", so the agent is persisted under
        # users/test-user-autouse/agents/ rather than the legacy shared dir.
        agent_dir = tmp_path / "users" / "test-user-autouse" / "agents" / "disk-check"
        assert agent_dir.exists()
        assert (agent_dir / "config.yaml").exists()
        assert (agent_dir / "SOUL.md").exists()
        assert (agent_dir / "SOUL.md").read_text() == "disk soul"

    def test_delete_removes_files_from_disk(self, agent_client, tmp_path):
        agent_client.post("/api/agents", json={"name": "remove-me", "soul": "bye"})
        agent_dir = tmp_path / "users" / "test-user-autouse" / "agents" / "remove-me"
        assert agent_dir.exists()

        agent_client.delete("/api/agents/remove-me")
        assert not agent_dir.exists()

    def test_create_rejects_legacy_name_collision(self, agent_client, tmp_path):
        """An unmigrated legacy agent must still block name collision so that
        running the migration script later won't shadow the legacy entry."""
        legacy_dir = tmp_path / "agents" / "legacy-agent"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "config.yaml").write_text("name: legacy-agent\n", encoding="utf-8")
        (legacy_dir / "SOUL.md").write_text("legacy soul", encoding="utf-8")

        response = agent_client.post("/api/agents", json={"name": "legacy-agent", "soul": "x"})
        assert response.status_code == 409


# ===========================================================================
# 9. Gateway API – User Profile endpoints
# ===========================================================================


class TestUserProfileAPI:
    def test_get_user_profile_empty(self, agent_client):
        response = agent_client.get("/api/user-profile")
        assert response.status_code == 200
        assert response.json()["content"] is None

    def test_put_user_profile(self, agent_client, tmp_path):
        content = "# User Profile\n\nI am a developer."
        response = agent_client.put("/api/user-profile", json={"content": content})
        assert response.status_code == 200
        assert response.json()["content"] == content

        # File should be written to disk
        user_md = tmp_path / "USER.md"
        assert user_md.exists()
        assert user_md.read_text(encoding="utf-8") == content

    def test_get_user_profile_after_put(self, agent_client):
        content = "# Profile\n\nI work on data science."
        agent_client.put("/api/user-profile", json={"content": content})

        response = agent_client.get("/api/user-profile")
        assert response.status_code == 200
        assert response.json()["content"] == content

    def test_put_empty_user_profile_returns_none(self, agent_client):
        response = agent_client.put("/api/user-profile", json={"content": ""})
        assert response.status_code == 200
        assert response.json()["content"] is None


class TestAgentsApiDisabled:
    def test_agents_list_returns_403(self, disabled_agent_client):
        response = disabled_agent_client.get("/api/agents")
        assert response.status_code == 403
        assert "agents_api.enabled=true" in response.json()["detail"]

    def test_catalog_remains_available_with_only_builtins(
        self,
        disabled_agent_client,
    ):
        response = disabled_agent_client.get("/api/agent-catalog")

        assert response.status_code == 200
        assert response.json()["custom_agent_management_enabled"] is False
        assert [agent["name"] for agent in response.json()["agents"]] == ["office"]
        assert response.json()["agents"][0]["soul"] is None

    def test_catalog_exposes_runtime_safe_personal_agent_without_management(
        self,
        disabled_agent_client,
        tmp_path,
    ):
        agent_dir = tmp_path / "users" / "test-user-autouse" / "agents" / "runtime-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text(
            "name: runtime-agent\ndescription: Runtime only\n",
            encoding="utf-8",
        )
        (agent_dir / "SOUL.md").write_text("private", encoding="utf-8")

        response = disabled_agent_client.get("/api/agent-catalog")

        assert response.status_code == 200
        agents = {agent["name"]: agent for agent in response.json()["agents"]}
        assert agents["runtime-agent"]["soul"] is None
        assert agents["runtime-agent"]["product"]["management"] == {
            "can_edit": False,
            "can_delete": False,
        }

    def test_builtin_get_remains_available(self, disabled_agent_client):
        response = disabled_agent_client.get("/api/agents/office")

        assert response.status_code == 200
        assert response.json()["product"]["id"] == "builtin:office"

    def test_agent_get_returns_403(self, disabled_agent_client):
        response = disabled_agent_client.get("/api/agents/example-agent")
        assert response.status_code == 403

    def test_agent_name_check_returns_403(self, disabled_agent_client):
        response = disabled_agent_client.get("/api/agents/check", params={"name": "example-agent"})
        assert response.status_code == 403

    def test_agent_create_returns_403(self, disabled_agent_client):
        response = disabled_agent_client.post("/api/agents", json={"name": "example-agent", "soul": "blocked"})
        assert response.status_code == 403

    def test_agent_update_returns_403(self, disabled_agent_client):
        response = disabled_agent_client.put("/api/agents/example-agent", json={"description": "blocked"})
        assert response.status_code == 403

    def test_agent_delete_returns_403(self, disabled_agent_client):
        response = disabled_agent_client.delete("/api/agents/example-agent")
        assert response.status_code == 403

    def test_user_profile_routes_return_403(self, disabled_agent_client):
        get_response = disabled_agent_client.get("/api/user-profile")
        put_response = disabled_agent_client.put("/api/user-profile", json={"content": "blocked"})

        assert get_response.status_code == 403
        assert put_response.status_code == 403
