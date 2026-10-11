"""Compatibility import for interrupted-tool recovery shared with standalone core."""

from vassilflow_core.middleware.dangling_tool_calls import DanglingToolCallMiddleware

__all__ = ["DanglingToolCallMiddleware"]
