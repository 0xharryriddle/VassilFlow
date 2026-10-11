"""Reusable agent and RAG primitives with explicit, application-owned dependencies.

Importing this namespace does not load configuration, open files, start workers,
or import the full ``vassilflow`` application harness.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agents import create_agent
    from .rag import CitationError, RagAnswer, RagPipeline, Source, create_retrieval_tool
    from .subagents import create_subagent_tool

__version__ = "0.1.1"
__all__ = [
    "CitationError",
    "RagAnswer",
    "RagPipeline",
    "Source",
    "create_agent",
    "create_retrieval_tool",
    "create_subagent_tool",
]

_EXPORTS = {
    "create_agent": "agents",
    "CitationError": "rag",
    "RagAnswer": "rag",
    "RagPipeline": "rag",
    "Source": "rag",
    "create_retrieval_tool": "rag",
    "create_subagent_tool": "subagents",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    globals()[name] = value
    return value
