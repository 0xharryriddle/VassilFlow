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
