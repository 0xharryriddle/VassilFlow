from pathlib import Path

from app.channels.service import _resolve_service_url
from app.gateway.auth_disabled import is_auth_disabled, is_explicit_production_environment
from deerflow.config.app_config import AppConfig
from deerflow.config.env_aliases import env_value, vassilflow_alias_for
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.runtime_paths import project_root, runtime_home
from deerflow.config.skills_config import SkillsConfig


def test_vassilflow_alias_for_deer_flow_names():
    assert vassilflow_alias_for("DEER_FLOW_HOME") == "VASSILFLOW_HOME"
    assert vassilflow_alias_for("DEERFLOW_WRITE_FILE_MAX_BYTES") == "VASSILFLOW_WRITE_FILE_MAX_BYTES"
    assert vassilflow_alias_for("ENVIRONMENT") is None


def test_env_value_prefers_vassilflow_alias(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", "legacy-home")
    monkeypatch.setenv("VASSILFLOW_HOME", "vassil-home")

    assert env_value("DEER_FLOW_HOME") == "vassil-home"


def test_env_value_supports_legacy_deerflow_prefix_alias(monkeypatch):
    monkeypatch.setenv("DEERFLOW_WRITE_FILE_MAX_BYTES", "1024")
    monkeypatch.setenv("VASSILFLOW_WRITE_FILE_MAX_BYTES", "2048")

    assert env_value("DEERFLOW_WRITE_FILE_MAX_BYTES") == "2048"


def test_vassilflow_project_root_and_home_aliases(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    home = tmp_path / "vassil-home"

    monkeypatch.chdir(other_cwd)
    monkeypatch.setenv("VASSILFLOW_PROJECT_ROOT", str(project))
    monkeypatch.setenv("VASSILFLOW_HOME", str(home))
    monkeypatch.delenv("DEER_FLOW_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("DEER_FLOW_HOME", raising=False)

    assert project_root() == project.resolve()
    assert runtime_home() == home.resolve()


def test_vassilflow_config_path_alias(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n", encoding="utf-8")

    monkeypatch.setenv("VASSILFLOW_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)

    assert AppConfig.resolve_config_path() == config_path


def test_vassilflow_extensions_config_path_alias(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")

    monkeypatch.setenv("VASSILFLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", raising=False)

    assert ExtensionsConfig.resolve_config_path() == config_path


def test_vassilflow_skills_path_alias(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VASSILFLOW_SKILLS_PATH", "team-skills")
    monkeypatch.delenv("DEER_FLOW_SKILLS_PATH", raising=False)

    assert SkillsConfig().get_skills_path() == tmp_path / "team-skills"


def test_vassilflow_auth_disabled_alias(monkeypatch):
    monkeypatch.setenv("VASSILFLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    monkeypatch.delenv("VASSILFLOW_ENV", raising=False)
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    assert is_auth_disabled() is True


def test_vassilflow_env_blocks_auth_disabled_in_production(monkeypatch):
    monkeypatch.setenv("VASSILFLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("VASSILFLOW_ENV", "production")
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)

    assert is_explicit_production_environment() is True
    assert is_auth_disabled() is False


def test_vassilflow_channel_url_alias(monkeypatch):
    monkeypatch.setenv("VASSILFLOW_CHANNELS_GATEWAY_URL", "http://gateway.internal")
    monkeypatch.delenv("DEER_FLOW_CHANNELS_GATEWAY_URL", raising=False)

    assert _resolve_service_url({}, "gateway_url", "DEER_FLOW_CHANNELS_GATEWAY_URL", "http://default") == "http://gateway.internal"
