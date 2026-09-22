"""Structured Gateway readiness reporting."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.brand import GATEWAY_SERVICE_NAME
from app.gateway.agent_catalog import build_builtin_agent_product
from app.gateway.capability_readiness import (
    get_agent_capability_readiness,
)
from app.gateway.domain_repair import (
    aggregate_repair_health,
    discover_repair_user_ids,
    inspect_user_repair_health,
)
from vassilflow.config.app_config import AppConfig
from vassilflow.config.builtin_agents import (
    BuiltinAgentDefinition,
    list_builtin_agents,
)
from vassilflow.config.database_config import DatabaseConfig
from vassilflow.persistence.engine import get_engine
from vassilflow.persistence.repository_registry import (
    build_domain_repository_registry,
)

logger = logging.getLogger(__name__)

_PROJECTION_HEALTH_USER_LIMIT = 10
_PROJECTION_HEALTH_TIMEOUT_SECONDS = 1.5


class GatewayReadinessCheck(BaseModel):
    """One sanitized service-level readiness check."""

    key: str
    status: Literal["ready", "degraded", "unavailable"]
    required: bool
    detail: str
    metadata: dict[str, str] = Field(default_factory=dict)


class GatewayAgentReadiness(BaseModel):
    """Readiness projection for one server-owned Agent."""

    id: str
    status: Literal["available", "degraded", "unavailable"]
    missing_requirements: list[str] = Field(default_factory=list)
    degraded_requirements: list[str] = Field(default_factory=list)
    checks: list[GatewayReadinessCheck] = Field(default_factory=list)


class GatewayReadinessReport(BaseModel):
    """Machine-readable readiness contract for operators and probes."""

    model_config = {"populate_by_name": True}

    schema_id: Literal["vassilflow.health.readiness.v1"] = Field(
        default="vassilflow.health.readiness.v1",
        alias="schema",
    )
    status: Literal["ready", "degraded", "not_ready"]
    service: str = GATEWAY_SERVICE_NAME
    checks: list[GatewayReadinessCheck] = Field(default_factory=list)
    agents: list[GatewayAgentReadiness] = Field(default_factory=list)


def configuration_failure_report() -> GatewayReadinessReport:
    """Return a structured failure without exposing config content."""

    return GatewayReadinessReport(
        status="not_ready",
        checks=[
            GatewayReadinessCheck(
                key="gateway.configuration",
                status="unavailable",
                required=True,
                detail="Gateway configuration is unavailable.",
            )
        ],
    )


def _runtime_check(request: Request) -> GatewayReadinessCheck:
    required_components = (
        "stream_bridge",
        "run_manager",
        "run_store",
        "thread_store",
        "checkpointer",
        "store",
        "database_config",
    )
    missing = [component for component in required_components if getattr(request.app.state, component, None) is None]
    if missing:
        return GatewayReadinessCheck(
            key="gateway.runtime",
            status="unavailable",
            required=True,
            detail="Gateway runtime components are not fully initialized.",
            metadata={"missing_components": ",".join(missing)},
        )
    return GatewayReadinessCheck(
        key="gateway.runtime",
        status="ready",
        required=True,
        detail="Gateway runtime components are ready.",
    )


async def _database_check(
    database_config: DatabaseConfig,
) -> GatewayReadinessCheck:
    backend = database_config.backend
    if backend == "memory":
        return GatewayReadinessCheck(
            key="gateway.persistence",
            status="ready",
            required=True,
            detail="In-memory application persistence is ready.",
            metadata={
                "backend": "memory",
                "durability": "ephemeral",
            },
        )

    engine = get_engine()
    if engine is None:
        return GatewayReadinessCheck(
            key="gateway.persistence",
            status="unavailable",
            required=True,
            detail="Application persistence is not initialized.",
            metadata={"backend": backend},
        )

    async def _ping() -> None:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping(), timeout=3.0)
    except Exception:
        logger.exception("Application persistence readiness probe failed")
        return GatewayReadinessCheck(
            key="gateway.persistence",
            status="unavailable",
            required=True,
            detail="Application persistence did not pass its readiness probe.",
            metadata={"backend": backend},
        )
    return GatewayReadinessCheck(
        key="gateway.persistence",
        status="ready",
        required=True,
        detail="Application persistence is ready.",
        metadata={
            "backend": backend,
            "durability": "durable",
        },
    )


async def _agent_check(
    definition: BuiltinAgentDefinition,
    config: AppConfig,
) -> GatewayAgentReadiness:
    capability_checks = await get_agent_capability_readiness(
        definition.capability_adapters,
        assistant_id=definition.name,
        agent_name=definition.name,
        user_id=None,
    )
    product = build_builtin_agent_product(
        definition,
        config,
        readiness=capability_checks,
    )
    return GatewayAgentReadiness(
        id=product.id,
        status=product.status,
        missing_requirements=product.missing_requirements,
        degraded_requirements=product.degraded_requirements,
        checks=[
            GatewayReadinessCheck(
                key=check.key,
                status=check.status,
                required=check.required,
                detail=check.detail,
                metadata=check.metadata,
            )
            for check in capability_checks
        ],
    )


async def _projection_repair_check() -> GatewayReadinessCheck:
    def inspect() -> dict[str, int | bool]:
        user_ids = discover_repair_user_ids()
        inspections = tuple(inspect_user_repair_health(user_id) for user_id in user_ids[:_PROJECTION_HEALTH_USER_LIMIT])
        summary = aggregate_repair_health(inspections)
        summary["user_scopes"] = len(user_ids)
        summary["limit_reached"] = bool(summary["limit_reached"] or len(user_ids) > _PROJECTION_HEALTH_USER_LIMIT)
        return summary

    try:
        summary = await asyncio.wait_for(
            asyncio.to_thread(inspect),
            timeout=_PROJECTION_HEALTH_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("Projection repair readiness discovery failed")
        return GatewayReadinessCheck(
            key="gateway.projection_repair",
            status="unavailable",
            required=False,
            detail="Durable projection repair state could not be checked.",
        )
    unresolved = int(summary["lifecycle_pending"]) + int(summary["stale_actions"])
    limited = bool(summary["limit_reached"])
    return GatewayReadinessCheck(
        key="gateway.projection_repair",
        status="degraded" if unresolved or limited else "ready",
        required=False,
        detail=("Durable projection repair has unresolved work." if unresolved or limited else "Durable projection repair state is current."),
        metadata={
            "user_scopes": str(summary["user_scopes"]),
            "lifecycle_pending": str(summary["lifecycle_pending"]),
            "stale_actions": str(summary["stale_actions"]),
            "active_actions": str(summary["active_actions"]),
            "limit_reached": str(limited).lower(),
        },
    )


async def build_gateway_readiness(
    request: Request,
    config: AppConfig,
) -> GatewayReadinessReport:
    """Build readiness from live core and capability evidence."""

    database_config = getattr(
        request.app.state,
        "database_config",
        config.database,
    )
    checks = [
        _runtime_check(request),
        await _database_check(database_config),
        await _projection_repair_check(),
    ]
    try:
        repository_checks = await asyncio.to_thread(build_domain_repository_registry(user_id=None).readiness)
    except Exception:
        logger.exception("Domain repository readiness discovery failed")
        checks.append(
            GatewayReadinessCheck(
                key="gateway.domain_repositories",
                status="unavailable",
                required=False,
                detail="Domain repositories could not be checked.",
            )
        )
    else:
        checks.extend(
            GatewayReadinessCheck(
                key=f"repository.{check.repository_key}",
                status=check.status,
                required=False,
                detail=check.detail,
            )
            for check in repository_checks
        )
    agents = list(await asyncio.gather(*(_agent_check(definition, config) for definition in list_builtin_agents())))

    if any(check.required and check.status == "unavailable" for check in checks):
        status = "not_ready"
    elif any(check.status != "ready" for check in checks) or any(agent.status != "available" for agent in agents):
        status = "degraded"
    else:
        status = "ready"
    return GatewayReadinessReport(
        status=status,
        checks=checks,
        agents=agents,
    )


__all__ = [
    "GatewayAgentReadiness",
    "GatewayReadinessCheck",
    "GatewayReadinessReport",
    "build_gateway_readiness",
    "configuration_failure_report",
]
