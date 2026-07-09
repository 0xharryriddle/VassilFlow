"""Regression anchors for Discord channel filesystem IO on async paths."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.channels.discord import DiscordChannel
from app.channels.message_bus import MessageBus

pytestmark = pytest.mark.asyncio


class _FakeStore:
    def __init__(self, tmp_path: Path) -> None:
        self._path = tmp_path / "channel_store.json"


async def test_discord_constructor_is_io_free_on_async_path(tmp_path: Path) -> None:
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "t", "channel_store": _FakeStore(tmp_path)})

    assert channel._bot_token == "t"
    assert channel._thread_store_path == tmp_path / "discord_threads.json"


async def test_discord_record_then_persist_does_not_block_event_loop(tmp_path: Path) -> None:
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    channel._record_thread_mapping("chan-1", "thread-1")
    assert channel._active_threads == {"chan-1": "thread-1"}
    assert "thread-1" in channel._active_thread_ids

    await asyncio.to_thread(channel._persist_thread_mappings)

    data = json.loads(await asyncio.to_thread(channel._thread_store_path.read_text))
    assert data == {"chan-1": "thread-1"}


async def test_discord_record_thread_mapping_visible_before_persist(tmp_path: Path) -> None:
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    channel._record_thread_mapping("chan-1", "thread-1")

    assert "thread-1" in channel._active_thread_ids
    assert channel._active_threads["chan-1"] == "thread-1"
    assert not await asyncio.to_thread(channel._thread_store_path.exists)


async def test_discord_record_thread_mapping_discards_replaced_thread(tmp_path: Path) -> None:
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    channel._record_thread_mapping("chan-1", "thread-1")
    channel._record_thread_mapping("chan-1", "thread-2")

    assert channel._active_threads == {"chan-1": "thread-2"}
    assert "thread-1" not in channel._active_thread_ids
    assert "thread-2" in channel._active_thread_ids


async def test_discord_load_active_threads_does_not_block_event_loop(tmp_path: Path) -> None:
    path = tmp_path / "discord_threads.json"
    await asyncio.to_thread(path.write_text, json.dumps({"chan-1": "thread-1", "chan-2": "thread-2"}))

    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    await asyncio.to_thread(channel._load_active_threads)

    assert channel._active_threads == {"chan-1": "thread-1", "chan-2": "thread-2"}
    assert channel._active_thread_ids == {"thread-1", "thread-2"}
