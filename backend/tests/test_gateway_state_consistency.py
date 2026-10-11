"""Failure and concurrency regressions for Gateway-owned durable state.

These tests use real SQLite writes and independent connection pools. Provider
hashing is stubbed only where a barrier is needed to reproduce an interleaving.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.config import AuthConfig
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.authz import _ALL_PERMISSIONS, AuthContext
from app.gateway.routers import auth, threads
from vassilflow.persistence.base import Base
from vassilflow.persistence.thread_meta.model import ThreadMetaRow
from vassilflow.persistence.thread_meta.sql import ThreadMetaRepository
from vassilflow.persistence.user.model import UserRow
from vassilflow.runtime.user_context import reset_current_user, set_current_user


@pytest.fixture(params=["DELETE", "WAL"])
async def session_factories(tmp_path, request):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'state-consistency.db').as_posix()}"
    engines = [create_async_engine(url), create_async_engine(url)]
    try:
        async with engines[0].begin() as connection:
            await connection.exec_driver_sql(f"PRAGMA journal_mode={request.param}")
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[UserRow.__table__, ThreadMetaRow.__table__]))
        yield [async_sessionmaker(engine, expire_on_commit=False) for engine in engines]
    finally:
        for engine in engines:
            await engine.dispose()


@pytest.mark.anyio
async def test_competing_initializations_have_one_winner(session_factories, monkeypatch):
    repository = SQLiteUserRepository(session_factories[0])
    provider = LocalAuthProvider(repository)
    barrier = asyncio.Barrier(2)

    async def hash_together(_password):
        await barrier.wait()
        return "$dfv2$offline-hash"

    monkeypatch.setattr("app.gateway.auth.local_provider.hash_password_async", hash_together)
    monkeypatch.setattr(auth, "get_local_provider", lambda: provider)
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="gateway-regression-test-secret-at-least-32-characters"))
    app = FastAPI()
    app.include_router(auth.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test.local") as client:
        responses = await asyncio.wait_for(
            asyncio.gather(*[client.post("/api/v1/auth/initialize", json={"email": email, "password": "Example_Test_99!"}) for email in ("first@example.com", "second@example.com")]),
            timeout=5,
        )
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert await repository.count_admin_users() == 1
    winner = next(response for response in responses if response.status_code == 201)
    loser = next(response for response in responses if response.status_code == 409)
    assert winner.json()["system_role"] == "admin"
    assert "access_token" in winner.cookies
    assert "access_token" not in loser.cookies


@pytest.mark.anyio
async def test_independent_repositories_cannot_both_initialize(session_factories):
    repositories = [SQLiteUserRepository(factory) for factory in session_factories]
    outcomes = await asyncio.gather(
        *[repository.create_initial_admin(User(email=f"admin-{index}@example.com", password_hash="hash", system_role="admin")) for index, repository in enumerate(repositories)],
        return_exceptions=True,
    )
    assert sum(isinstance(outcome, User) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, ValueError) for outcome in outcomes) == 1
    assert await repositories[0].count_admin_users() == 1


@pytest.mark.anyio
async def test_rehash_cannot_restore_reset_password_or_revoked_session(session_factories, monkeypatch):
    repository, competing = [SQLiteUserRepository(factory) for factory in session_factories]
    original = await repository.create_user(User(email="legacy@example.com", password_hash="$dfv1$legacy"))
    provider = LocalAuthProvider(repository)
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused_hash(_password):
        entered.set()
        await release.wait()
        return "$dfv2$old-password-rehashed"

    monkeypatch.setattr("app.gateway.auth.local_provider.verify_password_async", AsyncMock(return_value=True))
    monkeypatch.setattr("app.gateway.auth.local_provider.hash_password_async", paused_hash)
    login = asyncio.create_task(provider.authenticate({"email": original.email, "password": "old-password"}))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        updated = await competing.get_user_by_id(str(original.id))
        updated.password_hash = "$dfv2$new-password"
        updated.token_version += 1
        await competing.update_user(updated)
    finally:
        release.set()
    result = await asyncio.wait_for(login, timeout=5)
    persisted = await repository.get_user_by_id(str(original.id))
    assert persisted.password_hash == "$dfv2$new-password"
    assert persisted.token_version == 1
    assert result is None, "A credential changed during verification must not produce a successful login."


@pytest.mark.anyio
async def test_rehash_updates_only_the_hash(session_factories):
    repository, competing = [SQLiteUserRepository(factory) for factory in session_factories]
    original = await repository.create_user(User(email="before@example.com", password_hash="$dfv1$legacy", system_role="admin"))
    newer = await competing.get_user_by_id(str(original.id))
    newer.email = "after@example.com"
    newer.system_role = "user"
    newer.needs_setup = True
    await competing.update_user(newer)
    applied = await repository.rehash_password(str(original.id), expected_password_hash=original.password_hash, expected_token_version=original.token_version, password_hash="$dfv2$upgraded")
    assert applied is True
    persisted = await repository.get_user_by_id(str(original.id))
    assert (persisted.email, persisted.system_role, persisted.needs_setup) == ("after@example.com", "user", True)
    assert persisted.password_hash == "$dfv2$upgraded"
    assert persisted.token_version == 0


@pytest.mark.anyio
@pytest.mark.parametrize("new_hash,new_version", [("changed", 0), ("legacy", 1)])
async def test_rehash_rejects_changed_hash_or_version(session_factories, new_hash, new_version):
    repository = SQLiteUserRepository(session_factories[0])
    original = await repository.create_user(User(email="changed@example.com", password_hash="legacy"))
    updated = original.model_copy(update={"password_hash": new_hash, "token_version": new_version})
    await repository.update_user(updated)
    assert await repository.rehash_password(str(original.id), expected_password_hash="legacy", expected_token_version=0, password_hash="upgraded") is False
    persisted = await repository.get_user_by_id(str(original.id))
    assert (persisted.password_hash, persisted.token_version) == (new_hash, new_version)


@pytest.mark.anyio
async def test_concurrent_metadata_merges_keep_independent_keys(session_factories):
    repositories = [ThreadMetaRepository(factory) for factory in session_factories]
    await repositories[0].create("overlap", user_id="owner", metadata={"original": True, "nested": {"old": 1}})
    barrier = asyncio.Barrier(8)

    async def patch(index):
        await barrier.wait()
        await repositories[index % 2].update_metadata("overlap", {f"key-{index}": index}, user_id="owner")

    await asyncio.wait_for(asyncio.gather(*[patch(index) for index in range(8)]), timeout=10)
    metadata = (await repositories[0].get("overlap", user_id="owner"))["metadata"]
    assert metadata == {"original": True, "nested": {"old": 1}, **{f"key-{index}": index for index in range(8)}}
    await repositories[0].update_metadata("overlap", {"nested": {"new": 2}, "explicit_null": None}, user_id="owner")
    metadata = (await repositories[0].get("overlap", user_id="owner"))["metadata"]
    assert metadata["nested"] == {"new": 2}, "The operation is a shallow merge, not JSON Merge Patch."
    assert "explicit_null" in metadata and metadata["explicit_null"] is None


def _request_for(app, user_id):
    request = Request({"type": "http", "app": app, "method": "GET", "path": "/", "headers": []})
    request.state.auth = AuthContext(user=SimpleNamespace(id=user_id), permissions=_ALL_PERMISSIONS)
    return request


@pytest.mark.anyio
@pytest.mark.parametrize("deletion_error", [OSError, NotImplementedError])
async def test_checkpoint_delete_failure_retains_owner_and_retry_succeeds(session_factories, monkeypatch, deletion_error):
    repository = ThreadMetaRepository(session_factories[0])
    thread_id = "delete-failure"
    await repository.create(thread_id, user_id="owner")

    class FailingSaver(InMemorySaver):
        failing = True

        async def adelete_thread(self, thread_id):
            if self.failing:
                raise deletion_error("checkpoint delete unavailable")
            await super().adelete_thread(thread_id)

    saver = FailingSaver()
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"title": "Private owner data", "messages": []}
    checkpoint["channel_versions"] = {"title": "1", "messages": "1"}
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    await saver.aput(config, checkpoint, {}, checkpoint["channel_versions"])
    app = FastAPI()
    app.state.thread_store = repository
    app.state.checkpointer = saver
    dispatcher = SimpleNamespace(prepare_thread_deleted=AsyncMock(return_value="intent"), abort_source=AsyncMock(), commit_thread_deleted=AsyncMock())
    app.state.thread_lifecycle_dispatcher = dispatcher
    monkeypatch.setattr(threads, "get_memory_queue", lambda: SimpleNamespace(discard_thread=Mock()))
    monkeypatch.setattr(threads, "_delete_thread_data", lambda *_args, **_kwargs: threads.ThreadDeleteResponse(success=True, message="test cleanup"))

    async def assert_other_denied():
        token = set_current_user(SimpleNamespace(id="other"))
        try:
            with pytest.raises(HTTPException) as rejected:
                await threads.get_thread_state(thread_id=thread_id, request=_request_for(app, "other"))
            assert rejected.value.status_code == 404
        finally:
            reset_current_user(token)

    await assert_other_denied()
    token = set_current_user(SimpleNamespace(id="owner"))
    try:
        with pytest.raises(HTTPException) as deletion:
            await threads.delete_thread_data(thread_id=thread_id, request=_request_for(app, "owner"))
        assert deletion.value.status_code == 503
        assert await repository.get(thread_id, user_id="owner") is not None
        assert await saver.aget_tuple(config) is not None
        dispatcher.abort_source.assert_awaited_once()
        dispatcher.commit_thread_deleted.assert_not_awaited()
        await assert_other_denied()

        saver.failing = False
        response = await threads.delete_thread_data(thread_id=thread_id, request=_request_for(app, "owner"))
        assert response.success is True
        assert await repository.get(thread_id, user_id="owner") is None
        assert await saver.aget_tuple(config) is None
        dispatcher.commit_thread_deleted.assert_awaited_once()
    finally:
        reset_current_user(token)
