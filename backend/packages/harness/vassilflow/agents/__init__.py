"""Agent factory facade for VassilFlow integrations."""

from importlib import import_module

from vassilflow.agents.factory import create_deerflow_agent, create_vassilflow_agent

_agents_impl = import_module("deerflow.agents")

_IMPLEMENTATION_EXPORTS = [
    "Next",
    "Prev",
    "RuntimeFeatures",
    "SandboxState",
    "ThreadState",
    "make_lead_agent",
]

globals().update({name: getattr(_agents_impl, name) for name in _IMPLEMENTATION_EXPORTS})

__all__ = [
    *_IMPLEMENTATION_EXPORTS,
    "create_deerflow_agent",
    "create_vassilflow_agent",
]
