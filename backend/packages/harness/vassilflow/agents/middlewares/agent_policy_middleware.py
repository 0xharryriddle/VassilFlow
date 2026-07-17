"""Defense-in-depth enforcement for Agent tool and thread-data policy."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from vassilflow.agents.agent_policy import is_tool_allowed_by_agent_policy
from vassilflow.agents.data_policy import referenced_data_scopes
from vassilflow.config.agent_contract import AgentRuntimePolicy


class AgentPolicyMiddleware(AgentMiddleware[AgentState]):
    """Hide and block capabilities outside the canonical Agent contract."""

    def __init__(self, policy: AgentRuntimePolicy):
        super().__init__()
        self._policy = policy

    def _filter_model_tools(self, request: ModelRequest) -> ModelRequest:
        return request.override(tools=[tool for tool in request.tools if is_tool_allowed_by_agent_policy(tool, self._policy)])

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage | None:
        name = str(request.tool_call.get("name") or "")
        tool_call_id = str(request.tool_call.get("id") or "missing_tool_call_id")
        tool = request.tool
        if tool is None or getattr(tool, "name", None) != name or not is_tool_allowed_by_agent_policy(tool, self._policy):
            return ToolMessage(
                content=f"Error: Tool '{name}' is not permitted by this Agent's runtime policy.",
                tool_call_id=tool_call_id,
                name=name or None,
                status="error",
            )

        allowed_data = self._policy.data_access
        args = request.tool_call.get("args")
        if allowed_data is not None and not isinstance(args, Mapping):
            return ToolMessage(
                content="Error: Tool arguments must be an object under this Agent's data policy.",
                tool_call_id=tool_call_id,
                name=name or None,
                status="error",
            )
        if allowed_data is not None:
            denied = referenced_data_scopes(args) - allowed_data
            if denied:
                scopes = ", ".join(sorted(denied))
                return ToolMessage(
                    content=f"Error: This Agent is not permitted to access: {scopes}.",
                    tool_call_id=tool_call_id,
                    name=name or None,
                    status="error",
                )
        return None

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._filter_model_tools(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._filter_model_tools(request))

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        return self._blocked_tool_message(request) or handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        blocked = self._blocked_tool_message(request)
        if blocked is not None:
            return blocked
        return await handler(request)
