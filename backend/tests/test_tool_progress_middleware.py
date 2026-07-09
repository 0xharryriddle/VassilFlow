"""Tests for ToolProgressMiddleware state machine."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from vassilflow.agents.middlewares.tool_progress_middleware import (
    ToolPhaseState,
    ToolProgressMiddleware,
    is_near_duplicate,
    word_set,
)
from vassilflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, ToolResultMeta
from vassilflow.config.tool_progress_config import ToolProgressConfig


def _make_runtime(thread_id: str = "t1", run_id: str = "r1") -> MagicMock:
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id, "run_id": run_id}
    return runtime


def _make_tool_request(
    tool_name: str = "web_search",
    *,
    runtime: MagicMock | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": f"tc-{tool_name}"},
        runtime=runtime or _make_runtime(),
    )


def _meta_kwargs(
    *,
    status: str = "success",
    error_type: str | None = None,
    recoverable_by_model: bool = True,
    recommended_next_action: str = "continue",
    source: str = "content_analysis",
) -> dict[str, object]:
    return {
        TOOL_META_KEY: {
            "status": status,
            "error_type": error_type,
            "recoverable_by_model": recoverable_by_model,
            "recommended_next_action": recommended_next_action,
            "source": source,
        }
    }


def _make_tool_message(
    content: str = "A" * 200,
    *,
    tool_name: str = "web_search",
    meta_kwargs: dict[str, object] | None = None,
    status: str = "success",
) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=f"tc-{tool_name}",
        name=tool_name,
        status=status,
        additional_kwargs=meta_kwargs if meta_kwargs is not None else _meta_kwargs(),
    )


def _make_error_message(
    *,
    tool_name: str = "web_search",
    error_type: str = "no_results",
    recoverable_by_model: bool = True,
    recommended_next_action: str = "rewrite_query",
) -> ToolMessage:
    return _make_tool_message(
        "Error: no results found",
        tool_name=tool_name,
        status="error",
        meta_kwargs=_meta_kwargs(
            status="error",
            error_type=error_type,
            recoverable_by_model=recoverable_by_model,
            recommended_next_action=recommended_next_action,
        ),
    )


def _make_non_recoverable_error_message() -> ToolMessage:
    return _make_error_message(
        error_type="rate_limited",
        recoverable_by_model=False,
        recommended_next_action="summarize",
    )


def _make_model_request(messages: list, runtime: MagicMock) -> MagicMock:
    request = MagicMock()
    request.messages = list(messages)
    request.runtime = runtime

    def _override(**kwargs) -> MagicMock:
        updated = MagicMock()
        updated.messages = kwargs.get("messages", request.messages)
        updated.runtime = runtime
        updated.override = request.override
        return updated

    request.override = _override
    return request


def _make_mw(**kwargs) -> ToolProgressMiddleware:
    defaults = {
        "stagnation_threshold": 3,
        "warn_escalation_count": 2,
        "inject_assessment": True,
        "jaccard_threshold": 0.8,
        "min_words": 5,
    }
    defaults.update(kwargs)
    return ToolProgressMiddleware(**defaults)


def test_word_set_and_near_duplicate_helpers():
    assert "go" not in word_set("go quick brown fox")
    assert "quick" in word_set("go quick brown fox")

    base = frozenset("alpha bravo charlie delta echo foxtrot golf hotel".split())
    below = frozenset("alpha bravo charlie delta echo foxtrot golf india".split())
    above = frozenset("alpha bravo charlie delta echo foxtrot golf hotel india".split())

    assert not is_near_duplicate(below, [base], threshold=0.8, min_words=5)
    assert is_near_duplicate(above, [base], threshold=0.8, min_words=5)


def test_repeated_recoverable_errors_reach_warned_and_inject_hint():
    mw = _make_mw(stagnation_threshold=2)
    runtime = _make_runtime()
    request = _make_tool_request(runtime=runtime)
    error_msg = _make_error_message()

    mw.wrap_tool_call(request, lambda _request: error_msg)
    mw.wrap_tool_call(request, lambda _request: error_msg)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "warned"
    assert state.consecutive_problems == 2
    assert "PROGRESS HINT" in mw._drain_pending(runtime)[0]


def test_non_recoverable_errors_escalate_to_blocked_and_intercept_next_call():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1)
    runtime = _make_runtime()
    request = _make_tool_request(runtime=runtime)
    error_msg = _make_non_recoverable_error_message()
    call_count = 0

    def handler(_request):
        nonlocal call_count
        call_count += 1
        return error_msg

    for _ in range(3):
        mw.wrap_tool_call(request, handler)

    assert mw._phase_states["t1"]["web_search"].phase == "blocked"
    before = call_count

    result = mw.wrap_tool_call(request, handler)

    assert call_count == before
    assert isinstance(result, ToolMessage)
    assert "[TOOL_BLOCKED]" in result.content
    assert result.additional_kwargs[TOOL_META_KEY]["source"] == "progress_middleware"


def test_auth_error_immediately_blocks():
    mw = _make_mw(stagnation_threshold=5)
    request = _make_tool_request()
    auth_msg = _make_error_message(
        error_type="auth",
        recoverable_by_model=False,
        recommended_next_action="stop",
    )

    mw.wrap_tool_call(request, lambda _request: auth_msg)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "blocked"
    assert state.consecutive_problems == 1


def test_good_result_after_warning_resets_to_active():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    request = _make_tool_request()
    error_msg = _make_error_message()
    good_msg = _make_tool_message("fresh unique successful content with many words")

    mw.wrap_tool_call(request, lambda _request: error_msg)
    mw.wrap_tool_call(request, lambda _request: error_msg)
    mw.wrap_tool_call(request, lambda _request: good_msg)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "active"
    assert state.consecutive_problems == 0


def test_duplicate_success_counts_as_problem():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    request = _make_tool_request()
    content = "apple banana cherry delta echo foxtrot golf hotel india juliet"

    mw.wrap_tool_call(request, lambda _request: _make_tool_message(content))
    mw.wrap_tool_call(request, lambda _request: _make_tool_message(content))

    assert mw._phase_states["t1"]["web_search"].consecutive_problems == 1


def test_before_agent_resets_run_states():
    mw = _make_mw()
    runtime = _make_runtime()
    mw._phase_states["t1"] = {
        "web_search": ToolPhaseState(
            phase="blocked",
            consecutive_problems=4,
            block_reason="blocked",
            recent_word_sets=(frozenset({"old"}),),
        )
    }

    mw.before_agent({}, runtime)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "active"
    assert state.consecutive_problems == 0
    assert state.block_reason is None
    assert state.recent_word_sets == ()


def test_wrap_model_call_drains_and_injects_hints():
    mw = _make_mw(stagnation_threshold=2)
    runtime = _make_runtime()
    request = _make_tool_request(runtime=runtime)
    error_msg = _make_error_message()

    mw.wrap_tool_call(request, lambda _request: error_msg)
    mw.wrap_tool_call(request, lambda _request: error_msg)

    model_request = _make_model_request([], runtime)
    captured: list = []

    def model_handler(request):
        captured.extend(request.messages)
        return MagicMock()

    mw.wrap_model_call(model_request, model_handler)

    hints = [message for message in captured if isinstance(message, HumanMessage)]
    assert len(hints) == 1
    assert "PROGRESS HINT" in hints[0].content


def test_from_config_empty_exempt_tools_clears_defaults():
    middleware = ToolProgressMiddleware.from_config(ToolProgressConfig(enabled=True, exempt_tools=set()))

    assert middleware._exempt_tools == set()


def test_malformed_or_missing_meta_passthrough(caplog):
    mw = _make_mw()
    request = _make_tool_request()
    bad_msg = _make_tool_message(
        "content",
        meta_kwargs={TOOL_META_KEY: {"unexpected_field": True}},
    )
    missing_msg = _make_tool_message("content", meta_kwargs={})

    assert mw.wrap_tool_call(request, lambda _request: bad_msg) is bad_msg
    with caplog.at_level("WARNING"):
        assert mw.wrap_tool_call(request, lambda _request: missing_msg) is missing_msg

    assert "web_search" not in mw._phase_states.get("t1", {})
    assert any("vassilflow_tool_meta missing" in record.message for record in caplog.records)


def test_blocked_state_is_terminal():
    mw = _make_mw()
    blocked_state = ToolPhaseState(
        phase="blocked",
        consecutive_problems=3,
        block_reason="already blocked",
    )
    meta = ToolResultMeta(
        **_meta_kwargs(
            status="error",
            error_type="no_results",
            recoverable_by_model=True,
            recommended_next_action="rewrite_query",
        )[TOOL_META_KEY]
    )

    new_state, hint = mw._assess_and_transition(blocked_state, meta, "")

    assert new_state is blocked_state
    assert hint is None


def test_command_and_no_runtime_results_passthrough():
    mw = _make_mw()
    command = Command(goto="next")
    no_runtime_request = SimpleNamespace(tool_call={"name": "web_search", "id": "tc-1"})

    assert mw.wrap_tool_call(_make_tool_request(), lambda _request: command) is command
    msg = _make_tool_message()
    assert mw.wrap_tool_call(no_runtime_request, lambda _request: msg) is msg


@pytest.mark.anyio
async def test_async_wrap_tool_call_mirrors_sync_blocking():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1)
    request = _make_tool_request()
    error_msg = _make_non_recoverable_error_message()

    for _ in range(3):
        await mw.awrap_tool_call(request, AsyncMock(return_value=error_msg))

    result = await mw.awrap_tool_call(request, AsyncMock(return_value=error_msg))

    assert isinstance(result, ToolMessage)
    assert "[TOOL_BLOCKED]" in result.content
