"""Tests for VassilFlow MCP routing metadata."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from vassilflow.config.extensions_config import ExtensionsConfig
from vassilflow.tools.mcp_metadata import (
    MCP_TOOL_METADATA_KEY,
    MCP_TOOL_ROUTING_METADATA_KEY,
    get_mcp_routing,
    tag_mcp_routing,
    tag_mcp_tool,
)


class _Args(BaseModel):
    query: str = Field(..., description="query")


def _tool(name: str = "warehouse_query") -> StructuredTool:
    async def _call(query: str) -> str:
        return query

    return StructuredTool(
        name=name,
        description="Query internal data",
        args_schema=_Args,
        coroutine=_call,
    )


def test_routing_tag_preserves_mcp_source_tag():
    tagged = tag_mcp_routing(
        tag_mcp_tool(_tool()),
        {"mode": "prefer", "priority": 80, "keywords": ["orders"]},
    )

    assert tagged.metadata[MCP_TOOL_METADATA_KEY] is True
    assert tagged.metadata[MCP_TOOL_ROUTING_METADATA_KEY]["priority"] == 80
    assert get_mcp_routing(tagged)["keywords"] == ["orders"]


def test_routing_is_ignored_for_non_mcp_or_off_tools():
    non_mcp = tag_mcp_routing(
        _tool(),
        {"mode": "prefer", "priority": 80, "keywords": ["orders"]},
    )
    off = tag_mcp_routing(
        tag_mcp_tool(_tool()),
        {"mode": "off", "priority": 80, "keywords": ["orders"]},
    )

    assert get_mcp_routing(non_mcp) is None
    assert get_mcp_routing(off) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "stdio"])
async def test_loaded_tools_receive_effective_routing_metadata(transport: str):
    from vassilflow.mcp.tools import get_mcp_tools

    tool = _tool()
    extensions_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "warehouse": {
                    "type": transport,
                    "url": "http://localhost:8000/mcp",
                    "command": "npx",
                    "routing": {
                        "mode": "prefer",
                        "priority": 50,
                        "keywords": ["database"],
                    },
                    "tools": {
                        "query": {
                            "routing": {
                                "priority": 100,
                                "keywords": ["internal metrics"],
                            }
                        }
                    },
                }
            }
        }
    )

    with (
        patch("vassilflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch(
            "vassilflow.mcp.tools.build_servers_config",
            return_value={
                "warehouse": {
                    "transport": transport,
                    "url": "http://localhost:8000/mcp",
                    "command": "npx",
                }
            },
        ),
        patch("vassilflow.mcp.tools.get_initial_oauth_headers", new=AsyncMock(return_value={})),
        patch("vassilflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as mock_client,
    ):
        mock_client.return_value.get_tools = AsyncMock(return_value=[tool])
        tools = await get_mcp_tools()

    routing = get_mcp_routing(tools[0])
    assert routing is not None
    assert routing["priority"] == 100
    assert routing["keywords"] == ["internal metrics"]
