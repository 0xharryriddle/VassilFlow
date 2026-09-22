"""Tests for ClarificationMiddleware, focusing on options type coercion."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import add_messages
from pydantic import PrivateAttr

from vassilflow.agents.middlewares.clarification_middleware import (
    ClarificationMiddleware,
    find_latest_resolved_clarification,
    is_resolved_clarification_context_message,
)
from vassilflow.tools.builtins import ask_clarification_tool


def _make_model_request(messages: list) -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=messages,
        state={"messages": list(messages)},
    )


class _ClarificationAwareModel(BaseChatModel):
    """Fake model that repeats clarification unless resolved context is present."""

    call_count: int = 0
    _seen_messages: list[list[Any]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-clarification-aware"

    @property
    def seen_messages(self) -> list[list[Any]]:
        return self._seen_messages

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        self._seen_messages.append(list(messages))

        if self.call_count == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_clarification",
                        "id": "clarify-1",
                        "args": {"question": "Which harness do you mean?"},
                        "type": "tool_call",
                    }
                ],
            )
        elif any(is_resolved_clarification_context_message(message) for message in messages):
            message = AIMessage(content="Researching harness agents now.")
        else:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_clarification",
                        "id": "clarify-repeat",
                        "args": {"question": "Which harness do you mean?"},
                        "type": "tool_call",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.fixture
def middleware():
    return ClarificationMiddleware()


class TestFormatClarificationMessage:
    """Tests for _format_clarification_message options handling."""

    def test_options_as_native_list(self, middleware):
        """Normal case: options is already a list."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": ["dev", "staging", "prod"],
        }
        result = middleware._format_clarification_message(args)
        assert "1. dev" in result
        assert "2. staging" in result
        assert "3. prod" in result

    def test_options_as_json_string(self, middleware):
        """Bug case (#1995): model serializes options as a JSON string."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": json.dumps(["dev", "staging", "prod"]),
        }
        result = middleware._format_clarification_message(args)
        assert "1. dev" in result
        assert "2. staging" in result
        assert "3. prod" in result
        # Must NOT contain per-character output
        assert "1. [" not in result
        assert '2. "' not in result

    def test_options_as_json_string_scalar(self, middleware):
        """JSON string decoding to a non-list scalar is treated as one option."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": json.dumps("development"),
        }
        result = middleware._format_clarification_message(args)
        assert "1. development" in result
        # Must be a single option, not per-character iteration.
        assert "2." not in result

    def test_options_as_plain_string(self, middleware):
        """Edge case: options is a non-JSON string, treated as single option."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": "just one option",
        }
        result = middleware._format_clarification_message(args)
        assert "1. just one option" in result

    def test_options_none(self, middleware):
        """Options is None — no options section rendered."""
        args = {
            "question": "Tell me more",
            "clarification_type": "missing_info",
            "options": None,
        }
        result = middleware._format_clarification_message(args)
        assert "1." not in result

    def test_options_empty_list(self, middleware):
        """Options is an empty list — no options section rendered."""
        args = {
            "question": "Tell me more",
            "clarification_type": "missing_info",
            "options": [],
        }
        result = middleware._format_clarification_message(args)
        assert "1." not in result

    def test_options_missing(self, middleware):
        """Options key is absent — defaults to empty list."""
        args = {
            "question": "Tell me more",
            "clarification_type": "missing_info",
        }
        result = middleware._format_clarification_message(args)
        assert "1." not in result

    def test_context_included(self, middleware):
        """Context is rendered before the question."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "context": "Need target env for config",
            "options": ["dev", "prod"],
        }
        result = middleware._format_clarification_message(args)
        assert "Need target env for config" in result
        assert "Which env?" in result
        assert "1. dev" in result

    def test_json_string_with_mixed_types(self, middleware):
        """JSON string containing non-string elements still works."""
        args = {
            "question": "Pick one",
            "clarification_type": "approach_choice",
            "options": json.dumps(["Option A", 2, True, None]),
        }
        result = middleware._format_clarification_message(args)
        assert "1. Option A" in result
        assert "2. 2" in result
        assert "3. True" in result
        assert "4. None" in result


class TestHumanInputPayload:
    """Structured clarification requests should be available to UI clients."""

    def test_payload_with_options(self, middleware):
        payload = middleware._build_human_input_payload(
            {
                "question": "Which environment should I deploy to?",
                "clarification_type": "approach_choice",
                "context": "Need the target environment for config.",
                "options": ["development", "staging", "production"],
            },
            tool_call_id="call-abc",
            request_id="clarification:call-abc",
        )

        assert payload == {
            "version": 1,
            "kind": "human_input_request",
            "source": "ask_clarification",
            "request_id": "clarification:call-abc",
            "tool_call_id": "call-abc",
            "clarification_type": "approach_choice",
            "question": "Which environment should I deploy to?",
            "context": "Need the target environment for config.",
            "input_mode": "choice_with_other",
            "options": [
                {"id": "option-1", "label": "development", "value": "development"},
                {"id": "option-2", "label": "staging", "value": "staging"},
                {"id": "option-3", "label": "production", "value": "production"},
            ],
        }

    def test_payload_without_options_is_free_text(self, middleware):
        payload = middleware._build_human_input_payload(
            {
                "question": "Tell me more",
                "clarification_type": "missing_info",
                "options": None,
            },
            tool_call_id="call-abc",
            request_id="clarification:call-abc",
        )

        assert payload["input_mode"] == "free_text"
        assert "options" not in payload


class TestClarificationCommandIdempotency:
    """Clarification tool-call retries should not duplicate messages in state."""

    def test_repeated_tool_call_uses_stable_message_id(self, middleware):
        request = SimpleNamespace(
            tool_call={
                "name": "ask_clarification",
                "id": "call-clarify-1",
                "args": {
                    "question": "Which environment should I use?",
                    "clarification_type": "approach_choice",
                    "options": ["dev", "prod"],
                },
            }
        )

        first = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))
        second = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))

        first_message = first.update["messages"][0]
        second_message = second.update["messages"][0]

        assert first_message.id == "clarification:call-clarify-1"
        assert second_message.id == first_message.id
        assert second_message.tool_call_id == first_message.tool_call_id
        assert first_message.artifact["human_input"]["request_id"] == "clarification:call-clarify-1"
        assert first_message.artifact["human_input"]["tool_call_id"] == "call-clarify-1"
        assert first_message.artifact["human_input"]["input_mode"] == "choice_with_other"

        merged = add_messages(add_messages([], [first_message]), [second_message])

        assert len(merged) == 1
        assert merged[0].id == "clarification:call-clarify-1"
        assert merged[0].content == first_message.content
        assert merged[0].artifact == first_message.artifact

    def test_missing_tool_call_id_still_gets_stable_message_id(self, middleware):
        request = SimpleNamespace(
            tool_call={
                "name": "ask_clarification",
                "args": {
                    "question": "Which environment should I use?",
                    "clarification_type": "missing_info",
                },
            }
        )

        first = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))
        second = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))

        first_message = first.update["messages"][0]
        second_message = second.update["messages"][0]

        assert first_message.id.startswith("clarification:")
        assert second_message.id == first_message.id

        merged = add_messages(add_messages([], [first_message]), [second_message])

        assert len(merged) == 1


class TestResolvedClarificationContext:
    """Resolved clarification answers should remain visible to later model calls."""

    def test_finds_latest_resolved_clarification_with_ai_tool_call(self):
        ai_call = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ask_clarification",
                    "id": "clarify-1",
                    "args": {"question": "Which harness do you mean?"},
                }
            ],
        )
        tool_message = ToolMessage(
            content="Which harness do you mean?",
            tool_call_id="clarify-1",
            name="ask_clarification",
        )
        answer = HumanMessage(content="harness agent", id="answer-1")

        resolved = find_latest_resolved_clarification(
            [
                HumanMessage(content="Research harness"),
                ai_call,
                tool_message,
                HumanMessage(content="internal", additional_kwargs={"hide_from_ui": True}),
                answer,
                AIMessage(content="", tool_calls=[{"name": "web_search", "id": "search-1", "args": {}}]),
            ]
        )

        assert resolved is not None
        assert resolved.question == "Which harness do you mean?"
        assert resolved.answer == "harness agent"
        assert resolved.ai_message is ai_call
        assert resolved.transcript_messages == (ai_call, tool_message, answer)

    def test_wrap_model_call_injects_hidden_context_before_answer(self, middleware):
        ai_call = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ask_clarification",
                    "id": "clarify-1",
                    "args": {"question": "Which harness do you mean?"},
                }
            ],
        )
        answer = HumanMessage(
            content="--- BEGIN USER INPUT ---\nharness agent\n--- END USER INPUT ---",
            id="answer-1",
        )
        request = _make_model_request(
            [
                HumanMessage(content="Deep research harness", id="question-1"),
                ai_call,
                ToolMessage(
                    content="Which harness do you mean?",
                    tool_call_id="clarify-1",
                    name="ask_clarification",
                ),
                answer,
            ]
        )
        captured = {}

        def handler(model_request: ModelRequest):
            captured["messages"] = model_request.messages
            return AIMessage(content="ok")

        result = middleware.wrap_model_call(request, handler)

        assert result.content == "ok"
        messages = captured["messages"]
        hidden = [message for message in messages if is_resolved_clarification_context_message(message)]
        assert len(hidden) == 1
        assert hidden[0].additional_kwargs["hide_from_ui"] is True
        assert "Which harness do you mean?" in hidden[0].content
        assert "harness agent" in hidden[0].content
        assert "--- BEGIN USER INPUT ---" not in hidden[0].content
        assert messages.index(hidden[0]) == messages.index(answer) - 1

    def test_wrap_model_call_accepts_hidden_human_input_response(self, middleware):
        answer = HumanMessage(
            content='For your clarification "Which harness do you mean?", my answer is: harness agent',
            id="answer-1",
            additional_kwargs={
                "hide_from_ui": True,
                "human_input_response": {
                    "version": 1,
                    "kind": "human_input_response",
                    "source": "ask_clarification",
                    "request_id": "clarification:clarify-1",
                    "response_kind": "text",
                    "value": "harness agent",
                },
            },
        )
        request = _make_model_request(
            [
                HumanMessage(content="Deep research harness", id="question-1"),
                ToolMessage(
                    content="Which harness do you mean?",
                    tool_call_id="clarify-1",
                    name="ask_clarification",
                ),
                answer,
            ]
        )
        captured = {}

        def handler(model_request: ModelRequest):
            captured["messages"] = model_request.messages
            return AIMessage(content="ok")

        middleware.wrap_model_call(request, handler)

        hidden = [message for message in captured["messages"] if is_resolved_clarification_context_message(message)]
        assert len(hidden) == 1
        assert "Which harness do you mean?" in hidden[0].content
        assert "harness agent" in hidden[0].content

    def test_wrap_model_call_does_not_inject_until_user_answers(self, middleware):
        request = _make_model_request(
            [
                HumanMessage(content="Deep research harness"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ask_clarification",
                            "id": "clarify-1",
                            "args": {"question": "Which harness do you mean?"},
                        }
                    ],
                ),
                ToolMessage(
                    content="Which harness do you mean?",
                    tool_call_id="clarify-1",
                    name="ask_clarification",
                ),
            ]
        )
        captured = {}

        def handler(model_request: ModelRequest):
            captured["request"] = model_request
            return AIMessage(content="ok")

        middleware.wrap_model_call(request, handler)

        assert captured["request"] is request

    def test_wrap_model_call_ignores_hidden_and_summary_answers(self, middleware):
        request = _make_model_request(
            [
                HumanMessage(content="Deep research harness"),
                ToolMessage(
                    content="Which harness do you mean?",
                    tool_call_id="clarify-1",
                    name="ask_clarification",
                ),
                HumanMessage(content="internal", additional_kwargs={"hide_from_ui": True}),
                HumanMessage(content="summary text", name="summary"),
            ]
        )
        captured = {}

        def handler(model_request: ModelRequest):
            captured["request"] = model_request
            return AIMessage(content="ok")

        middleware.wrap_model_call(request, handler)

        assert captured["request"] is request

    def test_wrap_model_call_does_not_duplicate_existing_context(self, middleware):
        existing = HumanMessage(
            content="<resolved_clarification>already injected</resolved_clarification>",
            additional_kwargs={"hide_from_ui": True, "resolved_clarification_context": True},
        )
        request = _make_model_request(
            [
                existing,
                ToolMessage(
                    content="Which harness do you mean?",
                    tool_call_id="clarify-1",
                    name="ask_clarification",
                ),
                HumanMessage(content="harness agent"),
            ]
        )
        captured = {}

        def handler(model_request: ModelRequest):
            captured["messages"] = model_request.messages
            return AIMessage(content="ok")

        middleware.wrap_model_call(request, handler)

        assert [message for message in captured["messages"] if is_resolved_clarification_context_message(message)] == [existing]

    def test_awrap_model_call_injects_hidden_context(self, middleware):
        request = _make_model_request(
            [
                ToolMessage(
                    content="Which harness do you mean?",
                    tool_call_id="clarify-1",
                    name="ask_clarification",
                ),
                HumanMessage(content="harness agent"),
            ]
        )
        captured = {}

        async def handler(model_request: ModelRequest):
            captured["messages"] = model_request.messages
            return AIMessage(content="ok")

        result = asyncio.run(middleware.awrap_model_call(request, handler))

        assert result.content == "ok"
        assert any(is_resolved_clarification_context_message(message) for message in captured["messages"])

    def test_graph_follow_up_after_clarification_uses_resolved_context(self):
        model = _ClarificationAwareModel()
        agent = create_agent(
            model=model,
            tools=[ask_clarification_tool],
            middleware=[ClarificationMiddleware()],
            checkpointer=InMemorySaver(),
        )
        config = {"configurable": {"thread_id": "clarification-graph-follow-up"}}

        first = agent.invoke({"messages": [HumanMessage(content="Deep research harness", id="u1")]}, config)
        assert any(isinstance(message, ToolMessage) and message.name == "ask_clarification" for message in first["messages"])

        second = agent.invoke({"messages": [HumanMessage(content="harness agent", id="u2")]}, config)

        assert model.call_count == 2
        second_model_messages = model.seen_messages[-1]
        hidden = [message for message in second_model_messages if is_resolved_clarification_context_message(message)]
        assert len(hidden) == 1
        assert "Which harness do you mean?" in hidden[0].content
        assert "harness agent" in hidden[0].content
        assert second["messages"][-1].content == "Researching harness agents now."
        assert not any(is_resolved_clarification_context_message(message) for message in second["messages"])
        assert not any(isinstance(message, ToolMessage) and message.name == "ask_clarification" and getattr(message, "tool_call_id", None) == "clarify-repeat" for message in second["messages"])
