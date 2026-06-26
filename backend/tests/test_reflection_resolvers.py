"""Tests for reflection resolvers."""

import importlib
from pathlib import Path

import pytest
import yaml

from vassilflow.reflection import resolvers
from vassilflow.reflection.resolvers import resolve_variable

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_resolve_variable_reports_install_hint_for_missing_google_provider(monkeypatch: pytest.MonkeyPatch):
    """Missing google provider should return actionable install guidance."""

    def fake_import_module(module_path: str):
        raise ModuleNotFoundError(f"No module named '{module_path}'", name=module_path)

    monkeypatch.setattr(resolvers, "import_module", fake_import_module)

    with pytest.raises(ImportError) as exc_info:
        resolve_variable("langchain_google_genai:ChatGoogleGenerativeAI")

    message = str(exc_info.value)
    assert "Could not import module langchain_google_genai" in message
    assert "uv add langchain-google-genai" in message
    assert "restart VassilFlow" in message


def test_resolve_variable_reports_install_hint_for_missing_google_transitive_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing transitive dependency should still return actionable install guidance."""

    def fake_import_module(module_path: str):
        # Simulate provider module existing but a transitive dependency (e.g. `google`) missing.
        raise ModuleNotFoundError("No module named 'google'", name="google")

    monkeypatch.setattr(resolvers, "import_module", fake_import_module)

    with pytest.raises(ImportError) as exc_info:
        resolve_variable("langchain_google_genai:ChatGoogleGenerativeAI")

    message = str(exc_info.value)
    # Even when a transitive dependency is missing, the hint should still point to the provider package.
    assert "uv add langchain-google-genai" in message


def test_resolve_variable_invalid_path_format():
    """Invalid variable path should fail with format guidance."""
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("invalid.variable.path")

    assert "doesn't look like a variable path" in str(exc_info.value)


@pytest.mark.parametrize(
    ("vassilflow_path", "deerflow_path"),
    [
        (
            "vassilflow.models.openai_codex_provider:CodexChatModel",
            "deerflow.models.openai_codex_provider:CodexChatModel",
        ),
        (
            "vassilflow.community.ddg_search.tools:web_search_tool",
            "deerflow.community.ddg_search.tools:web_search_tool",
        ),
        (
            "vassilflow.sandbox.tools:read_file_tool",
            "deerflow.sandbox.tools:read_file_tool",
        ),
        (
            "vassilflow.sandbox.local:LocalSandboxProvider",
            "deerflow.sandbox.local:LocalSandboxProvider",
        ),
        (
            "vassilflow.guardrails.builtin:AllowlistProvider",
            "deerflow.guardrails.builtin:AllowlistProvider",
        ),
    ],
)
def test_resolve_variable_bridges_vassilflow_internal_class_paths(vassilflow_path, deerflow_path):
    assert resolve_variable(vassilflow_path) is resolve_variable(deerflow_path)


def test_resolve_variable_exposes_vassilflow_agent_factory_wrapper():
    facade_factory = resolve_variable("vassilflow.agents:create_vassilflow_agent")
    module_factory = resolve_variable("vassilflow.agents.factory:create_vassilflow_agent")
    deerflow_factory = resolve_variable("deerflow.agents:create_deerflow_agent")

    assert facade_factory.__name__ == "create_vassilflow_agent"
    assert getattr(facade_factory, "__wrapped__", None) is deerflow_factory
    assert module_factory is facade_factory


@pytest.mark.parametrize(
    ("vassilflow_path", "deerflow_path"),
    [
        (
            "vassilflow.models.openai_codex_provider:CodexChatModel",
            "deerflow.models.openai_codex_provider:CodexChatModel",
        ),
        (
            "vassilflow.community.ddg_search.tools:web_search_tool",
            "deerflow.community.ddg_search.tools:web_search_tool",
        ),
        (
            "vassilflow.sandbox.tools:read_file_tool",
            "deerflow.sandbox.tools:read_file_tool",
        ),
        (
            "vassilflow.sandbox.local:LocalSandboxProvider",
            "deerflow.sandbox.local:LocalSandboxProvider",
        ),
        (
            "vassilflow.guardrails.builtin:AllowlistProvider",
            "deerflow.guardrails.builtin:AllowlistProvider",
        ),
        (
            "vassilflow.agents.middlewares.safety_termination_detectors:OpenAICompatibleContentFilterDetector",
            "deerflow.agents.middlewares.safety_termination_detectors:OpenAICompatibleContentFilterDetector",
        ),
    ],
)
def test_direct_vassilflow_internal_imports_alias_to_deerflow_modules(vassilflow_path, deerflow_path):
    assert _import_variable(vassilflow_path) is _import_variable(deerflow_path)


def test_config_example_prefers_vassilflow_dynamic_paths():
    content = (REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8")

    assert "use: vassilflow." in content
    assert "use: deerflow." not in content


def test_active_config_example_vassilflow_use_paths_resolve():
    config = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    use_paths = sorted(
        {
            value["use"]
            for value in _walk_config_values(config)
            if isinstance(value, dict)
            and isinstance(value.get("use"), str)
            and value["use"].startswith("vassilflow.")
        }
    )

    assert use_paths
    for variable_path in use_paths:
        assert resolve_variable(variable_path) is not None, variable_path


def _walk_config_values(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_config_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_config_values(child)


def _import_variable(variable_path: str):
    module_path, variable_name = variable_path.rsplit(":", 1)

    return getattr(importlib.import_module(module_path), variable_name)
