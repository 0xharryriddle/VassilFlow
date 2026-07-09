"""Middleware for intercepting clarification requests and presenting them to the user."""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from vassilflow.agents.human_input import read_human_input_response
from vassilflow.utils.messages import message_to_text

logger = logging.getLogger(__name__)

_SUMMARY_MESSAGE_NAME = "summary"
_RESOLVED_CLARIFICATION_CONTEXT_KEY = "resolved_clarification_context"
_USER_INPUT_BEGIN = "--- BEGIN USER INPUT ---"
_USER_INPUT_END = "--- END USER INPUT ---"


@dataclass(frozen=True)
class ResolvedClarification:
    """A previous clarification request and the user's answer to it."""

    question: str
    answer: str
    tool_message: ToolMessage
    answer_message: HumanMessage
    ai_message: AIMessage | None = None

    @property
    def transcript_messages(self) -> tuple[AIMessage | ToolMessage | HumanMessage, ...]:
        """Messages that must stay together if history is summarized."""
        if self.ai_message is None:
            return (self.tool_message, self.answer_message)
        return (self.ai_message, self.tool_message, self.answer_message)


def is_resolved_clarification_context_message(message: object) -> bool:
    """Return True for request-only hidden context injected by this middleware."""
    return isinstance(message, HumanMessage) and bool(message.additional_kwargs.get(_RESOLVED_CLARIFICATION_CONTEXT_KEY))


def _is_genuine_user_message(message: object) -> bool:
    """Return True for user messages, excluding framework-injected context."""
    if not isinstance(message, HumanMessage):
        return False
    if message.name == _SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui") and read_human_input_response(message.additional_kwargs) is None:
        return False
    return True


def _clean_user_text(text: str) -> str:
    """Strip request-only input boundary markers from text shown to the model."""
    stripped = text.strip()
    if stripped.startswith(_USER_INPUT_BEGIN) and stripped.endswith(_USER_INPUT_END):
        stripped = stripped[len(_USER_INPUT_BEGIN) : -len(_USER_INPUT_END)].strip()
    return stripped


def _tool_call_id(message: ToolMessage) -> str | None:
    value = getattr(message, "tool_call_id", None)
    return value if isinstance(value, str) and value else None


def _ai_message_calls_clarification(message: AIMessage, tool_call_id: str | None) -> bool:
    tool_calls = list(getattr(message, "tool_calls", None) or [])
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        if tool_call_id and call.get("id") == tool_call_id:
            return True
        if not tool_call_id and call.get("name") == "ask_clarification":
            return True

    raw_calls = message.additional_kwargs.get("tool_calls") if isinstance(message.additional_kwargs, dict) else None
    if isinstance(raw_calls, list):
        for call in raw_calls:
            if not isinstance(call, dict):
                continue
            if tool_call_id and call.get("id") == tool_call_id:
                return True
            function = call.get("function")
            if not tool_call_id and isinstance(function, dict) and function.get("name") == "ask_clarification":
                return True
    return False


def _find_ai_message_for_tool_call(messages: list[Any], tool_index: int, tool_message: ToolMessage) -> AIMessage | None:
    tool_call_id = _tool_call_id(tool_message)
    for previous in reversed(messages[:tool_index]):
        if isinstance(previous, HumanMessage) and _is_genuine_user_message(previous):
            return None
        if isinstance(previous, AIMessage) and _ai_message_calls_clarification(previous, tool_call_id):
            return previous
    return None


def _is_clarification_tool_message(message: object) -> bool:
    return isinstance(message, ToolMessage) and message.name == "ask_clarification"


def find_latest_resolved_clarification(messages: list[Any]) -> ResolvedClarification | None:
    """Find the latest ask_clarification tool result followed by a visible user answer."""
    latest: ResolvedClarification | None = None
    pending: tuple[int, ToolMessage, AIMessage | None] | None = None

    for index, message in enumerate(messages):
        if _is_clarification_tool_message(message):
            tool_message = message
            pending = (index, tool_message, _find_ai_message_for_tool_call(messages, index, tool_message))
            latest = None
            continue

        if pending is None or not _is_genuine_user_message(message):
            continue

        _, tool_message, ai_message = pending
        question = message_to_text(tool_message).strip()
        answer = _clean_user_text(message_to_text(message).strip())
        if question and answer:
            latest = ResolvedClarification(
                question=question,
                answer=answer,
                tool_message=tool_message,
                answer_message=message,
                ai_message=ai_message,
            )
        pending = None

    return latest


class ClarificationMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    pass


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """Intercepts clarification tool calls and interrupts execution to present questions to the user.

    When the model calls the `ask_clarification` tool, this middleware:
    1. Intercepts the tool call before execution
    2. Extracts the clarification question and metadata
    3. Formats a user-friendly message
    4. Returns a Command that interrupts execution and presents the question
    5. Waits for user response before continuing

    This replaces the tool-based approach where clarification continued the conversation flow.
    """

    state_schema = ClarificationMiddlewareState

    def _stable_message_id(self, tool_call_id: str, formatted_message: str) -> str:
        """Build a deterministic message ID so retried clarification calls replace, not append."""
        if tool_call_id:
            return f"clarification:{tool_call_id}"
        digest = sha256(formatted_message.encode("utf-8")).hexdigest()[:16]
        return f"clarification:{digest}"

    def _normalize_options(self, raw_options: Any) -> list[str]:
        """Normalize tool-provided options into displayable string values."""
        options = raw_options

        # Some models serialize array parameters as JSON strings instead of
        # native arrays. Deserialize and normalize so rendering always receives
        # a list of strings.
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except (json.JSONDecodeError, TypeError):
                options = [options]

        if options is None:
            return []
        if not isinstance(options, list):
            options = [options]

        return [str(option) for option in options]

    def _build_human_input_payload(self, args: dict[str, Any], *, tool_call_id: str, request_id: str) -> dict[str, Any]:
        """Build the structured UI payload while keeping ToolMessage.content as fallback."""
        options = self._normalize_options(args.get("options", []))
        clarification_type = str(args.get("clarification_type", "missing_info"))

        payload: dict[str, Any] = {
            "version": 1,
            "kind": "human_input_request",
            "source": "ask_clarification",
            "request_id": request_id,
            "clarification_type": clarification_type,
            "question": str(args.get("question") or ""),
            "input_mode": "choice_with_other" if options else "free_text",
        }

        if tool_call_id:
            payload["tool_call_id"] = tool_call_id

        if "context" in args:
            context = args.get("context")
            payload["context"] = None if context is None else str(context)

        if options:
            payload["options"] = [
                {
                    "id": f"option-{index}",
                    "label": option,
                    "value": option,
                }
                for index, option in enumerate(options, 1)
            ]

        return payload

    def _is_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters.

        Args:
            text: Text to check

        Returns:
            True if text contains Chinese characters
        """
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _format_clarification_message(self, args: dict) -> str:
        """Format the clarification arguments into a user-friendly message.

        Args:
            args: The tool call arguments containing clarification details

        Returns:
            Formatted message string
        """
        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        context = args.get("context")
        options = self._normalize_options(args.get("options", []))

        # Type-specific icons
        type_icons = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }

        icon = type_icons.get(clarification_type, "❓")

        # Build the message naturally
        message_parts = []

        # Add icon and question together for a more natural flow
        if context:
            # If there's context, present it first as background
            message_parts.append(f"{icon} {context}")
            message_parts.append(f"\n{question}")
        else:
            # Just the question with icon
            message_parts.append(f"{icon} {question}")

        # Add options in a cleaner format
        if options and len(options) > 0:
            message_parts.append("")  # blank line for spacing
            for i, option in enumerate(options, 1):
                message_parts.append(f"  {i}. {option}")

        return "\n".join(message_parts)

    def _handle_clarification(self, request: ToolCallRequest) -> Command:
        """Handle clarification request and return command to interrupt execution.

        Args:
            request: Tool call request

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Extract clarification arguments
        args = request.tool_call.get("args", {})
        question = args.get("question", "")

        logger.info("Intercepted clarification request")
        logger.debug("Clarification question: %s", question)

        # Format the clarification message
        formatted_message = self._format_clarification_message(args)

        # Get the tool call ID
        tool_call_id = request.tool_call.get("id", "")
        request_id = self._stable_message_id(tool_call_id, formatted_message)
        human_input_payload = self._build_human_input_payload(args, tool_call_id=tool_call_id, request_id=request_id)

        # Create a ToolMessage with the formatted question
        # This will be added to the message history
        tool_message = ToolMessage(
            id=request_id,
            content=formatted_message,
            tool_call_id=tool_call_id,
            name="ask_clarification",
            artifact={"human_input": human_input_payload},
        )

        # Return a Command that:
        # 1. Adds the formatted tool message
        # 2. Interrupts execution by going to __end__
        # Note: We don't add an extra AIMessage here - the frontend will detect
        # and display ask_clarification tool messages directly
        return Command(
            update={"messages": [tool_message]},
            goto=END,
        )

    def _stable_resolved_context_id(self, resolved: ResolvedClarification) -> str:
        digest = sha256(f"{resolved.question}\n{resolved.answer}".encode()).hexdigest()[:16]
        return f"resolved-clarification:{digest}"

    def _build_resolved_context_message(self, resolved: ResolvedClarification) -> HumanMessage:
        content = "\n".join(
            [
                "<resolved_clarification>",
                "The user has already answered a prior clarification request for the current task.",
                "",
                "Clarification question:",
                resolved.question,
                "",
                "User answer:",
                resolved.answer,
                "",
                "Treat this as resolved context. Do not ask the same clarification again unless the user provides conflicting new information.",
                "</resolved_clarification>",
            ]
        )
        return HumanMessage(
            content=content,
            id=self._stable_resolved_context_id(resolved),
            additional_kwargs={
                "hide_from_ui": True,
                _RESOLVED_CLARIFICATION_CONTEXT_KEY: True,
            },
        )

    @staticmethod
    def _insert_context_before_answer(
        messages: list[Any],
        context_message: HumanMessage,
        answer_message: HumanMessage,
    ) -> list[Any]:
        answer_id = getattr(answer_message, "id", None)
        for index, message in enumerate(messages):
            message_id = getattr(message, "id", None)
            if message is answer_message or (message_id and answer_id and message_id == answer_id):
                return [*messages[:index], context_message, *messages[index:]]
        return [context_message, *messages]

    def _prepare_model_request(self, request: ModelRequest) -> ModelRequest:
        messages = list(request.messages)
        if any(is_resolved_clarification_context_message(message) for message in messages):
            return request

        resolved = find_latest_resolved_clarification(messages)
        if resolved is None:
            return request

        context_message = self._build_resolved_context_message(resolved)
        return request.override(messages=self._insert_context_before_answer(messages, context_message, resolved.answer_message))

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._prepare_model_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._prepare_model_request(request))

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification tool calls and interrupt execution (sync version).

        Args:
            request: Tool call request
            handler: Original tool execution handler

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Check if this is an ask_clarification tool call
        if request.tool_call.get("name") != "ask_clarification":
            # Not a clarification call, execute normally
            return handler(request)

        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification tool calls and interrupt execution (async version).

        Args:
            request: Tool call request
            handler: Original tool execution handler (async)

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Check if this is an ask_clarification tool call
        if request.tool_call.get("name") != "ask_clarification":
            # Not a clarification call, execute normally
            return await handler(request)

        return self._handle_clarification(request)
