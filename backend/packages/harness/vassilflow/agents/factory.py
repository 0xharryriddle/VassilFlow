"""Agent factory facade for VassilFlow SDK callers."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_implementation_factory = import_module("deerflow.agents.factory")

create_deerflow_agent = _implementation_factory.create_deerflow_agent


def create_vassilflow_agent(*args: Any, **kwargs: Any) -> Any:
    """Create a VassilFlow agent using the current factory implementation."""

    return create_deerflow_agent(*args, **kwargs)


create_vassilflow_agent.__wrapped__ = create_deerflow_agent  # type: ignore[attr-defined]


def __getattr__(name: str) -> Any:
    """Delegate non-renamed factory internals to the implementation module."""

    return getattr(_implementation_factory, name)


def __dir__() -> list[str]:
    return sorted({*globals(), *dir(_implementation_factory)})


__all__ = [
    "create_deerflow_agent",
    "create_vassilflow_agent",
]
