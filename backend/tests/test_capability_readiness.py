from __future__ import annotations

import asyncio
import time

import pytest

from app.gateway import capability_readiness as readiness_cache
from vassilflow.capabilities import (
    CapabilityReadinessCheck,
    CapabilityReadinessContext,
)
from vassilflow.capabilities import adapter as capability_adapter


@pytest.mark.anyio
async def test_capability_readiness_cache_is_scoped_and_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    now = [100.0]

    def probe(adapter_paths, context):
        nonlocal calls
        assert adapter_paths == ("example:Adapter",)
        assert context.user_id == "alice"
        calls += 1
        return (
            CapabilityReadinessCheck(
                key="example.service",
                status="ready",
                required=True,
                detail="Example service is ready.",
            ),
        )

    monkeypatch.setattr(readiness_cache, "_probe", probe)
    monkeypatch.setattr(
        readiness_cache.time,
        "monotonic",
        lambda: now[0],
    )
    readiness_cache.clear_capability_readiness_cache()
    context = CapabilityReadinessContext(
        assistant_id="example",
        agent_name="example",
        user_id="alice",
    )

    first = await readiness_cache.get_capability_readiness(
        ("example:Adapter",),
        context=context,
    )
    now[0] += 10
    second = await readiness_cache.get_capability_readiness(
        ("example:Adapter",),
        context=context,
    )
    now[0] += 6
    third = await readiness_cache.get_capability_readiness(
        ("example:Adapter",),
        context=context,
    )

    assert first == second == third
    assert calls == 2
    readiness_cache.clear_capability_readiness_cache()


@pytest.mark.anyio
async def test_agent_readiness_reuses_global_probe_across_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_users: list[str | None] = []

    def probe(adapter_paths, context):
        assert adapter_paths == ("example:Adapter",)
        seen_users.append(context.user_id)
        if context.user_id is None:
            return (
                CapabilityReadinessCheck(
                    key="example.service",
                    status="ready",
                    required=False,
                    detail="Example service is ready.",
                ),
            )
        return (
            CapabilityReadinessCheck(
                key="example.storage",
                status="ready",
                required=True,
                detail="Example storage is ready.",
            ),
        )

    monkeypatch.setattr(readiness_cache, "_probe", probe)
    readiness_cache.clear_capability_readiness_cache()

    alice = await readiness_cache.get_agent_capability_readiness(
        ("example:Adapter",),
        assistant_id="example",
        agent_name="example",
        user_id="alice",
    )
    bob = await readiness_cache.get_agent_capability_readiness(
        ("example:Adapter",),
        assistant_id="example",
        agent_name="example",
        user_id="bob",
    )

    assert [check.key for check in alice] == [
        "example.service",
        "example.storage",
    ]
    assert [check.key for check in bob] == [
        "example.service",
        "example.storage",
    ]
    assert len(seen_users) == 3
    assert set(seen_users) == {None, "alice", "bob"}
    readiness_cache.clear_capability_readiness_cache()


def test_capability_probe_failure_returns_sanitized_required_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(adapter_paths, *, context):
        assert adapter_paths
        assert context.agent_name == "example"
        raise RuntimeError("secret renderer URL")

    monkeypatch.setattr(readiness_cache, "capability_readiness", fail)

    checks = readiness_cache._probe(
        ("example:Adapter",),
        CapabilityReadinessContext(
            assistant_id="example",
            agent_name="example",
            user_id=None,
        ),
    )

    assert checks[0].key == "capability.adapter.global"
    assert checks[0].status == "unavailable"
    assert checks[0].required is True
    assert "secret" not in checks[0].detail


@pytest.mark.anyio
async def test_capability_readiness_coalesces_concurrent_cold_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def probe(adapter_paths, context):
        nonlocal calls
        assert adapter_paths == ("example:Adapter",)
        assert context.user_id is None
        calls += 1
        time.sleep(0.05)
        return (
            CapabilityReadinessCheck(
                key="example.service",
                status="ready",
                required=True,
                detail="Example service is ready.",
            ),
        )

    monkeypatch.setattr(readiness_cache, "_probe", probe)
    readiness_cache.clear_capability_readiness_cache()
    context = CapabilityReadinessContext(
        assistant_id="example",
        agent_name="example",
        user_id=None,
    )

    first, second = await asyncio.gather(
        readiness_cache.get_capability_readiness(
            ("example:Adapter",),
            context=context,
        ),
        readiness_cache.get_capability_readiness(
            ("example:Adapter",),
            context=context,
        ),
    )

    assert first == second
    assert calls == 1
    readiness_cache.clear_capability_readiness_cache()


@pytest.mark.anyio
async def test_capability_readiness_timeout_fails_closed_and_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def probe(_adapter_paths, _context):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return ()

    monkeypatch.setattr(readiness_cache, "_probe", probe)
    monkeypatch.setattr(
        readiness_cache,
        "_PROBE_TIMEOUT_SECONDS",
        0.01,
    )
    readiness_cache.clear_capability_readiness_cache()
    context = CapabilityReadinessContext(
        assistant_id="example",
        agent_name="example",
        user_id=None,
    )

    first = await readiness_cache.get_capability_readiness(
        ("example:Adapter",),
        context=context,
    )
    second = await readiness_cache.get_capability_readiness(
        ("example:Adapter",),
        context=context,
    )

    assert first == second
    assert first[0].key == "capability.timeout.global"
    assert first[0].status == "unavailable"
    assert first[0].required is True
    assert calls == 1
    readiness_cache.clear_capability_readiness_cache()


def test_capability_adapter_instances_are_not_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExampleAdapter:
        key = "example"

        def resolve_input(self, kind, payload, *, context):
            return payload

        def build_middlewares(self):
            return ()

        def check_readiness(self, *, context):
            return ()

        def build_project_repositories(self, *, context):
            return ()

    monkeypatch.setattr(
        capability_adapter,
        "resolve_class",
        lambda _path: ExampleAdapter,
    )

    first = capability_adapter.load_capability_adapters(("example:Adapter",))
    second = capability_adapter.load_capability_adapters(("example:Adapter",))

    assert first[0] is not second[0]
