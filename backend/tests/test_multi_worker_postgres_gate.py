"""Tests for the multi-worker Postgres startup gate."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.gateway.deps import _enforce_postgres_for_multi_worker, langgraph_runtime
from vassilflow.config.database_config import DatabaseConfig


def _config_with_backend(backend: str) -> SimpleNamespace:
    return SimpleNamespace(database=DatabaseConfig(backend=backend))


def test_gate_noop_when_gateway_workers_unset(monkeypatch):
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    for backend in ("sqlite", "memory", "postgres"):
        _enforce_postgres_for_multi_worker(_config_with_backend(backend))


def test_gate_noop_for_single_worker(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    for backend in ("sqlite", "memory", "postgres"):
        _enforce_postgres_for_multi_worker(_config_with_backend(backend))


def test_gate_allows_multi_worker_with_postgres(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    _enforce_postgres_for_multi_worker(_config_with_backend("postgres"))


def test_gate_rejects_multi_worker_with_sqlite(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    msg = str(exc_info.value)
    assert "GATEWAY_WORKERS=2" in msg
    assert "postgres" in msg.lower()
    assert "sqlite" in msg.lower()


def test_gate_rejects_multi_worker_with_memory(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit):
        _enforce_postgres_for_multi_worker(_config_with_backend("memory"))


def test_gate_rejects_high_worker_counts(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "4")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    assert "GATEWAY_WORKERS=4" in str(exc_info.value)


def test_gate_treats_invalid_env_as_single_worker(monkeypatch):
    for invalid in ("", "auto", "1.5", "abc", "0x4"):
        monkeypatch.setenv("GATEWAY_WORKERS", invalid)
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))


def test_gate_treats_zero_and_negatives_as_single_worker(monkeypatch):
    for value in ("0", "-1", "-999"):
        monkeypatch.setenv("GATEWAY_WORKERS", value)
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))


def test_gate_error_message_lists_both_remediations(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    msg = str(exc_info.value)
    assert "GATEWAY_WORKERS=1" in msg
    assert "Postgres" in msg


@pytest.mark.asyncio
async def test_langgraph_runtime_invokes_gate_before_persistence_setup(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
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
            async with langgraph_runtime(app, _config_with_backend("sqlite")):
                pass

    init_engine_from_config.assert_not_called()
    make_stream_bridge.assert_not_called()
    make_store.assert_not_called()
