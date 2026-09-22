"""Bounded cached readiness checks for built-in Agent capabilities."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass

from vassilflow.capabilities import (
    CapabilityReadinessCheck,
    CapabilityReadinessContext,
    capability_readiness,
)

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 15.0
_PROBE_TIMEOUT_SECONDS = 4.0
_MAX_CACHE_ENTRIES = 128
_MAX_INFLIGHT_PROBES = 128
_CACHE_LOCK = threading.Lock()
type _CacheKey = tuple[
    tuple[str, ...],
    str,
    str,
    str | None,
]
type _ReadinessChecks = tuple[CapabilityReadinessCheck, ...]


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    expires_at: float
    checks: tuple[CapabilityReadinessCheck, ...]


_CACHE: OrderedDict[_CacheKey, _CacheEntry] = OrderedDict()
_INFLIGHT: dict[_CacheKey, Future[_ReadinessChecks]] = {}


def clear_capability_readiness_cache() -> None:
    """Clear process-local readiness evidence, primarily for deterministic tests."""

    with _CACHE_LOCK:
        _CACHE.clear()


def _probe(
    adapter_paths: tuple[str, ...],
    context: CapabilityReadinessContext,
) -> tuple[CapabilityReadinessCheck, ...]:
    try:
        return capability_readiness(
            adapter_paths,
            context=context,
        )
    except Exception:
        logger.exception("Capability adapter readiness probe failed")
        return (
            CapabilityReadinessCheck(
                key=("capability.adapter.global" if context.user_id is None else "capability.adapter.user"),
                status="unavailable",
                required=True,
                detail="The Agent capability adapter could not be checked.",
            ),
        )


def _fallback_checks(
    *,
    context: CapabilityReadinessContext,
    reason: str,
) -> _ReadinessChecks:
    scope = "global" if context.user_id is None else "user"
    return (
        CapabilityReadinessCheck(
            key=f"capability.{reason}.{scope}",
            status="unavailable",
            required=True,
            detail="The Agent capability readiness check did not complete.",
        ),
    )


def _complete_probe(
    key: _CacheKey,
    future: Future[_ReadinessChecks],
    checks: _ReadinessChecks,
) -> None:
    with _CACHE_LOCK:
        if _INFLIGHT.get(key) is future:
            _INFLIGHT.pop(key, None)
        _CACHE[key] = _CacheEntry(
            expires_at=time.monotonic() + _CACHE_TTL_SECONDS,
            checks=checks,
        )
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_CACHE_ENTRIES:
            _CACHE.popitem(last=False)
    if not future.done():
        future.set_result(checks)


async def get_capability_readiness(
    adapter_paths: tuple[str, ...],
    *,
    context: CapabilityReadinessContext,
) -> tuple[CapabilityReadinessCheck, ...]:
    """Return cached readiness without blocking the Gateway event loop."""

    key: _CacheKey = (
        adapter_paths,
        context.assistant_id,
        context.agent_name,
        context.user_id,
    )
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached.expires_at > now:
            _CACHE.move_to_end(key)
            return cached.checks
        if cached is not None:
            _CACHE.pop(key, None)
        inflight = _INFLIGHT.get(key)
        owns_probe = inflight is None
        if owns_probe:
            if len(_INFLIGHT) >= _MAX_INFLIGHT_PROBES:
                return _fallback_checks(
                    context=context,
                    reason="capacity",
                )
            inflight = Future()
            _INFLIGHT[key] = inflight

    if not owns_probe:
        try:
            return await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(inflight)),
                timeout=_PROBE_TIMEOUT_SECONDS + 1.0,
            )
        except TimeoutError:
            logger.error("Timed out waiting for an in-flight capability readiness probe")
            return _fallback_checks(
                context=context,
                reason="wait_timeout",
            )

    try:
        checks = await asyncio.wait_for(
            asyncio.to_thread(
                _probe,
                adapter_paths,
                context,
            ),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.error("Capability readiness probe exceeded its deadline")
        checks = _fallback_checks(
            context=context,
            reason="timeout",
        )
    except Exception:
        logger.exception("Capability readiness probe execution failed")
        checks = _fallback_checks(
            context=context,
            reason="execution",
        )
    except asyncio.CancelledError:
        checks = _fallback_checks(
            context=context,
            reason="cancelled",
        )
        _complete_probe(key, inflight, checks)
        raise

    _complete_probe(key, inflight, checks)
    return checks


async def get_agent_capability_readiness(
    adapter_paths: tuple[str, ...],
    *,
    assistant_id: str,
    agent_name: str,
    user_id: str | None,
) -> tuple[CapabilityReadinessCheck, ...]:
    """Combine globally cached dependencies with optional user storage checks."""

    global_context = CapabilityReadinessContext(
        assistant_id=assistant_id,
        agent_name=agent_name,
        user_id=None,
    )
    if user_id is None:
        return await get_capability_readiness(
            adapter_paths,
            context=global_context,
        )

    global_checks, user_checks = await asyncio.gather(
        get_capability_readiness(
            adapter_paths,
            context=global_context,
        ),
        get_capability_readiness(
            adapter_paths,
            context=CapabilityReadinessContext(
                assistant_id=assistant_id,
                agent_name=agent_name,
                user_id=user_id,
            ),
        ),
    )
    combined = (*global_checks, *user_checks)
    keys = [check.key for check in combined]
    if len(keys) != len(set(keys)):
        logger.error("Capability readiness scopes returned duplicate check keys")
        return (
            CapabilityReadinessCheck(
                key="capability.readiness",
                status="unavailable",
                required=True,
                detail="The Agent readiness scopes conflict.",
            ),
        )
    return combined


__all__ = [
    "clear_capability_readiness_cache",
    "get_agent_capability_readiness",
    "get_capability_readiness",
]
