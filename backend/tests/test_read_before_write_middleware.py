"""Tests for the read-before-write file gate."""

from __future__ import annotations

import asyncio
import hashlib
import posixpath
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from vassilflow.agents.middlewares.read_before_write_middleware import (
    READ_MARK_KEY,
    ReadBeforeWriteMiddleware,
)
from vassilflow.agents.middlewares.tool_result_meta import TOOL_META_KEY
from vassilflow.config.app_config import AppConfig
from vassilflow.config.read_before_write_config import ReadBeforeWriteConfig
from vassilflow.config.sandbox_config import SandboxConfig


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_request(name: str, args: dict, messages=()) -> ToolCallRequest:
    runtime = MagicMock()
    runtime.context = {"thread_id": "thread-rbw"}
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": "call-1"},
        tool=None,
        state={"messages": list(messages)},
        runtime=runtime,
    )


def _marked_read(path: str, content: str, tool_call_id: str = "read-1") -> ToolMessage:
    message = ToolMessage(content=content[:20], tool_call_id=tool_call_id, name="read_file")
    message.additional_kwargs[READ_MARK_KEY] = {"path": posixpath.normpath(path), "hash": _sha(content)}
    return message


def _middleware(files: dict[str, str | Exception]) -> ReadBeforeWriteMiddleware:
    def reader(_runtime, path):
        normalized = posixpath.normpath(path)
        if normalized not in files:
            raise FileNotFoundError(path)
        value = files[normalized]
        if isinstance(value, Exception):
            raise value
        return value

    return ReadBeforeWriteMiddleware(content_reader=reader)


class TestReadCurrentFileContent:
    def test_reads_via_sandbox_with_resolution(self):
        from vassilflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.return_value = "hello"
        runtime = MagicMock()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            assert sandbox_tools.read_current_file_content(runtime, "/mnt/user-data/outputs/report.md") == "hello"
        sandbox.read_file.assert_called_once_with("/mnt/user-data/outputs/report.md")

    def test_propagates_file_not_found(self):
        from vassilflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.side_effect = FileNotFoundError()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            with pytest.raises(FileNotFoundError):
                sandbox_tools.read_current_file_content(MagicMock(), "/mnt/user-data/outputs/missing.md")


class TestReadMarkStamping:
    def test_read_file_success_stamps_full_file_hash(self):
        path = "/mnt/user-data/outputs/report.md"
        middleware = _middleware({path: "line1\nline2\nline3"})
        request = _make_request("read_file", {"description": "d", "path": path, "start_line": 3, "end_line": 3})
        handler = MagicMock(return_value=ToolMessage(content="line3", tool_call_id="call-1", name="read_file"))

        result = middleware.wrap_tool_call(request, handler)

        assert result.additional_kwargs[READ_MARK_KEY] == {"path": path, "hash": _sha("line1\nline2\nline3")}

    def test_error_tool_message_gets_no_mark(self):
        path = "/mnt/user-data/outputs/report.md"
        middleware = _middleware({path: "v1"})
        request = _make_request("read_file", {"description": "d", "path": path})
        handler = MagicMock(return_value=ToolMessage(content="boom", tool_call_id="call-1", name="read_file", status="error"))

        result = middleware.wrap_tool_call(request, handler)

        assert READ_MARK_KEY not in result.additional_kwargs

    def test_non_file_tools_untouched(self):
        middleware = _middleware({})
        request = _make_request("bash", {"description": "d", "command": "ls"})
        expected = ToolMessage(content="ok", tool_call_id="call-1", name="bash")
        handler = MagicMock(return_value=expected)

        assert middleware.wrap_tool_call(request, handler) is expected


class TestWriteGate:
    PATH = "/mnt/user-data/outputs/report.md"

    def test_new_file_write_allowed(self):
        middleware = _middleware({})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v1"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))

        result = middleware.wrap_tool_call(request, handler)

        handler.assert_called_once()
        assert result.status != "error"

    def test_overwrite_existing_without_read_blocked(self):
        middleware = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock()

        result = middleware.wrap_tool_call(request, handler)

        handler.assert_not_called()
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert "read" in result.content.lower()
        assert result.additional_kwargs[TOOL_META_KEY]["recoverable_by_model"] is True

    def test_append_without_read_blocked(self):
        middleware = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "more", "append": True})

        result = middleware.wrap_tool_call(request, MagicMock())

        assert result.status == "error"

    def test_str_replace_without_read_blocked(self):
        middleware = _middleware({self.PATH: "v1"})
        request = _make_request("str_replace", {"description": "d", "path": self.PATH, "old_str": "v1", "new_str": "v2"})

        result = middleware.wrap_tool_call(request, MagicMock())

        assert result.status == "error"

    def test_fresh_mark_allows_write(self):
        middleware = _middleware({self.PATH: "v1"})
        messages = [HumanMessage("hi"), AIMessage(""), _marked_read(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))

        result = middleware.wrap_tool_call(request, handler)

        handler.assert_called_once()
        assert result.status != "error"

    def test_stale_mark_after_modification_blocked(self):
        middleware = _middleware({self.PATH: "v2"})
        messages = [_marked_read(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v3"}, messages)

        result = middleware.wrap_tool_call(request, MagicMock())

        assert result.status == "error"

    def test_mark_removed_by_summarization_blocks(self):
        middleware = _middleware({self.PATH: "v1"})
        messages = [HumanMessage("Here is a summary of the conversation to date.", name="summary")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)

        result = middleware.wrap_tool_call(request, MagicMock())

        assert result.status == "error"

    def test_gate_read_failure_fails_open(self):
        middleware = _middleware({self.PATH: RuntimeError("sandbox hiccup")})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))

        result = middleware.wrap_tool_call(request, handler)

        handler.assert_called_once()
        assert result.status != "error"

    def test_error_string_sandbox_fails_open_and_does_not_mark(self):
        middleware = _middleware({self.PATH: "Error: file not found"})
        write_request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v1"})
        write_handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))

        assert middleware.wrap_tool_call(write_request, write_handler).status != "error"

        read_request = _make_request("read_file", {"description": "d", "path": self.PATH})
        read_handler = MagicMock(return_value=ToolMessage(content="Error: file not found", tool_call_id="call-1", name="read_file"))
        read_result = middleware.wrap_tool_call(read_request, read_handler)
        assert READ_MARK_KEY not in read_result.additional_kwargs


class TestAsyncPaths:
    PATH = "/mnt/user-data/outputs/report.md"

    def test_async_blocked_write_has_tool_meta(self):
        middleware = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})

        async def handler(_request):
            raise AssertionError("handler must not run when blocked")

        result = asyncio.run(middleware.awrap_tool_call(request, handler))

        assert result.status == "error"
        assert result.additional_kwargs[TOOL_META_KEY]["recoverable_by_model"] is True

    def test_parallel_appends_exactly_one_lands(self):
        files = {self.PATH: "v1"}
        middleware = _middleware(files)
        messages = [_marked_read(self.PATH, "v1")]

        def make_handler(suffix: str):
            async def handler(_request):
                await asyncio.sleep(0.02)
                files[self.PATH] = files[self.PATH] + suffix
                return ToolMessage(content="OK", tool_call_id="call-1", name="write_file")

            return handler

        async def run():
            return await asyncio.gather(
                middleware.awrap_tool_call(
                    _make_request("write_file", {"description": "d", "path": self.PATH, "content": "A", "append": True}, messages),
                    make_handler("A"),
                ),
                middleware.awrap_tool_call(
                    _make_request("write_file", {"description": "d", "path": self.PATH, "content": "B", "append": True}, messages),
                    make_handler("B"),
                ),
            )

        results = asyncio.run(run())

        assert sorted(result.status for result in results) == ["error", "success"]
        assert files[self.PATH] in {"v1A", "v1B"}


def _wiring_app_config(**overrides) -> AppConfig:
    return AppConfig(sandbox=SandboxConfig(use="test"), **overrides)


class TestChainWiring:
    def test_enabled_by_default_in_runtime_chain(self):
        from vassilflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware
        from vassilflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware, build_lead_runtime_middlewares

        middlewares = build_lead_runtime_middlewares(app_config=_wiring_app_config())
        types = [type(m) for m in middlewares]

        assert ReadBeforeWriteMiddleware in types
        assert types.index(SandboxAuditMiddleware) < types.index(ReadBeforeWriteMiddleware) < types.index(ToolErrorHandlingMiddleware)

    def test_disabled_removes_middleware(self):
        from vassilflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares

        app_config = _wiring_app_config(read_before_write=ReadBeforeWriteConfig(enabled=False))
        middlewares = build_lead_runtime_middlewares(app_config=app_config)

        assert ReadBeforeWriteMiddleware not in [type(m) for m in middlewares]

    def test_subagents_get_the_gate_too(self):
        from vassilflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        middlewares = build_subagent_runtime_middlewares(app_config=_wiring_app_config())

        assert ReadBeforeWriteMiddleware in [type(m) for m in middlewares]
