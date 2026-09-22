from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from vassilflow.agents.agent_policy import (
    filter_tools_by_agent_policy,
    resolve_agent_runtime_policy,
)
from vassilflow.agents.middlewares.agent_policy_middleware import (
    AgentPolicyMiddleware,
    referenced_data_scopes,
)
from vassilflow.config.agent_contract import (
    AGENT_DATA_ACCESS_SCOPES,
    AgentRuntimePolicy,
    deserialize_agent_runtime_policy,
    resolve_agent_identity,
)
from vassilflow.config.agents_config import AgentConfig


def _request(name: str, args: dict) -> ToolCallRequest:
    runtime = MagicMock()
    runtime.context = {"thread_id": "thread-policy"}
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": "call-1"},
        tool=SimpleNamespace(name=name, metadata={}),
        state={"messages": []},
        runtime=runtime,
    )


def test_agent_identity_normalizes_once() -> None:
    assert resolve_agent_identity(None).assistant_id == "lead_agent"
    assert resolve_agent_identity(" lead_agent ").agent_name is None
    assert resolve_agent_identity("Report_AGENT").assistant_id == "report-agent"


def test_default_agent_aliases_are_reserved() -> None:
    from vassilflow.config.agent_contract import is_default_agent_alias

    assert is_default_agent_alias("lead_agent") is True
    assert is_default_agent_alias(" Lead-Agent ") is True
    assert is_default_agent_alias("lead") is False


def test_agent_identity_rejects_invalid_names() -> None:
    with pytest.raises(ValueError, match="Invalid assistant_id"):
        resolve_agent_identity("../../sample")


def test_unknown_runtime_policy_version_fails_closed() -> None:
    policy = deserialize_agent_runtime_policy(
        {
            "agent_policy_version": 999,
            "allowed_tools": ["read_file"],
            "agent_data_access": list(AGENT_DATA_ACCESS_SCOPES),
            "agent_allow_mcp_tools": True,
            "agent_allow_acp_agents": True,
        }
    )

    assert policy == AgentRuntimePolicy(
        allowed_tool_names=frozenset(),
        data_access=frozenset(),
    )


def test_custom_tool_groups_filter_complete_assembly() -> None:
    app_config = SimpleNamespace(
        tools=[
            SimpleNamespace(name="read_file", group="file:read"),
            SimpleNamespace(name="web_search", group="web"),
        ]
    )
    policy = resolve_agent_runtime_policy(
        agent_config=AgentConfig(name="reader", tool_groups=["file:read"]),
        builtin_agent=None,
        app_config=app_config,
    )
    tools = [
        SimpleNamespace(name="read_file"),
        SimpleNamespace(name="web_search"),
        SimpleNamespace(name="mcp_private"),
        SimpleNamespace(name="ask_clarification"),
        SimpleNamespace(name="tool_search"),
    ]

    assert policy is not None
    assert [tool.name for tool in filter_tools_by_agent_policy(tools, policy)] == [
        "read_file",
        "ask_clarification",
        "tool_search",
    ]


def test_restricted_policy_rejects_mcp_name_collision_and_acp() -> None:
    from vassilflow.tools.mcp_metadata import tag_mcp_tool

    local = SimpleNamespace(name="read_file", metadata={})
    mcp_collision = tag_mcp_tool(SimpleNamespace(name="read_file", metadata={}))
    acp = SimpleNamespace(name="invoke_acp_agent", metadata={})
    policy = AgentRuntimePolicy(allowed_tool_names=frozenset({"read_file", "invoke_acp_agent"}))

    assert filter_tools_by_agent_policy([local, mcp_collision, acp], policy) == [local]


def test_data_scope_extraction_uses_path_arguments_only() -> None:
    assert referenced_data_scopes(
        {
            "source_path": "/mnt/user-data/uploads/input.pptx",
            "output_path": "/mnt/user-data/outputs/result.pptx",
            "content": "Mention /mnt/user-data/workspace without accessing it",
        }
    ) == frozenset({"thread_uploads", "thread_outputs"})


def test_data_scope_extraction_normalizes_traversal_before_authorizing() -> None:
    assert referenced_data_scopes({"path": "/mnt/user-data/workspace/../uploads/private.txt"}) == frozenset({"thread_uploads"})
    assert referenced_data_scopes({"path": "/mnt/user-data/workspace/../../outside.txt"}) == frozenset({"thread_uploads", "thread_workspace", "thread_outputs"})


def test_data_scope_extraction_resolves_relative_paths_and_commands() -> None:
    assert referenced_data_scopes({"path": "draft.txt"}) == frozenset({"thread_workspace"})
    assert referenced_data_scopes({"command": "cat ../uploads/source.txt > ../outputs/result.txt"}) == frozenset({"thread_uploads", "thread_workspace", "thread_outputs"})
    assert referenced_data_scopes({"path": "../../outside.txt"}) == frozenset({"thread_uploads", "thread_workspace", "thread_outputs"})
    assert referenced_data_scopes({"command": "pwd"}) == frozenset(AGENT_DATA_ACCESS_SCOPES)


def test_data_scope_extraction_handles_directories_and_opaque_revisions() -> None:
    assert referenced_data_scopes(
        {
            "output_dir": "/mnt/user-data/outputs/rendered",
            "pattern": "*.png",
        }
    ) == frozenset({"thread_outputs"})
    assert referenced_data_scopes({"project_id": "project-1", "revision_id": "revision-2"}) == frozenset(AGENT_DATA_ACCESS_SCOPES)


def test_policy_middleware_blocks_tool_and_data_scope() -> None:
    middleware = AgentPolicyMiddleware(
        AgentRuntimePolicy(
            allowed_tool_names=frozenset({"read_file"}),
            data_access=frozenset({"thread_uploads"}),
        )
    )

    blocked_tool = middleware.wrap_tool_call(
        _request("web_search", {"query": "x"}),
        MagicMock(),
    )
    blocked_data = middleware.wrap_tool_call(
        _request("read_file", {"path": "/mnt/user-data/outputs/private.txt"}),
        MagicMock(),
    )
    allowed_handler = MagicMock(
        return_value=ToolMessage(
            content="ok",
            tool_call_id="call-1",
            name="read_file",
        )
    )
    allowed = middleware.wrap_tool_call(
        _request("read_file", {"path": "/mnt/user-data/uploads/input.txt"}),
        allowed_handler,
    )

    assert blocked_tool.status == "error"
    assert blocked_data.status == "error"
    assert allowed.content == "ok"
    allowed_handler.assert_called_once()


def test_policy_middleware_async_block_is_fail_closed() -> None:
    middleware = AgentPolicyMiddleware(AgentRuntimePolicy(allowed_tool_names=frozenset(), data_access=frozenset()))

    async def handler(_request):
        raise AssertionError("blocked tool must not execute")

    result = asyncio.run(
        middleware.awrap_tool_call(
            _request("read_file", {"path": "/mnt/user-data/uploads/a"}),
            handler,
        )
    )
    assert result.status == "error"


def test_policy_middleware_rejects_non_object_arguments() -> None:
    middleware = AgentPolicyMiddleware(
        AgentRuntimePolicy(
            allowed_tool_names=frozenset({"read_file"}),
            data_access=frozenset({"thread_uploads"}),
        )
    )
    request = _request("read_file", {})
    request.tool_call["args"] = "not-an-object"

    result = middleware.wrap_tool_call(request, MagicMock())

    assert result.status == "error"
    assert "must be an object" in str(result.content)


def test_mcp_boundary_rechecks_provenance_and_stdio_data_policy() -> None:
    from langchain_core.tools import ToolException

    from vassilflow.config.agent_contract import serialize_agent_runtime_policy
    from vassilflow.mcp.tools import _enforce_mcp_agent_policy

    denied_runtime = SimpleNamespace(
        context={"agent_policy": serialize_agent_runtime_policy(AgentRuntimePolicy(allowed_tool_names=frozenset({"srv_read"})))},
        config={},
    )
    with pytest.raises(ToolException, match="MCP tools"):
        _enforce_mcp_agent_policy(
            denied_runtime,
            {},
            tool_name="srv_read",
            is_stdio=False,
        )

    restricted_stdio_runtime = SimpleNamespace(
        context={
            "agent_policy": serialize_agent_runtime_policy(
                AgentRuntimePolicy(
                    allowed_tool_names=frozenset({"srv_read"}),
                    data_access=frozenset({"thread_workspace"}),
                    allow_mcp_tools=True,
                )
            )
        },
        config={},
    )
    with pytest.raises(ToolException, match="local MCP process"):
        _enforce_mcp_agent_policy(
            restricted_stdio_runtime,
            {"path": "draft.txt"},
            tool_name="srv_read",
            is_stdio=True,
        )

    wrong_name_runtime = SimpleNamespace(
        context={
            "agent_policy": serialize_agent_runtime_policy(
                AgentRuntimePolicy(
                    allowed_tool_names=frozenset({"srv_read"}),
                    data_access=frozenset(AGENT_DATA_ACCESS_SCOPES),
                    allow_mcp_tools=True,
                )
            )
        },
        config={},
    )
    with pytest.raises(ToolException, match="srv_write"):
        _enforce_mcp_agent_policy(
            wrong_name_runtime,
            {},
            tool_name="srv_write",
            is_stdio=False,
        )
