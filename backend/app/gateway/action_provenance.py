"""Gateway helpers for direct user actions that do not belong to an Agent run."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import HTTPException

from vassilflow.actions import ActionStatus, ActionStoreError, FileActionStore
from vassilflow.config.paths import get_paths

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UserActionHandle:
    """Identity and store for one direct API mutation."""

    action_id: str
    store: FileActionStore
    heartbeat_stop: asyncio.Event | None = None
    heartbeat_task: asyncio.Task[None] | None = None


_ACTION_HEARTBEAT_INTERVAL_SECONDS = 5 * 60
_ACTION_HEARTBEAT_LEASE = timedelta(minutes=30)


async def _heartbeat_action(
    store: FileActionStore,
    action_id: str,
    stop: asyncio.Event,
) -> None:
    while True:
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=_ACTION_HEARTBEAT_INTERVAL_SECONDS,
            )
            return
        except TimeoutError:
            try:
                await asyncio.to_thread(
                    store.renew,
                    action_id,
                    lease_duration=_ACTION_HEARTBEAT_LEASE,
                )
            except ActionStoreError:
                logger.error(
                    "Could not renew direct action lease",
                    exc_info=True,
                )


async def _stop_heartbeat(handle: UserActionHandle) -> None:
    if handle.heartbeat_stop is None or handle.heartbeat_task is None:
        return
    handle.heartbeat_stop.set()
    await handle.heartbeat_task


async def abandon_user_action(handle: UserActionHandle) -> None:
    """Stop lease renewal while preserving an unresolved running Action."""

    await _stop_heartbeat(handle)


def _store_for_user(user_id: str) -> FileActionStore:
    return FileActionStore(
        get_paths().user_actions_dir(user_id),
        owner_user_id=user_id,
    )


async def start_user_action(
    *,
    user_id: str,
    operation: str,
    references: list[dict[str, str]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> UserActionHandle:
    """Durably start one direct mutation before executing it."""

    def start() -> tuple[FileActionStore, dict[str, Any]]:
        store = _store_for_user(user_id)
        action = store.start(
            operation=operation,
            source="user_api",
            references=references,
            metadata=metadata,
        )
        return store, action

    try:
        store, action = await asyncio.to_thread(start)
    except ActionStoreError as exc:
        logger.error("Could not start direct action provenance", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Action provenance is currently unavailable.",
        ) from exc
    heartbeat_stop = asyncio.Event()
    return UserActionHandle(
        action_id=action["action_id"],
        store=store,
        heartbeat_stop=heartbeat_stop,
        heartbeat_task=asyncio.create_task(
            _heartbeat_action(
                store,
                action["action_id"],
                heartbeat_stop,
            )
        ),
    )


async def finish_user_action(
    handle: UserActionHandle,
    *,
    status: ActionStatus,
    references: list[dict[str, str]] | None = None,
    before_artifact: dict[str, Any] | None = None,
    after_artifact: dict[str, Any] | None = None,
    evidence: list[dict[str, str]] | None = None,
    error: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one terminal outcome for a direct mutation."""

    try:
        result = await asyncio.to_thread(
            handle.store.finish,
            handle.action_id,
            status=status,
            references=references,
            before_artifact=before_artifact,
            after_artifact=after_artifact,
            evidence=evidence,
            error=error,
            metadata=metadata,
        )
        return result
    except ActionStoreError as exc:
        logger.error(
            "Could not finalize direct action provenance %s",
            handle.action_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Action provenance could not be finalized; the operation may have completed.",
        ) from exc
    finally:
        await _stop_heartbeat(handle)


async def reject_user_action(
    handle: UserActionHandle,
    exc: HTTPException,
) -> None:
    """Best-effort terminal record for a direct mutation rejected by its domain."""

    detail = exc.detail if isinstance(exc.detail, str) else "The action was not completed."
    status: ActionStatus = "rejected" if 400 <= exc.status_code < 500 else "failed"
    try:
        await finish_user_action(
            handle,
            status=status,
            error={
                "type": "request_rejected" if status == "rejected" else "operation_failed",
                "message": detail,
            },
            metadata={"http_status": exc.status_code},
        )
    except HTTPException:
        logger.error(
            "Direct action %s remains running after outcome persistence failed",
            handle.action_id,
            exc_info=True,
        )


async def fail_user_action(handle: UserActionHandle) -> None:
    """Best-effort failed outcome for an unexpected direct mutation error."""

    try:
        await finish_user_action(
            handle,
            status="failed",
            error={
                "type": "operation_failed",
                "message": "The action failed unexpectedly.",
            },
        )
    except HTTPException:
        logger.error(
            "Direct action %s remains running after unexpected failure",
            handle.action_id,
            exc_info=True,
        )
