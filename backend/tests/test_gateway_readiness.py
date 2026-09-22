from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.gateway import readiness
from vassilflow.capabilities import CapabilityReadinessCheck
from vassilflow.config.app_config import AppConfig
from vassilflow.config.builtin_agents import list_builtin_agents
from vassilflow.config.database_config import DatabaseConfig
from vassilflow.config.sandbox_config import SandboxConfig
from vassilflow.config.tool_config import ToolConfig
from vassilflow.persistence.project_repository import (
    ProjectRepositoryReadiness,
)


def _sample_config() -> AppConfig:
    providers = {
        "sample_inspect": ("sample_agent_fixture:sample_inspect_tool"),
        "sample_generate": ("sample_agent_fixture:sample_generate_tool"),
        "sample_edit": ("sample_agent_fixture:sample_edit_tool"),
        "sample_render": ("sample_agent_fixture:sample_render_tool"),
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


def _request(*, complete_runtime: bool) -> Request:
    state = SimpleNamespace()
    if complete_runtime:
        for component in (
            "stream_bridge",
            "run_manager",
            "run_store",
            "thread_store",
            "checkpointer",
            "store",
        ):
            setattr(state, component, object())
        state.database_config = DatabaseConfig(backend="memory")
    app = SimpleNamespace(state=state)
    return Request({"type": "http", "app": app})


def _empty_repository_registry(
    *,
    user_id: str | None,
) -> SimpleNamespace:
    assert user_id is None
    return SimpleNamespace(readiness=lambda: ())


@pytest.mark.anyio
async def test_gateway_readiness_projects_optional_renderer_failure_as_degraded(
    monkeypatch,
) -> None:
    async def capability_checks(
        adapter_paths,
        *,
        assistant_id,
        agent_name,
        user_id,
    ):
        assert adapter_paths
        assert assistant_id == agent_name == "sample"
        assert user_id is None
        return (
            CapabilityReadinessCheck(
                key="sample.renderer",
                status="unavailable",
                required=False,
                detail="Sample preview rendering is unavailable.",
            ),
            CapabilityReadinessCheck(
                key="sample.projects",
                status="ready",
                required=True,
                detail="Sample Projects storage is ready.",
            ),
        )

    monkeypatch.setattr(
        readiness,
        "get_agent_capability_readiness",
        capability_checks,
    )
    monkeypatch.setattr(
        readiness,
        "build_domain_repository_registry",
        _empty_repository_registry,
    )

    report = await readiness.build_gateway_readiness(
        _request(complete_runtime=True),
        _sample_config(),
    )

    assert report.status == "degraded"
    assert report.checks[0].status == "ready"
    assert report.checks[1].metadata == {
        "backend": "memory",
        "durability": "ephemeral",
    }
    assert report.agents[0].status == "degraded"
    assert report.agents[0].degraded_requirements == ["sample.renderer"]


@pytest.mark.anyio
async def test_gateway_readiness_fails_when_core_runtime_is_incomplete(
    monkeypatch,
) -> None:
    async def capability_checks(
        adapter_paths,
        *,
        assistant_id,
        agent_name,
        user_id,
    ):
        assert adapter_paths
        assert assistant_id == agent_name == "sample"
        assert user_id is None
        return ()

    monkeypatch.setattr(
        readiness,
        "get_agent_capability_readiness",
        capability_checks,
    )
    monkeypatch.setattr(
        readiness,
        "build_domain_repository_registry",
        _empty_repository_registry,
    )

    report = await readiness.build_gateway_readiness(
        _request(complete_runtime=False),
        _sample_config(),
    )

    assert report.status == "not_ready"
    runtime_check = report.checks[0]
    assert runtime_check.required is True
    assert runtime_check.status == "unavailable"
    assert "stream_bridge" in runtime_check.metadata["missing_components"]


@pytest.mark.anyio
async def test_gateway_readiness_uses_startup_database_config(
    monkeypatch,
    tmp_path,
) -> None:
    async def capability_checks(
        adapter_paths,
        *,
        assistant_id,
        agent_name,
        user_id,
    ):
        assert adapter_paths
        assert assistant_id == agent_name == "sample"
        assert user_id is None
        return ()

    monkeypatch.setattr(
        readiness,
        "get_agent_capability_readiness",
        capability_checks,
    )
    monkeypatch.setattr(
        readiness,
        "build_domain_repository_registry",
        _empty_repository_registry,
    )
    request = _request(complete_runtime=True)
    request.app.state.database_config = DatabaseConfig(backend="memory")
    config = _sample_config()
    config.database = DatabaseConfig(
        backend="sqlite",
        sqlite_dir=str(tmp_path),
    )

    report = await readiness.build_gateway_readiness(request, config)

    assert report.checks[1].metadata["backend"] == "memory"
    assert report.checks[1].status == "ready"


@pytest.mark.anyio
async def test_domain_repository_failure_degrades_but_does_not_fail_gateway(
    monkeypatch,
) -> None:
    async def capability_checks(
        adapter_paths,
        *,
        assistant_id,
        agent_name,
        user_id,
    ):
        assert adapter_paths
        assert assistant_id == agent_name == "sample"
        assert user_id is None
        return ()

    def unavailable_registry(*, user_id):
        assert user_id is None
        return SimpleNamespace(
            readiness=lambda: (
                ProjectRepositoryReadiness(
                    repository_key="sample.projects",
                    status="unavailable",
                    detail="Sample Projects storage is unavailable.",
                ),
            )
        )

    monkeypatch.setattr(
        readiness,
        "get_agent_capability_readiness",
        capability_checks,
    )
    monkeypatch.setattr(
        readiness,
        "build_domain_repository_registry",
        unavailable_registry,
    )

    report = await readiness.build_gateway_readiness(
        _request(complete_runtime=True),
        _sample_config(),
    )

    assert report.status == "degraded"
    repository_check = next(check for check in report.checks if check.key == "repository.sample.projects")
    assert repository_check.required is False
    assert repository_check.status == "unavailable"


def test_configuration_failure_report_is_sanitized() -> None:
    report = readiness.configuration_failure_report()

    assert report.status == "not_ready"
    assert report.model_dump(mode="json", by_alias=True) == {
        "schema": "vassilflow.health.readiness.v1",
        "status": "not_ready",
        "service": report.service,
        "checks": [
            {
                "key": "gateway.configuration",
                "status": "unavailable",
                "required": True,
                "detail": "Gateway configuration is unavailable.",
                "metadata": {},
            }
        ],
        "agents": [],
    }


@pytest.mark.anyio
async def test_gateway_readiness_checks_builtin_agents_concurrently(
    monkeypatch,
) -> None:
    definitions = list_builtin_agents()
    assert len(definitions) == 1
    sample = definitions[0]
    secondary = replace(
        sample,
        name="sample-secondary",
        display_name="Sample Secondary",
    )
    active = 0
    peak = 0
    both_started = asyncio.Event()

    async def capability_checks(
        adapter_paths,
        *,
        assistant_id,
        agent_name,
        user_id,
    ):
        nonlocal active, peak
        assert adapter_paths
        assert assistant_id == agent_name
        assert user_id is None
        active += 1
        peak = max(peak, active)
        if active == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        active -= 1
        return ()

    monkeypatch.setattr(
        readiness,
        "list_builtin_agents",
        lambda: (sample, secondary),
    )
    monkeypatch.setattr(
        readiness,
        "get_agent_capability_readiness",
        capability_checks,
    )
    monkeypatch.setattr(
        readiness,
        "build_domain_repository_registry",
        _empty_repository_registry,
    )

    report = await readiness.build_gateway_readiness(
        _request(complete_runtime=True),
        _sample_config(),
    )

    assert peak == 2
    assert [agent.id for agent in report.agents] == [
        "builtin:sample",
        "builtin:sample-secondary",
    ]


pytestmark = pytest.mark.usefixtures("sample_builtin_registry")
