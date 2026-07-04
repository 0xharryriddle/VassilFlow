"""Static guards for VassilFlow-owned runtime wording."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


WORDING_TARGETS = [
    (
        "backend/packages/harness/vassilflow/agents/memory/__init__.py",
        "Memory module for VassilFlow.",
        "Memory module for VassilFlow.",
    ),
    (
        "backend/packages/harness/vassilflow/tools/types.py",
        "Concrete runtime type used by all VassilFlow tools.",
        "Concrete runtime type used by all VassilFlow tools.",
    ),
    (
        "backend/packages/harness/vassilflow/mcp/tools.py",
        "the rest of VassilFlow addresses them",
        "the rest of VassilFlow addresses them",
    ),
    (
        "backend/packages/harness/vassilflow/models/patched_minimax.py",
        "which VassilFlow already understands.",
        "which VassilFlow already understands.",
    ),
    (
        "backend/packages/harness/vassilflow/models/vllm_provider.py",
        "Map VassilFlow's legacy",
        "Map VassilFlow's legacy",
    ),
    (
        "backend/packages/harness/vassilflow/agents/middlewares/system_message_coalescing_middleware.py",
        "VassilFlow's lead agent",
        "VassilFlow's lead agent",
    ),
    (
        "backend/packages/harness/vassilflow/agents/middlewares/safety_termination_detectors.py",
        "providers VassilFlow supports today",
        "providers VassilFlow supports today",
    ),
    (
        "backend/packages/harness/vassilflow/agents/factory.py",
        "Pure-argument factory for VassilFlow agents.",
        "Pure-argument factory for VassilFlow agents.",
    ),
    (
        "backend/packages/harness/vassilflow/agents/features.py",
        "Declarative feature flags for ``create_vassilflow_agent``.",
        "Declarative feature flags for ``create_vassilflow_agent``.",
    ),
    (
        "backend/packages/harness/vassilflow/agents/lead_agent/agent.py",
        "embedded ``VassilFlowClient``",
        "embedded ``VassilFlowClient``",
    ),
    (
        "backend/packages/harness/vassilflow/client.py",
        "Embedded Python client for VassilFlow agent system.",
        "VassilFlow embedded Python client implementation.",
    ),
    (
        "backend/packages/harness/vassilflow/client.py",
        "Provides direct programmatic access to VassilFlow's agent capabilities",
        "Provides direct programmatic access to VassilFlow's agent capabilities",
    ),
    (
        "backend/packages/harness/vassilflow/client.py",
        "from vassilflow.client import VassilFlowClient",
        "from vassilflow.client import VassilFlowClient",
    ),
    (
        "backend/packages/harness/vassilflow/client.py",
        "So ``VassilFlowClient.stream()`` is",
        "So ``VassilFlowClient.stream()`` is",
    ),
    (
        "backend/packages/harness/vassilflow/runtime/runs/worker.py",
        "Shared helper with ``VassilFlowClient.stream``",
        "Shared helper with ``VassilFlowClient.stream``",
    ),
    (
        "backend/packages/harness/vassilflow/agents/middlewares/input_sanitization_middleware.py",
        "I use VassilFlow's <think> tag?",
        "I use VassilFlow's <think> tag?",
    ),
    (
        "backend/packages/harness/vassilflow/tools/sync.py",
        "VassilFlow's current config-sensitive tools",
        "VassilFlow's current config-sensitive tools",
    ),
    (
        "backend/tests/test_tool_args_schema_no_pydantic_warning.py",
        "VassilFlow tools annotate their runtime parameter",
        "VassilFlow tools annotate their runtime parameter",
    ),
    (
        "backend/tests/test_tool_args_schema_no_pydantic_warning.py",
        "actual context VassilFlow installs is a dict",
        "actual context VassilFlow installs is a dict",
    ),
    (
        "backend/tests/test_persistence_migrations_env.py",
        "VassilFlow's own tables",
        "VassilFlow's own tables",
    ),
    (
        "backend/tests/test_persistence_migrations_env.py",
        "test_filter_includes_vassilflow_tables",
        "test_filter_includes_vassilflow_tables",
    ),
    (
        "backend/tests/test_channels.py",
        "new VassilFlow thread",
        "new VassilFlow thread",
    ),
    (
        "backend/tests/test_channels.py",
        "same VassilFlow thread",
        "same VassilFlow thread",
    ),
    (
        "backend/packages/harness/vassilflow/__init__.py",
        "VassilFlow facade over the current VassilFlow runtime.",
        "VassilFlow agent harness package.",
    ),
    (
        "backend/packages/harness/vassilflow/runtime/__init__.py",
        "current VassilFlow implementation",
        "LangGraph-compatible runtime",
    ),
    (
        "backend/packages/harness/vassilflow/boundary.py",
        "the VassilFlow runtime can keep",
        "the implementation runtime can keep",
    ),
    (
        "backend/packages/harness/vassilflow/reflection/resolvers.py",
        "current VassilFlow implementation",
        "current implementation modules",
    ),
    (
        "backend/docs/BLOCKING_IO_DETECTION.md",
        "the `vassilflow.*` facade",
        "code under `app.*` or `vassilflow.*`",
    ),
    (
        "backend/tests/support/detectors/blocking_io_runtime.py",
        "app, vassilflow implementation, and\nvassilflow facade",
        "app and VassilFlow modules",
    ),
    (
        "backend/tests/support/detectors/blocking_io_runtime.py",
        "app.*, vassilflow.*, and vassilflow.* callers",
        "app.* and vassilflow.* callers",
    ),
]


@pytest.mark.parametrize(("path", "_previous", "current"), WORDING_TARGETS)
def test_runtime_wording_prefers_vassilflow_identity(path: str, _previous: str, current: str) -> None:
    content = (REPO_ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")

    assert current in content
