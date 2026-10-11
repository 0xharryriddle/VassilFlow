"""The channel manager owns and drains its dispatched handlers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.store import ChannelStore


@pytest.mark.anyio
async def test_stop_cancels_running_and_semaphore_waiting_handlers(tmp_path, monkeypatch):
    bus = MessageBus()
    manager = ChannelManager(bus, ChannelStore(path=tmp_path / "channels.json"), max_concurrency=1)
    first_started, both_dispatched, cleanup_started, release_cleanup = (asyncio.Event() for _ in range(4))
    chats = []
    handlers = []
    original_handler = manager._handle_message

    async def track_handler(message):
        handlers.append(asyncio.current_task())
        if len(handlers) == 2:
            both_dispatched.set()
        await original_handler(message)

    async def chat(message, **kwargs):
        chats.append(message.chat_id)
        first_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()

    monkeypatch.setattr(manager, "_handle_message", track_handler)
    monkeypatch.setattr(manager, "_handle_chat", chat)
    await manager.start()
    await bus.publish_inbound(InboundMessage(channel_name="test", chat_id="first", user_id="user", text="Hello", workspace_id="workspace", metadata={"message_id": "first"}))
    await asyncio.wait_for(first_started.wait(), 1)
    await bus.publish_inbound(InboundMessage(channel_name="test", chat_id="second", user_id="user", text="Hello again", workspace_id="workspace", metadata={"message_id": "second"}))
    await asyncio.wait_for(both_dispatched.wait(), 1)
    shutdown = asyncio.create_task(manager.stop())
    try:
        await asyncio.wait_for(cleanup_started.wait(), 1)
        assert not shutdown.done(), "stop must await handler cleanup"
        release_cleanup.set()
        await asyncio.wait_for(shutdown, 1)
        assert all(task.done() for task in handlers)
        assert chats == ["first"], "a semaphore waiter must not start during shutdown"
        assert not manager._handler_tasks
        assert not manager._recent_inbound_events, "cancelled messages must be eligible for redelivery"
        await manager.start()
        await manager.stop()
    finally:
        release_cleanup.set()
        for task in handlers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*handlers, shutdown, return_exceptions=True)
        await manager.stop()


@pytest.mark.anyio
async def test_cancelled_stop_caller_does_not_interrupt_owned_cleanup(tmp_path, monkeypatch):
    manager = ChannelManager(MessageBus(), ChannelStore(path=tmp_path / "channels.json"))
    started, cleaning, release = (asyncio.Event() for _ in range(3))

    async def handler(message):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    monkeypatch.setattr(manager, "_handle_message", handler)
    await manager.start()
    await manager.bus.publish_inbound(InboundMessage(channel_name="test", chat_id="chat", user_id="user", text="Hello"))
    await started.wait()
    caller = asyncio.create_task(manager.stop())
    await cleaning.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    repeated = asyncio.create_task(manager.stop())
    try:
        await asyncio.sleep(0)
        assert not repeated.done()
        assert len(manager._handler_tasks) == 1
        assert not next(iter(manager._handler_tasks)).done()
        release.set()
        await asyncio.wait_for(repeated, 1)
        assert not manager._handler_tasks
    finally:
        release.set()
        await manager.stop()


@pytest.mark.anyio
async def test_service_waits_for_handler_drain_before_stopping_transports(tmp_path, monkeypatch):
    from app.channels.service import ChannelService

    monkeypatch.setattr("app.channels.service.ChannelStore", lambda: ChannelStore(path=tmp_path / "channels.json"))
    service = ChannelService({})
    draining, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def drain():
        draining.set()
        await release.wait()
        calls.append("drained")

    async def stop_channel():
        calls.append("transport stopped")

    service.manager.stop = AsyncMock(side_effect=drain)
    transport = SimpleNamespace(stop=AsyncMock(side_effect=stop_channel))
    service._channels["test"] = transport
    service._running = True
    shutdown = asyncio.create_task(service.stop())
    try:
        await draining.wait()
        transport.stop.assert_not_awaited()
        release.set()
        await shutdown
        assert calls == ["drained", "transport stopped"]
        assert not service._channels
    finally:
        release.set()
        await shutdown
