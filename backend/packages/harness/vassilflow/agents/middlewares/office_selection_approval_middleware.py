"""Require one-time human review before a selected-object Office edit."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from hashlib import sha256
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from vassilflow.agents.human_input import read_human_input_response
from vassilflow.community.office.selection import PPTX_SELECTION_SCHEMA

_APPROVAL_SOURCE = "office_selection_approval"
_APPROVE_OPTION_ID = "approve"
_CANCEL_OPTION_ID = "cancel"
_MAX_REVIEW_JSON_CHARS = 12_000
_SELECTION_IDENTITY_FIELDS = (
    "project_id",
    "revision_id",
    "source_sha256",
    "slide_index",
    "object_path",
    "object_fingerprint",
)


def _error_message(request: ToolCallRequest, content: str) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=str(request.tool_call.get("id", "missing-id")),
        name="office_edit",
        status="error",
    )


def _runtime_selection(request: ToolCallRequest) -> Mapping[str, Any] | None:
    runtime = getattr(request, "runtime", None)
    context = getattr(runtime, "context", None)
    selection = context.get("office_selection") if isinstance(context, Mapping) else None
    if selection is None:
        return None
    if not isinstance(selection, Mapping) or selection.get("schema") != PPTX_SELECTION_SCHEMA:
        raise ValueError("Verified Office selection context is invalid")
    if any(field not in selection for field in _SELECTION_IDENTITY_FIELDS):
        raise ValueError("Verified Office selection context is incomplete")
    return selection


def _canonical_proposal(
    selection: Mapping[str, Any],
    args: Mapping[str, Any],
) -> tuple[str, str]:
    identity = {field: selection[field] for field in _SELECTION_IDENTITY_FIELDS}
    payload = {"selection": identity, "tool_args": dict(args)}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    proposal_id = sha256(canonical.encode("utf-8")).hexdigest()
    review = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if len(review) > _MAX_REVIEW_JSON_CHARS:
        raise ValueError("Selected-object Office edit is too large for complete review; split it into smaller transactions")
    return proposal_id, review


def _markdown_code_block(value: str) -> str:
    fence = "```"
    while fence in value:
        fence += "`"
    return f"{fence}json\n{value}\n{fence}"


def _request_id(proposal_id: str) -> str:
    return f"office-selection-approval:{proposal_id}"


def _human_input_payload(
    request: ToolCallRequest,
    *,
    proposal_id: str,
    review: str,
) -> dict[str, Any]:
    return {
        "version": 1,
        "kind": "human_input_request",
        "source": _APPROVAL_SOURCE,
        "request_id": _request_id(proposal_id),
        "tool_call_id": str(request.tool_call.get("id", "")),
        "clarification_type": "office_edit_approval",
        "title": "Review Office edit",
        "question": "Apply these operations to the selected PowerPoint object?",
        "context": _markdown_code_block(review),
        "input_mode": "single_choice",
        "options": [
            {
                "id": _APPROVE_OPTION_ID,
                "label": "Approve and apply",
                "value": "approve",
            },
            {
                "id": _CANCEL_OPTION_ID,
                "label": "Cancel",
                "value": "cancel",
            },
        ],
        "proposal_sha256": proposal_id,
    }


def _approval_command(
    request: ToolCallRequest,
    *,
    proposal_id: str,
    review: str,
) -> Command:
    payload = _human_input_payload(
        request,
        proposal_id=proposal_id,
        review=review,
    )
    message = ToolMessage(
        id=payload["request_id"],
        content="Review the exact selected-object Office edit before it is applied.",
        tool_call_id=str(request.tool_call.get("id", "missing-id")),
        name="office_edit",
        artifact={
            "human_input": payload,
            "office_selection_approval": {
                "proposal_sha256": proposal_id,
            },
        },
    )
    return Command(update={"messages": [message]}, goto=END)


def _state_messages(request: ToolCallRequest) -> Sequence[Any]:
    runtime = getattr(request, "runtime", None)
    state = getattr(runtime, "state", None)
    messages = state.get("messages") if isinstance(state, Mapping) else None
    return messages if isinstance(messages, Sequence) else ()


def _matching_decision(
    messages: Sequence[Any],
    *,
    request_id: str,
) -> str | None:
    response_index: int | None = None
    response: Mapping[str, Any] | None = None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, HumanMessage) or message.name == "summary":
            continue
        candidate = read_human_input_response(message.additional_kwargs)
        if candidate is None and message.additional_kwargs.get("hide_from_ui"):
            continue
        response_index = index
        response = candidate
        break
    if response_index is None or response is None:
        return None
    if response.get("source") != _APPROVAL_SOURCE or response.get("request_id") != request_id or response.get("response_kind") != "option":
        return None

    request_was_emitted = any(
        isinstance(message, ToolMessage)
        and isinstance(message.artifact, Mapping)
        and isinstance(message.artifact.get("human_input"), Mapping)
        and message.artifact["human_input"].get("source") == _APPROVAL_SOURCE
        and message.artifact["human_input"].get("request_id") == request_id
        for message in messages[:response_index]
    )
    if not request_was_emitted:
        return None
    option_id = response.get("option_id")
    value = response.get("value")
    if option_id not in {_APPROVE_OPTION_ID, _CANCEL_OPTION_ID} or value != option_id:
        return None
    return option_id


class OfficeSelectionApprovalMiddleware(AgentMiddleware[AgentState]):
    """Pause exact selected-object edits until the user approves that proposal."""

    @staticmethod
    def _prepare(request: ToolCallRequest) -> tuple[str, str] | ToolMessage | None:
        if request.tool_call.get("name") != "office_edit":
            return None
        try:
            selection = _runtime_selection(request)
            if selection is None:
                return None
            args = request.tool_call.get("args")
            if not isinstance(args, Mapping):
                return _error_message(request, "Selected-object Office edit arguments are invalid")
            return _canonical_proposal(selection, args)
        except (TypeError, ValueError) as exc:
            return _error_message(request, str(exc))

    @staticmethod
    def _decision_result(
        request: ToolCallRequest,
        *,
        proposal_id: str,
        review: str,
    ) -> Command | ToolMessage | None:
        decision = _matching_decision(
            _state_messages(request),
            request_id=_request_id(proposal_id),
        )
        if decision == _APPROVE_OPTION_ID:
            return None
        if decision == _CANCEL_OPTION_ID:
            return _error_message(request, "Selected-object Office edit was cancelled by the user")
        return _approval_command(
            request,
            proposal_id=proposal_id,
            review=review,
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        prepared = self._prepare(request)
        if prepared is None:
            return handler(request)
        if isinstance(prepared, ToolMessage):
            return prepared
        result = self._decision_result(
            request,
            proposal_id=prepared[0],
            review=prepared[1],
        )
        return handler(request) if result is None else result

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        prepared = self._prepare(request)
        if prepared is None:
            return await handler(request)
        if isinstance(prepared, ToolMessage):
            return prepared
        result = self._decision_result(
            request,
            proposal_id=prepared[0],
            review=prepared[1],
        )
        return await handler(request) if result is None else result
