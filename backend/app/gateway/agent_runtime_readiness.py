"""Fail-closed readiness enforcement at the Gateway run boundary."""

from __future__ import annotations

from fastapi import HTTPException

from app.gateway.agent_catalog import build_builtin_agent_product
from app.gateway.capability_readiness import (
    get_agent_capability_readiness,
)
from vassilflow.config.agent_contract import CanonicalAgentIdentity
from vassilflow.config.app_config import AppConfig
from vassilflow.config.builtin_agents import get_builtin_agent


async def enforce_agent_runtime_readiness(
    identity: CanonicalAgentIdentity,
    config: AppConfig,
    *,
    user_id: str,
) -> None:
    """Reject a built-in Agent run when a required capability is unavailable."""

    definition = get_builtin_agent(identity.agent_name)
    if definition is None:
        return

    readiness = await get_agent_capability_readiness(
        definition.capability_adapters,
        assistant_id=definition.name,
        agent_name=definition.name,
        user_id=user_id,
    )
    product = build_builtin_agent_product(
        definition,
        config,
        readiness=readiness,
    )
    if product.status != "unavailable":
        return

    raise HTTPException(
        status_code=503,
        detail={
            "code": "agent_unavailable",
            "message": "The selected Agent is currently unavailable.",
            "agent_id": product.id,
            "requirements": product.missing_requirements,
        },
    )


__all__ = ["enforce_agent_runtime_readiness"]
