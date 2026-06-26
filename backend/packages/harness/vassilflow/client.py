"""Client facade for VassilFlow integrations."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_implementation_client = import_module("deerflow.client")

DeerFlowClient = _implementation_client.DeerFlowClient
StreamEvent = _implementation_client.StreamEvent
StreamEventType = _implementation_client.StreamEventType


class VassilFlowClient(DeerFlowClient):
    """VassilFlow-named embedded client facade.

    The implementation still lives in ``deerflow.client.DeerFlowClient`` during
    the migration window; this subclass gives new integrations a stable
    VassilFlow-owned type name without changing runtime behavior.
    """


def __getattr__(name: str) -> Any:
    """Delegate non-renamed client internals to the implementation module."""

    return getattr(_implementation_client, name)


def __dir__() -> list[str]:
    return sorted({*globals(), *dir(_implementation_client)})


__all__ = sorted(
    {
        name
        for name in dir(_implementation_client)
        if not name.startswith("_")
    }
    | {"VassilFlowClient"}
)
