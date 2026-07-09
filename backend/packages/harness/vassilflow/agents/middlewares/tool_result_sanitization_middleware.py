"""Neutralize prompt-injection control tokens in untrusted remote tool results.

VassilFlow already treats genuine user messages as untrusted input and escapes
framework/injection tags before they enter model context. Remote content fetched
by network tools is another untrusted entry point, so first-party web tool
results get the same structural neutralization before the next model call.

Local tool output is intentionally left untouched: shell logs and file contents
often contain literal angle brackets that should remain exact.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace as dc_replace
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

# Built-in tools whose result payloads are attacker-influenceable remote
# content. The allowlist avoids mangling local tools that may legitimately
# print code, XML, logs, or prompts.
_REMOTE_CONTENT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "web_fetch",
        "web_search",
        "image_search",
    }
)


def _neutralize_content(content: object) -> object:
    """Return *content* with untrusted tags neutralized, preserving its shape."""
    from vassilflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags

    if isinstance(content, str):
        return neutralize_untrusted_tags(content)
    if isinstance(content, list):
        rebuilt: list[object] = []
        for block in content:
            if isinstance(block, str):
                rebuilt.append(neutralize_untrusted_tags(block))
            elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                rebuilt.append({**block, "text": neutralize_untrusted_tags(block["text"])})
            else:
                rebuilt.append(block)
        return rebuilt
    return content


def _sanitize_tool_message(message: ToolMessage) -> ToolMessage:
    """Return a copy of *message* with neutralized content, or the original."""
    new_content = _neutralize_content(message.content)
    if new_content == message.content:
        return message
    return message.model_copy(update={"content": new_content})


def _sanitize_result(result: ToolMessage | Command) -> ToolMessage | Command:
    """Neutralize a tool-call result while preserving ToolMessage/Command shape."""
    if isinstance(result, ToolMessage):
        return _sanitize_tool_message(result)

    update = getattr(result, "update", None)
    if isinstance(update, dict):
        messages = update.get("messages")
        if isinstance(messages, list) and any(isinstance(message, ToolMessage) for message in messages):
            new_messages = [_sanitize_tool_message(message) if isinstance(message, ToolMessage) else message for message in messages]
            if new_messages != messages:
                return dc_replace(result, update={**update, "messages": new_messages})
    return result


class ToolResultSanitizationMiddleware(AgentMiddleware[AgentState]):
    """Escape framework/injection tags in first-party remote tool results."""

    def _should_sanitize(self, request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") in _REMOTE_CONTENT_TOOL_NAMES

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        result = handler(request)
        if not self._should_sanitize(request):
            return result
        return _sanitize_result(result)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        result = await handler(request)
        if not self._should_sanitize(request):
            return result
        return _sanitize_result(result)
