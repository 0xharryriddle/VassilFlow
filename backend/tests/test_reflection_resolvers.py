"""Tests for reflection resolvers."""

from pathlib import Path

import pytest

from deerflow.reflection import resolvers
from deerflow.reflection.resolvers import resolve_variable

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


def test_config_example_prefers_vassilflow_dynamic_paths():
    content = (REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8")

    assert "use: vassilflow." in content
    assert "use: deerflow." not in content
