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


def test_backend_docs_index_and_mcp_use_vassilflow_identity():
    docs_readme = (REPO_ROOT / "backend" / "docs" / "README.md").read_text(encoding="utf-8")
    mcp_docs = (REPO_ROOT / "backend" / "docs" / "MCP_SERVER.md").read_text(encoding="utf-8")

    assert "VassilFlow backend" in docs_readme
    assert "New to VassilFlow?" in docs_readme
    assert "VassilFlow supports configurable MCP servers" in mcp_docs
    assert "VassilFlow's built-in file tools" in mcp_docs
    assert "DeerFlow backend" not in docs_readme
    assert "New to DeerFlow?" not in docs_readme
    assert "DeerFlow supports configurable MCP servers" not in mcp_docs
