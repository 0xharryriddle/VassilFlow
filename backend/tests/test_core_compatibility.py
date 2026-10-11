"""The full application uses the same recovery middleware as standalone core."""

from vassilflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware as LegacyMiddleware
from vassilflow_core.middleware import DanglingToolCallMiddleware as CoreMiddleware


def test_existing_harness_imports_reuse_core_implementation():
    assert LegacyMiddleware is CoreMiddleware
