"""VassilFlow facade over the current DeerFlow runtime.

The implementation still lives under ``deerflow`` during the migration. This
package exposes the VassilFlow-owned public vocabulary without breaking existing
``deerflow.*`` imports.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from vassilflow._module_aliases import install_vassilflow_module_aliases

install_vassilflow_module_aliases()

_LAZY_EXPORTS = {
    "ApprovalRequest": ("vassilflow.boundary", "ApprovalRequest"),
    "ApprovalStatus": ("vassilflow.boundary", "ApprovalStatus"),
    "CompletionEvidence": ("vassilflow.boundary", "CompletionEvidence"),
    "DeerFlowClient": ("vassilflow.client", "DeerFlowClient"),
    "EventType": ("vassilflow.boundary", "EventType"),
    "PolicyDecision": ("vassilflow.boundary", "PolicyDecision"),
    "PolicyDecisionValue": ("vassilflow.boundary", "PolicyDecisionValue"),
    "RiskTier": ("vassilflow.boundary", "RiskTier"),
    "Run": ("vassilflow.boundary", "Run"),
    "RunStatus": ("vassilflow.boundary", "RunStatus"),
    "Session": ("vassilflow.boundary", "Session"),
    "SessionStatus": ("vassilflow.boundary", "SessionStatus"),
    "StreamEvent": ("vassilflow.client", "StreamEvent"),
    "StreamEventType": ("vassilflow.client", "StreamEventType"),
    "ToolSpec": ("vassilflow.boundary", "ToolSpec"),
    "TraceStep": ("vassilflow.boundary", "TraceStep"),
    "VassilFlowClient": ("vassilflow.client", "VassilFlowClient"),
    "create_deerflow_agent": ("vassilflow.agents", "create_deerflow_agent"),
    "create_vassilflow_agent": ("vassilflow.agents", "create_vassilflow_agent"),
}


def __getattr__(name: str) -> Any:
    """Load public facade exports only when callers ask for them."""

    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value

__all__ = [
    "ApprovalRequest",
    "ApprovalStatus",
    "CompletionEvidence",
    "DeerFlowClient",
    "EventType",
    "PolicyDecision",
    "PolicyDecisionValue",
    "RiskTier",
    "Run",
    "RunStatus",
    "Session",
    "SessionStatus",
    "StreamEvent",
    "StreamEventType",
    "ToolSpec",
    "TraceStep",
    "VassilFlowClient",
    "create_deerflow_agent",
    "create_vassilflow_agent",
    "install_vassilflow_module_aliases",
]
