"""Static coverage for VassilFlow-owned documentation surfaces."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_guardrails_docs_use_vassilflow_framework_identity():
    content = (REPO_ROOT / "backend" / "docs" / "GUARDRAILS.md").read_text(encoding="utf-8")

    assert "aport setup --framework vassilflow" in content
    assert "~/.aport/vassilflow/config.yaml" in content
    assert 'framework="vassilflow"' in content
    assert "VassilFlow Tool Names" in content
    assert "Start DeerFlow" not in content
    assert "~/.aport/deerflow" not in content
    assert 'framework="deerflow"' not in content


def test_backend_claude_uses_vassilflow_project_identity():
    content = (REPO_ROOT / "backend" / "CLAUDE.md").read_text(encoding="utf-8")

    assert "VassilFlow is a LangGraph-based AI super agent system" in content
    assert "VASSILFLOW_CONFIG_PATH" in content
    assert "VassilFlow's application tables" in content
    assert "empty (no VassilFlow tables)" in content
    assert "VassilFlowClient` provides direct in-process access" in content
    assert "DeerFlow is a LangGraph-based AI super agent system" not in content
    assert "DeerFlow's application tables" not in content
