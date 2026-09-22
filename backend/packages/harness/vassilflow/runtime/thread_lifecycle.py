"""Domain-neutral lifecycle notifications for conversation resources."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from .lifecycle_journal import (
    FileThreadLifecycleJournal,
    validate_lifecycle_handler_key,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ThreadDeleted:
    """One user-owned conversation has been deleted."""

    user_id: str
    thread_id: str


@dataclass(frozen=True, slots=True)
class ThreadBranched:
    """One conversation branch has been created."""

    user_id: str
    source_thread_id: str
    target_thread_id: str
    assistant_id: str
    workspace_clone_mode: str
    recorded_at: str | None = None


@dataclass(frozen=True, slots=True)
class ThreadLifecycleIntent:
    """Durable source intent prepared before one core thread mutation."""

    user_id: str
    event_name: str
    operation_id: str | None


class ThreadLifecycleHandler(Protocol):
    """Optional idempotent domain adapter for thread lifecycle changes."""

    key: str

    async def on_thread_deleted(self, event: ThreadDeleted) -> None: ...

    async def on_thread_branched(self, event: ThreadBranched) -> None: ...


class ThreadLifecycleDispatchError(RuntimeError):
    """One or more lifecycle handlers failed after all handlers were attempted."""

    def __init__(
        self,
        event_name: str,
        failures: tuple[Exception, ...],
        *,
        operation_id: str | None = None,
        failed_handler_keys: tuple[str, ...] = (),
    ) -> None:
        self.event_name = event_name
        self.failures = failures
        self.operation_id = operation_id
        self.failed_handler_keys = failed_handler_keys
        super().__init__(f"{len(failures)} handler(s) failed while projecting {event_name}")


@dataclass(frozen=True, slots=True)
class ThreadLifecycleReplayReport:
    """Aggregate result for one bounded user-scoped replay pass."""

    scanned: int
    pending: int
    repaired: int
    still_pending: int
    failed: int
    awaiting_source: int
    limit_reached: bool


class ThreadLifecycleDispatcher:
    """Dispatch thread lifecycle changes to registered domain adapters."""

    def __init__(
        self,
        handlers: tuple[ThreadLifecycleHandler, ...] = (),
        *,
        journal_factory: Callable[[str], FileThreadLifecycleJournal] | None = None,
        running_attempt_lease: timedelta = timedelta(minutes=5),
        attempt_heartbeat_interval: timedelta | None = None,
    ) -> None:
        if running_attempt_lease < timedelta(0):
            raise ValueError("Lifecycle running-attempt lease is invalid")
        if attempt_heartbeat_interval is None:
            attempt_heartbeat_interval = running_attempt_lease / 3 if running_attempt_lease > timedelta(0) else None
        elif attempt_heartbeat_interval <= timedelta(0) or running_attempt_lease <= timedelta(0) or attempt_heartbeat_interval >= running_attempt_lease:
            raise ValueError("Lifecycle heartbeat interval must be shorter than its lease")
        self._handlers = handlers
        self._journal_factory = journal_factory
        self._running_attempt_lease = running_attempt_lease
        self._attempt_heartbeat_interval = attempt_heartbeat_interval
        self._handlers_by_key: dict[str, ThreadLifecycleHandler] = {}
        for handler in handlers:
            key = validate_lifecycle_handler_key(handler.key)
            if key in self._handlers_by_key:
                raise ValueError(f"Lifecycle handler key {key!r} is duplicated")
            self._handlers_by_key[key] = handler

    @property
    def handler_keys(self) -> tuple[str, ...]:
        """Return stable handler identities in dispatch order."""

        return tuple(self._handlers_by_key)

    async def _prepare(
        self,
        *,
        user_id: str,
        event_name: str,
        payload: dict[str, str],
    ) -> ThreadLifecycleIntent:
        if self._journal_factory is None:
            return ThreadLifecycleIntent(
                user_id=user_id,
                event_name=event_name,
                operation_id=None,
            )
        journal = self._journal_factory(user_id)
        operation = await asyncio.to_thread(
            journal.prepare,
            event_name=event_name,
            payload=payload,
            handler_keys=self.handler_keys,
        )
        return ThreadLifecycleIntent(
            user_id=user_id,
            event_name=event_name,
            operation_id=operation["operation_id"],
        )

    @staticmethod
    def _restore_event(
        operation: dict,
    ) -> ThreadDeleted | ThreadBranched:
        payload = operation["payload"]
        if operation["event"] == "thread_deleted":
            return ThreadDeleted(
                user_id=operation["owner_user_id"],
                thread_id=payload["thread_id"],
            )
        return ThreadBranched(
            user_id=operation["owner_user_id"],
            source_thread_id=payload["source_thread_id"],
            target_thread_id=payload["target_thread_id"],
            assistant_id=payload["assistant_id"],
            workspace_clone_mode=payload["workspace_clone_mode"],
            recorded_at=operation.get("source_committed_at"),
        )

    async def _dispatch_direct(
        self,
        event_name: str,
        event: ThreadDeleted | ThreadBranched,
    ) -> None:
        failures: list[Exception] = []
        failed_handler_keys: list[str] = []
        for handler_key, handler in self._handlers_by_key.items():
            try:
                if event_name == "thread_deleted":
                    await handler.on_thread_deleted(event)  # type: ignore[arg-type]
                else:
                    await handler.on_thread_branched(event)  # type: ignore[arg-type]
            except Exception as exc:
                failures.append(exc)
                failed_handler_keys.append(handler_key)
        if failures:
            raise ThreadLifecycleDispatchError(
                event_name,
                tuple(failures),
                failed_handler_keys=tuple(failed_handler_keys),
            ) from failures[0]

    async def _dispatch_durable(
        self,
        journal: FileThreadLifecycleJournal,
        operation: dict,
    ) -> dict:
        event_name = operation["event"]
        operation_id = operation["operation_id"]
        event = self._restore_event(operation)
        failures: list[Exception] = []
        failed_handler_keys: list[str] = []

        for handler_key in operation["handlers"]:
            handler = self._handlers_by_key.get(handler_key)
            if handler is None:
                failures.append(RuntimeError("Registered lifecycle handler is unavailable"))
                failed_handler_keys.append(handler_key)
                continue
            try:
                attempt_id = await asyncio.to_thread(
                    journal.begin_attempt,
                    operation_id,
                    handler_key,
                    running_lease=self._running_attempt_lease,
                )
            except Exception as exc:
                failures.append(exc)
                failed_handler_keys.append(handler_key)
                continue
            if attempt_id is None:
                continue

            heartbeat_stop: asyncio.Event | None = None
            heartbeat_task: asyncio.Task[None] | None = None
            if self._attempt_heartbeat_interval is not None:
                heartbeat_stop = asyncio.Event()
                heartbeat_task = asyncio.create_task(
                    self._heartbeat_attempt(
                        journal,
                        operation_id,
                        handler_key,
                        attempt_id,
                        heartbeat_stop,
                    )
                )
            handler_error: Exception | None = None
            try:
                if event_name == "thread_deleted":
                    await handler.on_thread_deleted(event)  # type: ignore[arg-type]
                else:
                    await handler.on_thread_branched(event)  # type: ignore[arg-type]
            except Exception as exc:
                handler_error = exc
            finally:
                await self._stop_heartbeat(
                    heartbeat_stop,
                    heartbeat_task,
                )

            if handler_error is not None:
                try:
                    await asyncio.to_thread(
                        journal.finish_attempt,
                        operation_id,
                        handler_key,
                        attempt_id,
                        succeeded=False,
                        error_type=type(handler_error).__name__[:128],
                    )
                except Exception:
                    logger.exception("Could not persist failed lifecycle handler attempt")
                failures.append(handler_error)
                failed_handler_keys.append(handler_key)
                continue

            try:
                await asyncio.to_thread(
                    journal.finish_attempt,
                    operation_id,
                    handler_key,
                    attempt_id,
                    succeeded=True,
                )
            except Exception as exc:
                failures.append(exc)
                failed_handler_keys.append(handler_key)

        projection = await asyncio.to_thread(journal.get, operation_id)
        if failures:
            raise ThreadLifecycleDispatchError(
                event_name,
                tuple(failures),
                operation_id=operation_id,
                failed_handler_keys=tuple(failed_handler_keys),
            ) from failures[0]
        return projection

    async def _heartbeat_attempt(
        self,
        journal: FileThreadLifecycleJournal,
        operation_id: str,
        handler_key: str,
        attempt_id: str,
        stop: asyncio.Event,
    ) -> None:
        interval = self._attempt_heartbeat_interval
        if interval is None:
            return
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=interval.total_seconds(),
                )
                return
            except TimeoutError:
                await asyncio.to_thread(
                    journal.renew_attempt,
                    operation_id,
                    handler_key,
                    attempt_id,
                    lease_duration=self._running_attempt_lease,
                )

    @staticmethod
    async def _stop_heartbeat(
        stop: asyncio.Event | None,
        task: asyncio.Task[None] | None,
    ) -> None:
        if stop is None or task is None:
            return
        stop.set()
        try:
            await task
        except Exception:
            logger.error(
                "Could not renew lifecycle handler-attempt lease",
                exc_info=True,
            )

    async def prepare_thread_deleted(
        self,
        event: ThreadDeleted,
    ) -> ThreadLifecycleIntent:
        """Persist a delete intent before core thread state is removed."""

        return await self._prepare(
            user_id=event.user_id,
            event_name="thread_deleted",
            payload={"thread_id": event.thread_id},
        )

    async def prepare_thread_branched(
        self,
        event: ThreadBranched,
    ) -> ThreadLifecycleIntent:
        """Persist a branch intent before target thread state is written."""

        return await self._prepare(
            user_id=event.user_id,
            event_name="thread_branched",
            payload={
                "source_thread_id": event.source_thread_id,
                "target_thread_id": event.target_thread_id,
                "assistant_id": event.assistant_id,
                "workspace_clone_mode": event.workspace_clone_mode,
            },
        )

    async def _commit(
        self,
        intent: ThreadLifecycleIntent,
        event: ThreadDeleted | ThreadBranched,
    ) -> None:
        if event.user_id != intent.user_id:
            raise ValueError("Lifecycle intent owner does not match its event")
        if intent.operation_id is None:
            await self._dispatch_direct(intent.event_name, event)
            return
        if self._journal_factory is None:
            raise RuntimeError("Lifecycle journaling is not configured")
        journal = self._journal_factory(intent.user_id)
        if intent.event_name == "thread_deleted":
            if not isinstance(event, ThreadDeleted):
                raise ValueError("Lifecycle delete intent has the wrong event type")
            payload = {"thread_id": event.thread_id}
        else:
            if not isinstance(event, ThreadBranched):
                raise ValueError("Lifecycle branch intent has the wrong event type")
            payload = {
                "source_thread_id": event.source_thread_id,
                "target_thread_id": event.target_thread_id,
                "assistant_id": event.assistant_id,
                "workspace_clone_mode": event.workspace_clone_mode,
            }
        operation = await asyncio.to_thread(
            journal.commit_source,
            intent.operation_id,
            payload=payload,
        )
        await self._dispatch_durable(journal, operation)

    async def commit_thread_deleted(
        self,
        intent: ThreadLifecycleIntent,
        event: ThreadDeleted,
    ) -> None:
        """Commit a completed delete source mutation and fan it out."""

        if intent.event_name != "thread_deleted":
            raise ValueError("Lifecycle intent is not a thread delete")
        await self._commit(intent, event)

    async def commit_thread_branched(
        self,
        intent: ThreadLifecycleIntent,
        event: ThreadBranched,
    ) -> None:
        """Commit a completed branch source mutation and fan it out."""

        if intent.event_name != "thread_branched":
            raise ValueError("Lifecycle intent is not a thread branch")
        await self._commit(intent, event)

    async def abort_source(
        self,
        intent: ThreadLifecycleIntent,
        *,
        error_type: str,
    ) -> None:
        """Mark a prepared source intent terminal after a mutation failure."""

        if intent.operation_id is None:
            return
        if self._journal_factory is None:
            raise RuntimeError("Lifecycle journaling is not configured")
        journal = self._journal_factory(intent.user_id)
        await asyncio.to_thread(
            journal.abort_source,
            intent.operation_id,
            error_type=error_type,
        )

    async def thread_deleted(self, event: ThreadDeleted) -> None:
        intent = await self.prepare_thread_deleted(event)
        await self.commit_thread_deleted(intent, event)

    async def thread_branched(self, event: ThreadBranched) -> None:
        intent = await self.prepare_thread_branched(event)
        await self.commit_thread_branched(intent, event)

    async def replay_user(
        self,
        user_id: str,
        *,
        limit: int = 500,
    ) -> ThreadLifecycleReplayReport:
        """Retry only unfinished handlers from durable lifecycle operations."""

        if self._journal_factory is None:
            raise RuntimeError("Lifecycle journaling is not configured")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Lifecycle replay limit is invalid")
        journal = self._journal_factory(user_id)
        pending_operations = await asyncio.to_thread(
            journal.list,
            limit=10_000,
            unfinished_only=True,
            oldest_first=True,
        )
        committed_operations = [operation for operation in pending_operations if operation["source_status"] == "committed"]
        limited_operations = committed_operations[:limit]
        limit_reached = len(committed_operations) > limit
        repaired = 0
        failed = 0
        for operation in limited_operations:
            try:
                projection = await self._dispatch_durable(
                    journal,
                    operation,
                )
            except ThreadLifecycleDispatchError:
                failed += 1
                continue
            if projection["status"] == "succeeded":
                repaired += 1
        remaining = await asyncio.to_thread(
            journal.list,
            limit=10_000,
            unfinished_only=True,
            oldest_first=True,
        )
        return ThreadLifecycleReplayReport(
            scanned=len(limited_operations),
            pending=len(pending_operations),
            repaired=repaired,
            still_pending=len(remaining),
            failed=failed,
            awaiting_source=sum(operation["source_status"] == "prepared" for operation in remaining),
            limit_reached=limit_reached,
        )


__all__ = [
    "ThreadBranched",
    "ThreadDeleted",
    "ThreadLifecycleDispatcher",
    "ThreadLifecycleDispatchError",
    "ThreadLifecycleHandler",
    "ThreadLifecycleIntent",
    "ThreadLifecycleReplayReport",
]
