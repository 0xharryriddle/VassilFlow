"""Generic optimistic-to-trusted capability input boundary for runs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vassilflow.capabilities import (
    CAPABILITY_INPUT_SCHEMA,
    CAPABILITY_INPUTS_CONTEXT_KEY,
    MAX_CAPABILITY_INPUTS,
    CapabilityInputConflictError,
    CapabilityInputIntegrityError,
    CapabilityInputInvalidError,
    CapabilityInputNotFoundError,
    CapabilityInputUnavailableError,
    CapabilityInputUnsupportedError,
    CapabilityResolutionContext,
    load_capability_adapters,
)
from vassilflow.config.agent_contract import CanonicalAgentIdentity
from vassilflow.config.builtin_agents import get_builtin_agent

logger = logging.getLogger(__name__)


class CapabilityInputEnvelope(BaseModel):
    """Versioned client envelope dispatched by capability and input kind."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["vassilflow.capability_input.v1"] = Field(
        default=CAPABILITY_INPUT_SCHEMA,
        alias="schema",
    )
    capability: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    payload: dict[str, Any]


def _parse_capability_inputs(value: Any) -> tuple[CapabilityInputEnvelope, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_CAPABILITY_INPUTS:
        raise HTTPException(
            status_code=400,
            detail="Invalid capability inputs",
        )
    try:
        parsed = tuple(item if isinstance(item, CapabilityInputEnvelope) else CapabilityInputEnvelope.model_validate(item) for item in value)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid capability input envelope",
        ) from exc
    identities = [(item.capability, item.kind) for item in parsed]
    if len(set(identities)) != len(identities):
        raise HTTPException(
            status_code=400,
            detail="Duplicate capability input envelope",
        )
    return parsed


def extract_capability_inputs(body: Any) -> tuple[CapabilityInputEnvelope, ...]:
    """Read direct REST input or the SDK-compatible context envelope."""

    direct_raw = getattr(body, "capability_inputs", None)
    direct = _parse_capability_inputs(direct_raw)
    context = getattr(body, "context", None)
    contextual_raw = context.get(CAPABILITY_INPUTS_CONTEXT_KEY) if isinstance(context, Mapping) else None
    if contextual_raw is None:
        return direct
    contextual = _parse_capability_inputs(contextual_raw)
    if direct_raw is not None and direct != contextual:
        raise HTTPException(
            status_code=400,
            detail="Conflicting capability inputs",
        )
    return contextual


def inject_trusted_capability_inputs(
    config: dict[str, Any],
    resolved_inputs: Sequence[CapabilityInputEnvelope],
) -> None:
    """Replace client copies with server-resolved request-scoped envelopes."""

    for section in ("context", "configurable"):
        value = config.get(section)
        if isinstance(value, dict):
            value.pop(CAPABILITY_INPUTS_CONTEXT_KEY, None)
    if not resolved_inputs:
        return
    runtime_context = config.setdefault("context", {})
    if not isinstance(runtime_context, dict):
        raise HTTPException(
            status_code=400,
            detail="request config context must be an object",
        )
    runtime_context[CAPABILITY_INPUTS_CONTEXT_KEY] = [item.model_dump(mode="json", by_alias=True) for item in resolved_inputs]


async def resolve_capability_inputs_for_run(
    inputs: Sequence[CapabilityInputEnvelope],
    *,
    identity: CanonicalAgentIdentity,
    user_id: str,
) -> tuple[CapabilityInputEnvelope, ...]:
    """Resolve every optimistic input through the selected Agent's adapters."""

    if not inputs:
        return ()
    definition = get_builtin_agent(identity.agent_name)
    adapter_paths = definition.capability_adapters if definition is not None else ()
    adapters = {adapter.key: adapter for adapter in load_capability_adapters(adapter_paths)}
    context = CapabilityResolutionContext(
        assistant_id=identity.assistant_id,
        agent_name=identity.agent_name,
        user_id=user_id,
    )
    resolved: list[CapabilityInputEnvelope] = []
    for item in inputs:
        adapter = adapters.get(item.capability)
        if adapter is None:
            raise HTTPException(
                status_code=400,
                detail=(f"Capability {item.capability!r} is not available for the selected Agent"),
            )
        try:
            payload = await asyncio.to_thread(
                adapter.resolve_input,
                item.kind,
                item.payload,
                context=context,
            )
        except (CapabilityInputInvalidError, CapabilityInputUnsupportedError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except CapabilityInputNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CapabilityInputConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CapabilityInputIntegrityError as exc:
            logger.error(
                "Capability %s input failed integrity checks",
                item.capability,
                exc_info=True,
            )
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CapabilityInputUnavailableError as exc:
            logger.error(
                "Capability %s input could not be resolved",
                item.capability,
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if not isinstance(payload, Mapping):
            logger.error(
                "Capability %s adapter returned a non-mapping payload",
                item.capability,
            )
            raise HTTPException(
                status_code=500,
                detail="Capability input resolver returned an invalid payload",
            )
        resolved.append(
            CapabilityInputEnvelope(
                capability=item.capability,
                kind=item.kind,
                payload=dict(payload),
            )
        )
    return tuple(resolved)
