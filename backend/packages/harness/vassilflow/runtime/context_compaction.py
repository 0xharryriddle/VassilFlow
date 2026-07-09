"""Manual thread-context compaction helpers."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import threading
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from langgraph.checkpoint.base import uuid6

from vassilflow.agents.middlewares.summarization_middleware import VassilFlowSummarizationMiddleware, create_summarization_middleware
from vassilflow.config.app_config import AppConfig, get_app_config
from vassilflow.utils.time import now_iso


class ContextCompactionDisabled(RuntimeError):
    """Raised when manual compaction is requested while summarization is disabled."""


class ContextCompactionFailed(RuntimeError):
    """Raised when a compressible thread cannot be summarized."""


@dataclass(frozen=True)
class ThreadCompactionResult:
    """Result returned after a manual context-compaction attempt."""

    thread_id: str
    compacted: bool
    reason: str | None = None
    removed_message_count: int = 0
    preserved_message_count: int = 0
    summary_updated: bool = False
    checkpoint_id: str | None = None
    total_tokens: int = 0


_thread_locks_guard = threading.Lock()
_thread_locks_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = weakref.WeakKeyDictionary()


@asynccontextmanager
async def thread_context_lock(thread_id: str) -> AsyncIterator[None]:
    """Serialize checkpoint-changing thread operations within the current loop."""
    loop = asyncio.get_running_loop()
    with _thread_locks_guard:
        locks = _thread_locks_by_loop.get(loop)
        if locks is None:
            locks = {}
            _thread_locks_by_loop[loop] = locks
        lock = locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[thread_id] = lock

    async with lock:
        yield


def _create_compaction_middleware(
    *,
    app_config: AppConfig,
    keep: tuple[str, int | float] | None,
) -> VassilFlowSummarizationMiddleware:
    middleware = create_summarization_middleware(app_config=app_config, keep=keep)
    if middleware is None:
        raise ContextCompactionDisabled("Context compaction is disabled.")
    return middleware


async def _call_checkpointer_method(checkpointer: Any, async_name: str, sync_name: str, *args: Any, **kwargs: Any) -> Any:
    async_method = getattr(checkpointer, async_name, None)
    if async_method is not None:
        result = async_method(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result
    sync_method = getattr(checkpointer, sync_name, None)
    if sync_method is None:
        raise AttributeError(f"Missing checkpointer method: {async_name}/{sync_name}")
    result = await asyncio.to_thread(sync_method, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _next_channel_version(checkpointer: Any, current_version: Any) -> Any:
    get_next_version = getattr(checkpointer, "get_next_version", None)
    if callable(get_next_version):
        return get_next_version(current_version, None)
    if isinstance(current_version, int):
        return current_version + 1
    return 1


def _checkpoint_namespace(checkpoint_tuple: Any) -> str:
    config = getattr(checkpoint_tuple, "config", {}) or {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    checkpoint_ns = configurable.get("checkpoint_ns", "") if isinstance(configurable, dict) else ""
    return checkpoint_ns if isinstance(checkpoint_ns, str) else ""


def _checkpoint_id_from_config(config: Any, *, fallback: str | None = None) -> str | None:
    if isinstance(config, dict):
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        if isinstance(checkpoint_id, str):
            return checkpoint_id
    return fallback


async def compact_thread_context(
    checkpointer: Any,
    thread_id: str,
    *,
    keep: tuple[str, int | float] | None = None,
    force: bool = True,
    user_id: str | None = None,
    agent_name: str | None = None,
    app_config: AppConfig | None = None,
) -> ThreadCompactionResult:
    """Summarize old messages in a thread and write a compacted checkpoint."""
    resolved_app_config = app_config or get_app_config()
    middleware = _create_compaction_middleware(app_config=resolved_app_config, keep=keep)

    read_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint_tuple = await _call_checkpointer_method(checkpointer, "aget_tuple", "get_tuple", read_config)
    if checkpoint_tuple is None:
        raise LookupError(f"Thread {thread_id} checkpoint not found")

    checkpoint: dict[str, Any] = dict(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata: dict[str, Any] = dict(getattr(checkpoint_tuple, "metadata", {}) or {})
    channel_values: dict[str, Any] = dict(checkpoint.get("channel_values", {}) or {})
    messages = channel_values.get("messages")
    if not isinstance(messages, list) or not messages:
        return ThreadCompactionResult(thread_id=thread_id, compacted=False, reason="not_enough_messages")

    runtime_context = {"thread_id": thread_id, "user_id": user_id}
    if agent_name:
        runtime_context["agent_name"] = agent_name
    runtime = SimpleNamespace(context=runtime_context)

    try:
        result = await middleware.acompact_state({"messages": list(messages)}, runtime, force=force)  # type: ignore[arg-type]
    except Exception as exc:
        raise ContextCompactionFailed("Failed to compact thread context.") from exc

    if result is None:
        return ThreadCompactionResult(thread_id=thread_id, compacted=False, reason="not_enough_messages")

    channel_values["messages"] = list(result.compacted_messages)
    checkpoint["channel_values"] = channel_values

    channel_versions = dict(checkpoint.get("channel_versions", {}) or {})
    next_version = _next_channel_version(checkpointer, channel_versions.get("messages"))
    channel_versions["messages"] = next_version
    checkpoint["channel_versions"] = channel_versions
    checkpoint["id"] = str(uuid6())
    checkpoint["ts"] = now_iso()

    metadata["source"] = "update"
    metadata["updated_at"] = now_iso()
    prev_step = metadata.get("step")
    metadata["step"] = (prev_step + 1) if isinstance(prev_step, int) else 1
    metadata["writes"] = {
        "manual_compaction": {
            "messages": {
                "removed": len(result.messages_to_summarize),
                "preserved": len(result.preserved_messages),
            },
            "summary": {
                "sha256": hashlib.sha256(result.summary_text.encode("utf-8")).hexdigest(),
                "chars": len(result.summary_text),
            },
        }
    }

    write_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": _checkpoint_namespace(checkpoint_tuple)}}
    new_config = await _call_checkpointer_method(
        checkpointer,
        "aput",
        "put",
        write_config,
        checkpoint,
        metadata,
        {"messages": next_version},
    )

    return ThreadCompactionResult(
        thread_id=thread_id,
        compacted=True,
        removed_message_count=len(result.messages_to_summarize),
        preserved_message_count=len(result.preserved_messages),
        summary_updated=True,
        checkpoint_id=_checkpoint_id_from_config(new_config, fallback=checkpoint["id"]),
        total_tokens=result.total_tokens,
    )
