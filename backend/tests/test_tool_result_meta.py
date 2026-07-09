"""Tests for VassilFlow tool result metadata normalization."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from vassilflow.agents.middlewares.tool_result_meta import (
    TOOL_META_KEY,
    ToolResultMeta,
    normalize_tool_message,
    normalize_tool_result,
    stamp_exception_meta,
)


def _make_msg(
    content: str,
    *,
    status: str = "success",
    kwargs: dict[str, object] | None = None,
) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id="tc-1",
        name="test_tool",
        status=status,
        additional_kwargs=kwargs or {},
    )


def _meta(msg: ToolMessage) -> dict[str, object]:
    return msg.additional_kwargs[TOOL_META_KEY]


def test_existing_meta_is_preserved():
    existing = {"status": "success", "source": "custom"}
    msg = _make_msg("hello", kwargs={TOOL_META_KEY: existing})

    result = normalize_tool_message(msg)

    assert result.additional_kwargs[TOOL_META_KEY] is existing


@pytest.mark.parametrize(
    "snippet,expected_type",
    [
        ("Error: 401 unauthorized", "auth"),
        ("Error: permission denied for path", "permission"),
        ("Error: rate limit exceeded", "rate_limited"),
        ("Error: connection timeout", "transient"),
        ("Error: tool not configured", "config"),
        ("Error: no results found for query", "no_results"),
        ("Error: file not found", "not_found"),
        ("Error: internal error 500", "internal"),
        ("Error: something unexpected happened", "unknown"),
    ],
)
def test_error_prefix_classification(snippet: str, expected_type: str):
    result = normalize_tool_message(_make_msg(snippet, status="error"))
    meta = _meta(result)

    assert meta["status"] == "error"
    assert meta["error_type"] == expected_type
    assert meta["source"] == "tool_return"


def test_no_api_key_is_config_not_auth():
    result = normalize_tool_message(_make_msg("Error: no api key configured", status="error"))
    meta = _meta(result)

    assert meta["error_type"] == "config"
    assert meta["recommended_next_action"] == "stop"
    assert meta["recoverable_by_model"] is False


def test_nonstandard_json_error_uses_error_field_only():
    content = '{"error": "api limit exceeded", "query": "connection timeout"}'
    result = normalize_tool_message(_make_msg(content, status="error"))
    meta = _meta(result)

    assert meta["status"] == "error"
    assert meta["source"] == "tool_return"
    assert meta["error_type"] == "unknown"


def test_json_without_error_key_is_unknown_on_error_status():
    result = normalize_tool_message(_make_msg('{"user_id": 401, "action": "login"}', status="error"))
    meta = _meta(result)

    assert meta["status"] == "error"
    assert meta["error_type"] == "unknown"
    assert meta["recommended_next_action"] != "stop"


def test_success_json_error_is_classified():
    result = normalize_tool_message(_make_msg('{"error": "BRAVE_SEARCH_API_KEY is not configured"}'))
    meta = _meta(result)

    assert meta["status"] == "error"
    assert meta["error_type"] == "config"


@pytest.mark.parametrize(
    "error_value",
    ["none", "None", "null", "false", "no", "ok", "success", "n/a", ""],
)
def test_semantic_zero_error_strings_are_not_errors(error_value: str):
    result = normalize_tool_message(_make_msg(json.dumps({"error": error_value, "results": ["item"]})))

    assert _meta(result)["status"] != "error"


@pytest.mark.parametrize(
    "content,expected_error_type",
    [
        ("Error: HTTP 500 Internal Server Error", "internal"),
        ("Error: 401 Unauthorized", "auth"),
        ("Error: 404 Not Found", "not_found"),
        ("Error: took 500ms to respond", "unknown"),
        ("Error: query returned 4010 rows", "unknown"),
    ],
)
def test_numeric_keyword_word_boundary(content: str, expected_error_type: str):
    result = normalize_tool_message(_make_msg(content, status="error"))

    assert _meta(result)["error_type"] == expected_error_type


def test_no_results_success_response_is_partial_success():
    result = normalize_tool_message(_make_msg("No results found for query"))
    meta = _meta(result)

    assert meta["status"] == "partial_success"
    assert meta["recommended_next_action"] == "rewrite_query"


def test_stamp_exception_meta_overwrites_existing_meta_and_preserves_other_kwargs():
    msg = _make_msg(
        "Error: no results found",
        status="error",
        kwargs={TOOL_META_KEY: {"source": "tool_return"}, "subagent_status": "running"},
    )

    result = stamp_exception_meta(msg, "PermissionError: access denied")
    meta = _meta(result)

    assert meta["source"] == "exception"
    assert meta["error_type"] == "permission"
    assert result.additional_kwargs["subagent_status"] == "running"


def test_tool_result_meta_dataclass_round_trip():
    result = normalize_tool_message(_make_msg("A" * 200))
    meta = ToolResultMeta(**_meta(result))

    assert meta.status == "success"
    assert meta.recommended_next_action == "continue"


def test_normalize_tool_result_passthrough_command():
    cmd = Command(goto="next_node")

    assert normalize_tool_result(cmd) is cmd
