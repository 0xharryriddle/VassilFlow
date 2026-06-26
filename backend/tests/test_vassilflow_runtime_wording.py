"""Static guards for VassilFlow-owned runtime wording."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


WORDING_TARGETS = [
    (
        "backend/packages/harness/deerflow/agents/memory/__init__.py",
        "Memory module for DeerFlow.",
        "Memory module for VassilFlow.",
    ),
    (
        "backend/packages/harness/deerflow/tools/types.py",
        "Concrete runtime type used by all DeerFlow tools.",
        "Concrete runtime type used by all VassilFlow tools.",
    ),
    (
        "backend/packages/harness/deerflow/mcp/tools.py",
        "the rest of DeerFlow addresses them",
        "the rest of VassilFlow addresses them",
    ),
    (
        "backend/packages/harness/deerflow/models/patched_minimax.py",
        "which DeerFlow already understands.",
        "which VassilFlow already understands.",
    ),
    (
        "backend/packages/harness/deerflow/models/vllm_provider.py",
        "Map DeerFlow's legacy",
        "Map VassilFlow's legacy",
    ),
    (
        "backend/packages/harness/deerflow/agents/middlewares/system_message_coalescing_middleware.py",
        "DeerFlow's lead agent",
        "VassilFlow's lead agent",
    ),
    (
        "backend/packages/harness/deerflow/agents/middlewares/safety_termination_detectors.py",
        "providers DeerFlow supports today",
        "providers VassilFlow supports today",
    ),
    (
        "backend/packages/harness/deerflow/agents/factory.py",
        "Pure-argument factory for DeerFlow agents.",
        "Pure-argument factory for VassilFlow agents.",
    ),
    (
        "backend/packages/harness/deerflow/agents/features.py",
        "Declarative feature flags for ``create_deerflow_agent``.",
        "Declarative feature flags for ``create_vassilflow_agent``.",
    ),
    (
        "backend/packages/harness/deerflow/agents/lead_agent/agent.py",
        "embedded ``DeerFlowClient``",
        "embedded ``VassilFlowClient``",
    ),
    (
        "backend/packages/harness/deerflow/client.py",
        "Embedded Python client for DeerFlow agent system.",
        "VassilFlow embedded Python client implementation.",
    ),
    (
        "backend/packages/harness/deerflow/client.py",
        "Provides direct programmatic access to DeerFlow's agent capabilities",
        "Provides direct programmatic access to VassilFlow's agent capabilities",
    ),
    (
        "backend/packages/harness/deerflow/client.py",
        "from deerflow.client import DeerFlowClient",
        "from vassilflow.client import VassilFlowClient",
    ),
    (
        "backend/packages/harness/deerflow/client.py",
        "So ``DeerFlowClient.stream()`` is",
        "So ``VassilFlowClient.stream()`` is",
    ),
    (
        "backend/packages/harness/deerflow/agents/middlewares/input_sanitization_middleware.py",
        "I use DeerFlow's <think> tag?",
        "I use VassilFlow's <think> tag?",
    ),
    (
        "backend/packages/harness/deerflow/tools/sync.py",
        "DeerFlow's current config-sensitive tools",
        "VassilFlow's current config-sensitive tools",
    ),
    (
        "backend/tests/test_tool_args_schema_no_pydantic_warning.py",
        "DeerFlow tools annotate their runtime parameter",
        "VassilFlow tools annotate their runtime parameter",
    ),
    (
        "backend/tests/test_tool_args_schema_no_pydantic_warning.py",
        "actual context DeerFlow installs is a dict",
        "actual context VassilFlow installs is a dict",
    ),
    (
        "backend/tests/test_persistence_migrations_env.py",
        "DeerFlow's own tables",
        "VassilFlow's own tables",
    ),
    (
        "backend/tests/test_persistence_migrations_env.py",
        "test_filter_includes_deerflow_tables",
        "test_filter_includes_vassilflow_tables",
    ),
    (
        "backend/tests/test_channels.py",
        "new DeerFlow thread",
        "new VassilFlow thread",
    ),
    (
        "backend/tests/test_channels.py",
        "same DeerFlow thread",
        "same VassilFlow thread",
    ),
]


@pytest.mark.parametrize(("path", "legacy", "current"), WORDING_TARGETS)
def test_runtime_wording_prefers_vassilflow_identity(path: str, legacy: str, current: str) -> None:
    content = (REPO_ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")

    assert current in content
    assert legacy not in content
