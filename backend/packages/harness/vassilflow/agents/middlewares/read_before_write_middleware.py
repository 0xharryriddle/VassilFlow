"""Deterministic read-before-write gate for file-modifying tools.

The gate enforces a simple invariant: modifying an existing file requires a
``read_file`` of that file's current version earlier in the conversation.
Read marks live on ToolMessages so summarization naturally invalidates them
when the read result leaves context.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import posixpath
import threading
import weakref
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from vassilflow.agents.middlewares.tool_result_meta import normalize_tool_result
from vassilflow.sandbox.tools import read_current_file_content

logger = logging.getLogger(__name__)

READ_MARK_KEY = "vassilflow_read_mark"

_READ_TOOLS = frozenset({"read_file"})
_GATED_WRITE_TOOLS = frozenset({"write_file", "str_replace"})
_UNINSPECTABLE_CONTENT_PREFIX = "Error:"

_BLOCK_MESSAGE = (
    "Error: {tool_name} blocked - {path} already exists and you have not read its current version. "
    "Any write invalidates earlier reads, so re-read before every modification. "
    "Call read_file on it, check what is already there, then retry."
)

_GATE_LOCKS: weakref.WeakValueDictionary[tuple[str, str], threading.Lock] = weakref.WeakValueDictionary()
_GATE_LOCKS_GUARD = threading.Lock()


def _get_gate_lock(scope: str, norm_path: str) -> threading.Lock:
    key = (scope, norm_path)
    with _GATE_LOCKS_GUARD:
        lock = _GATE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _GATE_LOCKS[key] = lock
        return lock


def _normalize_mark_path(path: str) -> str:
    return posixpath.normpath(path)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ReadBeforeWriteMiddleware(AgentMiddleware):
    """Version gate for writes to existing files."""

    def __init__(self, content_reader: Callable[[Any, str], str] | None = None) -> None:
        super().__init__()
        self._content_reader = content_reader or read_current_file_content

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        name = request.tool_call.get("name")
        if name in _GATED_WRITE_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return handler(request)
            with self._lock_for(request, path):
                blocked = self._check_write_gate(request)
                if blocked is not None:
                    return normalize_tool_result(blocked)
                return handler(request)
        if name in _READ_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return handler(request)
            with self._lock_for(request, path):
                result = handler(request)
                self._attach_read_mark(request, result)
                return result
        return handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        name = request.tool_call.get("name")
        if name in _GATED_WRITE_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return await handler(request)
            lock = self._lock_for(request, path)
            await asyncio.to_thread(lock.acquire)
            try:
                blocked = await asyncio.to_thread(self._check_write_gate, request)
                if blocked is not None:
                    return normalize_tool_result(blocked)
                return await handler(request)
            finally:
                lock.release()
        if name in _READ_TOOLS:
            path = self._requested_path(request)
            if path is None:
                return await handler(request)
            lock = self._lock_for(request, path)
            await asyncio.to_thread(lock.acquire)
            try:
                result = await handler(request)
                await asyncio.to_thread(self._attach_read_mark, request, result)
                return result
            finally:
                lock.release()
        return await handler(request)

    def _lock_for(self, request: ToolCallRequest, path: str) -> threading.Lock:
        return _get_gate_lock(self._lock_scope(request), _normalize_mark_path(path))

    @staticmethod
    def _lock_scope(request: ToolCallRequest) -> str:
        context = getattr(request.runtime, "context", None)
        if isinstance(context, dict):
            thread_id = context.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
        state = request.state
        if isinstance(state, dict):
            sandbox_state = state.get("sandbox")
            if isinstance(sandbox_state, dict):
                sandbox_id = sandbox_state.get("sandbox_id")
                if isinstance(sandbox_id, str) and sandbox_id:
                    return sandbox_id
        return "global"

    def _check_write_gate(self, request: ToolCallRequest) -> ToolMessage | None:
        tool_call = request.tool_call
        path = self._requested_path(request)
        if path is None:
            return None
        try:
            current = self._content_reader(request.runtime, path)
        except FileNotFoundError:
            return None
        except Exception:
            logger.warning("read-before-write gate could not inspect %r; allowing write", path, exc_info=True)
            return None
        if current.startswith(_UNINSPECTABLE_CONTENT_PREFIX):
            logger.debug("read-before-write gate got error-string read for %r; allowing write", path)
            return None
        norm_path = _normalize_mark_path(path)
        if self._latest_mark_hash(request.state, norm_path) == _content_hash(current):
            return None
        tool_name = str(tool_call.get("name", "write"))
        return ToolMessage(
            content=_BLOCK_MESSAGE.format(tool_name=tool_name, path=path),
            tool_call_id=str(tool_call.get("id", "")),
            name=tool_name,
            status="error",
        )

    @staticmethod
    def _requested_path(request: ToolCallRequest) -> str | None:
        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict):
            return None
        path = args.get("path")
        return path if isinstance(path, str) and path else None

    @staticmethod
    def _latest_mark_hash(state: Any, norm_path: str) -> str | None:
        messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        if not messages:
            return None
        for message in reversed(messages):
            if not isinstance(message, ToolMessage):
                continue
            mark = (message.additional_kwargs or {}).get(READ_MARK_KEY)
            if isinstance(mark, dict) and mark.get("path") == norm_path:
                mark_hash = mark.get("hash")
                return mark_hash if isinstance(mark_hash, str) else None
        return None

    def _attach_read_mark(self, request: ToolCallRequest, result: ToolMessage | Command) -> None:
        path = self._requested_path(request)
        if path is None:
            return
        message = self._extract_tool_message(result)
        if message is None or message.status == "error":
            return
        try:
            content = self._content_reader(request.runtime, path)
        except Exception:
            logger.debug("read-before-write mark skipped for %r: file not hashable", path, exc_info=True)
            return
        if content.startswith(_UNINSPECTABLE_CONTENT_PREFIX):
            logger.debug("read-before-write mark skipped for %r: error-string read channel", path)
            return
        message.additional_kwargs[READ_MARK_KEY] = {
            "path": _normalize_mark_path(path),
            "hash": _content_hash(content),
        }

    @staticmethod
    def _extract_tool_message(result: ToolMessage | Command) -> ToolMessage | None:
        if isinstance(result, ToolMessage):
            return result
        if isinstance(result, Command) and isinstance(result.update, dict):
            candidates = [m for m in result.update.get("messages", []) if isinstance(m, ToolMessage)]
            if candidates:
                return candidates[-1]
        return None
