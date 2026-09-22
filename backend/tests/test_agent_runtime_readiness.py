from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.gateway import agent_runtime_readiness
from vassilflow.capabilities import CapabilityReadinessCheck
from vassilflow.config.agent_contract import resolve_agent_identity
from vassilflow.config.app_config import AppConfig
from vassilflow.config.sandbox_config import SandboxConfig
from vassilflow.config.tool_config import ToolConfig


def _sample_config() -> AppConfig:
    providers = {
        "sample_inspect": "sample_agent_fixture:sample_inspect_tool",
        "sample_generate": "sample_agent_fixture:sample_generate_tool",
        "sample_edit": "sample_agent_fixture:sample_edit_tool",
        "sample_render": "sample_agent_fixture:sample_render_tool",
    }
    return AppConfig(
        sandbox=SandboxConfig(use="test"),
        tools=[
            ToolConfig(
                name=name,
                group=("file:read" if name == "sample_inspect" else "file:write"),
                use=provider,
            )
            for name, provider in providers.items()
        ],
    )


@pytest.mark.anyio
async def test_required_capability_unavailable_blocks_builtin_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def checks(*_args, **_kwargs):
        return (
            CapabilityReadinessCheck(
                key="sample.projects",
                status="unavailable",
                required=True,
                detail="secret storage path",
            ),
        )

    monkeypatch.setattr(
        agent_runtime_readiness,
        "get_agent_capability_readiness",
        checks,
    )

    with pytest.raises(HTTPException) as exc_info:
        await agent_runtime_readiness.enforce_agent_runtime_readiness(
            resolve_agent_identity("sample"),
            _sample_config(),
            user_id="alice",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "code": "agent_unavailable",
        "message": "The selected Agent is currently unavailable.",
        "agent_id": "builtin:sample",
        "requirements": ["sample.projects"],
    }
    assert "secret" not in str(exc_info.value.detail)


@pytest.mark.anyio
async def test_optional_capability_unavailable_keeps_builtin_launchable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def checks(*_args, **_kwargs):
        return (
            CapabilityReadinessCheck(
                key="sample.renderer",
                status="unavailable",
                required=False,
                detail="Sample preview rendering is unavailable.",
            ),
        )

    monkeypatch.setattr(
        agent_runtime_readiness,
        "get_agent_capability_readiness",
        checks,
    )

    await agent_runtime_readiness.enforce_agent_runtime_readiness(
        resolve_agent_identity("sample"),
        _sample_config(),
        user_id="alice",
    )


@pytest.mark.anyio
async def test_static_tool_requirement_also_blocks_builtin_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def checks(*_args, **_kwargs):
        return ()

    monkeypatch.setattr(
        agent_runtime_readiness,
        "get_agent_capability_readiness",
        checks,
    )

    with pytest.raises(HTTPException) as exc_info:
        await agent_runtime_readiness.enforce_agent_runtime_readiness(
            resolve_agent_identity("sample"),
            AppConfig(sandbox=SandboxConfig(use="test")),
            user_id="alice",
        )

    assert exc_info.value.status_code == 503
    assert set(exc_info.value.detail["requirements"]) == {
        "sample_edit",
        "sample_generate",
        "sample_inspect",
        "sample_render",
    }


pytestmark = pytest.mark.usefixtures("sample_builtin_registry")
