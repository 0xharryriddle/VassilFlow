"""Agent factory facade for VassilFlow integrations."""

from typing import Any

from deerflow.agents import (
    Next,
    Prev,
    RuntimeFeatures,
    SandboxState,
    ThreadState,
    create_deerflow_agent,
    make_lead_agent,
)


def create_vassilflow_agent(*args: Any, **kwargs: Any) -> Any:
    """Create a VassilFlow agent using the current DeerFlow implementation."""

    return create_deerflow_agent(*args, **kwargs)


create_vassilflow_agent.__wrapped__ = create_deerflow_agent  # type: ignore[attr-defined]

__all__ = [
    "Next",
    "Prev",
    "RuntimeFeatures",
    "SandboxState",
    "ThreadState",
    "create_deerflow_agent",
    "create_vassilflow_agent",
    "make_lead_agent",
]
