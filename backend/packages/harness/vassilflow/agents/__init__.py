"""Agent factory facade for VassilFlow integrations."""

from deerflow.agents import (
    Next,
    Prev,
    RuntimeFeatures,
    SandboxState,
    ThreadState,
    create_deerflow_agent,
    make_lead_agent,
)

create_vassilflow_agent = create_deerflow_agent

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
