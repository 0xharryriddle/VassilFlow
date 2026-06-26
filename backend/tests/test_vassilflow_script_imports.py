"""Static coverage for VassilFlow-owned script import surfaces."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_tool_error_degradation_detector_uses_vassilflow_facade_imports():
    content = _read("scripts/tool-error-degradation-detection.sh")

    assert "from vassilflow.agents.lead_agent.agent import build_middlewares" in content
    assert "from vassilflow.config import get_app_config" in content
    assert "from vassilflow.sandbox.middleware import SandboxMiddleware" in content
    assert (
        "from vassilflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware"
        in content
    )
    assert (
        "from vassilflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares"
        in content
    )
    assert "from deerflow.agents.lead_agent.agent import" not in content
    assert "from deerflow.config import" not in content
    assert "from deerflow.sandbox.middleware import" not in content


def test_backend_debug_script_uses_vassilflow_facade_imports():
    content = _read("backend/debug.py")

    assert "from vassilflow.config import get_app_config" in content
    assert "from vassilflow.config.app_config import apply_logging_level" in content
    assert "from vassilflow.agents import make_lead_agent" in content
    assert "from vassilflow.config.paths import get_paths" in content
    assert "from vassilflow.mcp import initialize_mcp_tools" in content
    assert "from vassilflow.runtime.user_context import get_effective_user_id" in content
    assert "from deerflow.config import get_app_config" not in content
    assert "from deerflow.agents import make_lead_agent" not in content
    assert "from deerflow.mcp import initialize_mcp_tools" not in content


def test_backend_python_scripts_use_vassilflow_public_imports():
    autogen = _read("backend/scripts/_autogen_revision.py")
    migration = _read("backend/scripts/migrate_user_isolation.py")
    recorder = _read("backend/scripts/record_gateway.py")
    safety_demo = _read("backend/scripts/e2e_safety_termination_demo.py")

    assert "import vassilflow.persistence.models" in autogen
    assert "from vassilflow.persistence.bootstrap import _escape_url_for_alembic" in autogen
    assert "from vassilflow.config.paths import Paths, get_paths" in migration
    assert "import vassilflow.models.factory as factory_mod" in recorder
    assert "from vassilflow.client import VassilFlowClient" in safety_demo
    assert "client = VassilFlowClient()" in safety_demo

    assert "import deerflow.persistence.models" not in autogen
    assert "from deerflow.persistence.bootstrap import _escape_url_for_alembic" not in autogen
    assert "from deerflow.config.paths import Paths, get_paths" not in migration
    assert "import deerflow.models.factory as factory_mod" not in recorder
    assert 'import_module("deerflow.client")' not in safety_demo
    assert "import deerflow.client" not in safety_demo
    assert "from deerflow.client import DeerFlowClient" not in safety_demo
    assert "client = DeerFlowClient()" not in safety_demo
