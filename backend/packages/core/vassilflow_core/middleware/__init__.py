"""Config-free middleware shared by the core and full VassilFlow application."""

from .dangling_tool_calls import DanglingToolCallMiddleware

__all__ = ["DanglingToolCallMiddleware"]
