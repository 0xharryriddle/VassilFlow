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


def test_configuration_docs_use_vassilflow_identity_and_env_names():
    content = (REPO_ROOT / "backend" / "docs" / "CONFIGURATION.md").read_text(
        encoding="utf-8"
    )

    assert "configure VassilFlow for your environment" in content
    assert "VassilFlow supports multiple sandbox execution modes" in content
    assert "Set `VASSILFLOW_SANDBOX_BIND_HOST` explicitly" in content
    assert "Set `VASSILFLOW_PROJECT_ROOT` if the runtime starts elsewhere" in content
    assert "legacy `DEER_FLOW_SANDBOX_BIND_HOST` is still accepted" in content
    assert "configure DeerFlow for your environment" not in content
    assert "DeerFlow supports multiple sandbox execution modes" not in content
    assert "Set `DEER_FLOW_SANDBOX_BIND_HOST` explicitly" not in content


def test_architecture_docs_use_vassilflow_runtime_identity():
    content = (REPO_ROOT / "backend" / "docs" / "ARCHITECTURE.md").read_text(
        encoding="utf-8"
    )

    assert "overview of the VassilFlow backend architecture" in content
    assert "Local VassilFlow thread data cleanup" in content
    assert "VassilFlow-managed filesystem data" in content
    assert "`{runtime_home}/threads/{thread_id}/user-data/workspace`" in content
    assert "`skills/` under the project root by default" in content
    assert "overview of the DeerFlow backend architecture" not in content
    assert "Local DeerFlow thread data cleanup" not in content
    assert "`backend/.deer-flow/threads/{thread_id}/user-data/workspace`" not in content


def test_im_channel_docs_use_vassilflow_identity():
    content = (REPO_ROOT / "backend" / "docs" / "IM_CHANNEL_CONNECTIONS.md").read_text(
        encoding="utf-8"
    )

    assert "VassilFlow supports user-owned IM channel bindings" in content
    assert "connect the channel from VassilFlow Settings" in content
    assert "Send /connect <code> to the VassilFlow Slack bot." in content
    assert "VassilFlow run user id" in content
    assert "DeerFlow supports user-owned IM channel bindings" not in content
    assert "connect the channel from DeerFlow Settings" not in content
    assert "Send /connect <code> to the DeerFlow Slack bot." not in content
