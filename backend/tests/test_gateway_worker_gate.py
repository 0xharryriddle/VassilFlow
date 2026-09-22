"""The current process-local runtime must never start multiple workers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.gateway.deps import _enforce_single_worker, langgraph_runtime
from vassilflow.config.database_config import DatabaseConfig


def _config_with_backend(backend: str) -> SimpleNamespace:
    return SimpleNamespace(database=DatabaseConfig(backend=backend))


@pytest.fixture(autouse=True)
def _clear_worker_environment(monkeypatch):
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


def test_gate_noop_when_worker_counts_unset():
    _enforce_single_worker()


@pytest.mark.parametrize("variable", ["GATEWAY_WORKERS", "WEB_CONCURRENCY"])
def test_gate_noop_for_single_worker(monkeypatch, variable):
    monkeypatch.setenv(variable, "1")
    _enforce_single_worker()


@pytest.mark.parametrize("variable", ["GATEWAY_WORKERS", "WEB_CONCURRENCY"])
@pytest.mark.parametrize("workers", ["2", "4"])
def test_gate_rejects_multiple_workers(monkeypatch, variable, workers):
    monkeypatch.setenv(variable, workers)
    with pytest.raises(SystemExit) as exc_info:
        _enforce_single_worker()
    msg = str(exc_info.value)
    assert f"{variable}={workers}" in msg
    assert "RunManager" in msg
    assert "StreamBridge" in msg
    assert f"{variable}=1" in msg


@pytest.mark.parametrize("variable", ["GATEWAY_WORKERS", "WEB_CONCURRENCY"])
@pytest.mark.parametrize("value", ["", "auto", "1.5", "abc", "0x4", "0", "-1", "-999"])
def test_gate_rejects_invalid_worker_counts(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(SystemExit):
        _enforce_single_worker()


def test_single_gateway_worker_does_not_hide_web_concurrency(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(SystemExit, match="WEB_CONCURRENCY=2"):
        _enforce_single_worker()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "memory", "postgres"])
@pytest.mark.parametrize("variable", ["GATEWAY_WORKERS", "WEB_CONCURRENCY"])
async def test_langgraph_runtime_invokes_gate_before_persistence_setup(monkeypatch, backend, variable):
    monkeypatch.setenv(variable, "2")
    init_engine_from_config = AsyncMock(name="init_engine_from_config")

    @asynccontextmanager
    async def _noop_context(_config):
        yield MagicMock()

    with (
        patch("vassilflow.persistence.engine.init_engine_from_config", init_engine_from_config),
        patch("vassilflow.runtime.make_stream_bridge", side_effect=_noop_context) as make_stream_bridge,
        patch("vassilflow.runtime.make_store", side_effect=_noop_context) as make_store,
    ):
        app = FastAPI()
        with pytest.raises(SystemExit):
            async with langgraph_runtime(app, _config_with_backend(backend)):
                pass

    init_engine_from_config.assert_not_called()
    make_stream_bridge.assert_not_called()
    make_store.assert_not_called()
