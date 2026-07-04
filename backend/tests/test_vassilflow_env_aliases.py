from pathlib import Path

from app.channels.service import _resolve_service_url
from app.gateway.auth_disabled import is_auth_disabled, is_explicit_production_environment
from vassilflow.config.app_config import AppConfig
from vassilflow.config.env_aliases import env_value, vassilflow_alias_for
from vassilflow.config.extensions_config import ExtensionsConfig
from vassilflow.config.runtime_paths import project_root, runtime_home
from vassilflow.config.skills_config import SkillsConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_alias_registry_has_no_self_aliases():
    assert vassilflow_alias_for("VASSILFLOW_HOME") is None
    assert vassilflow_alias_for("VASSILFLOW_WRITE_FILE_MAX_BYTES") is None
    assert vassilflow_alias_for("ENVIRONMENT") is None


def test_env_value_reads_exact_vassilflow_name(monkeypatch):
    monkeypatch.setenv("VASSILFLOW_HOME", "vassil-home")

    assert env_value("VASSILFLOW_HOME") == "vassil-home"


def test_missing_vassilflow_name_returns_none(monkeypatch):
    monkeypatch.delenv("VASSILFLOW_HOME", raising=False)

    assert env_value("VASSILFLOW_HOME") is None


def test_vassilflow_env_standalone_names_are_documented():
    docs = (
        REPO_ROOT / ".env.example",
        REPO_ROOT / "README.md",
        REPO_ROOT / "backend/docs/CONFIGURATION.md",
        REPO_ROOT / "backend/docs/SETUP.md",
        REPO_ROOT / "frontend/src/content/en/harness/configuration.mdx",
    )

    for path in docs:
        content = path.read_text(encoding="utf-8")
        assert "VASSILFLOW_*" in content, path


def test_vassilflow_project_root_and_home(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    home = tmp_path / "vassil-home"

    monkeypatch.chdir(other_cwd)
    monkeypatch.setenv("VASSILFLOW_PROJECT_ROOT", str(project))
    monkeypatch.setenv("VASSILFLOW_HOME", str(home))

    assert project_root() == project.resolve()
    assert runtime_home() == home.resolve()


def test_vassilflow_runtime_home_defaults_to_current_name(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()

    monkeypatch.setenv("VASSILFLOW_PROJECT_ROOT", str(project))
    monkeypatch.delenv("VASSILFLOW_HOME", raising=False)

    assert runtime_home() == (project / ".vassilflow").resolve()


def test_vassilflow_config_path(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("sandbox:\n  use: vassilflow.sandbox.local:LocalSandboxProvider\n", encoding="utf-8")

    monkeypatch.setenv("VASSILFLOW_CONFIG_PATH", str(config_path))

    assert AppConfig.resolve_config_path() == config_path


def test_vassilflow_extensions_config_path(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")

    monkeypatch.setenv("VASSILFLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    assert ExtensionsConfig.resolve_config_path() == config_path


def test_vassilflow_skills_path(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VASSILFLOW_SKILLS_PATH", "team-skills")

    assert SkillsConfig().get_skills_path() == tmp_path / "team-skills"


def test_vassilflow_auth_disabled(monkeypatch):
    monkeypatch.setenv("VASSILFLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("VASSILFLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    assert is_auth_disabled() is True


def test_vassilflow_env_blocks_auth_disabled_in_production(monkeypatch):
    monkeypatch.setenv("VASSILFLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("VASSILFLOW_ENV", "production")

    assert is_explicit_production_environment() is True
    assert is_auth_disabled() is False


def test_vassilflow_channel_url(monkeypatch):
    monkeypatch.setenv("VASSILFLOW_CHANNELS_GATEWAY_URL", "http://gateway.internal")

    assert _resolve_service_url({}, "gateway_url", "VASSILFLOW_CHANNELS_GATEWAY_URL", "http://default") == "http://gateway.internal"
