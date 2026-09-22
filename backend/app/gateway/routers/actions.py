"""Read API for the current user's action and provenance records."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from vassilflow.actions import (
    ACTION_SCHEMA,
    ActionIntegrityError,
    ActionNotFoundError,
    ActionStoreError,
    FileActionStore,
)
from vassilflow.config.paths import get_paths
from vassilflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/actions", tags=["actions"])


class ActionReferenceResponse(BaseModel):
    kind: str
    id: str
    role: str | None = None


class ActionArtifactResponse(BaseModel):
    sha256: str
    size_bytes: int


class ActionErrorResponse(BaseModel):
    type: str
    message: str


class ActionResponse(BaseModel):
    schema_version: Literal["vassilflow.action.v1"] = Field(alias="schema")
    action_id: str
    owner_user_id: str
    operation: str
    source: Literal["agent_run", "user_api"]
    assistant_id: str | None
    thread_id: str | None
    run_id: str | None
    started_at: str
    completed_at: str | None
    status: Literal["running", "succeeded", "rejected", "failed", "partial"]
    references: list[ActionReferenceResponse]
    before_artifact: ActionArtifactResponse | None
    after_artifact: ActionArtifactResponse | None
    evidence: list[ActionReferenceResponse]
    error: ActionErrorResponse | None
    metadata: dict[str, Any]


class ActionsResponse(BaseModel):
    actions: list[ActionResponse]


def _store_for_user(user_id: str) -> FileActionStore:
    return FileActionStore(
        get_paths().user_actions_dir(user_id),
        owner_user_id=user_id,
    )


async def _run_action_io[T](operation: Any) -> T:
    try:
        return await asyncio.to_thread(operation)
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Action was not found.") from exc
    except ActionIntegrityError as exc:
        logger.error("Action provenance failed integrity checks", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="Action provenance failed integrity checks.",
        ) from exc
    except ActionStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=ActionsResponse)
async def list_actions(
    limit: int = Query(default=100, ge=1, le=500),
    operation: str | None = Query(default=None, max_length=128),
    resource_kind: str | None = Query(default=None, max_length=64),
    resource_id: str | None = Query(default=None, max_length=512),
) -> ActionsResponse:
    """List the current user's newest action records."""

    user_id = get_effective_user_id()

    def load() -> ActionsResponse:
        records = _store_for_user(user_id).list(
            limit=limit,
            operation=operation,
            resource_kind=resource_kind,
            resource_id=resource_id,
        )
        return ActionsResponse(actions=[ActionResponse.model_validate(item) for item in records])

    return await _run_action_io(load)


@router.get("/{action_id}", response_model=ActionResponse)
async def get_action(action_id: str) -> ActionResponse:
    """Resolve one action ID inside the current user's provenance journal."""

    user_id = get_effective_user_id()

    def load() -> ActionResponse:
        record = _store_for_user(user_id).get(action_id)
        if record["schema"] != ACTION_SCHEMA:
            raise ActionIntegrityError("Action projection schema is invalid")
        return ActionResponse.model_validate(record)

    return await _run_action_io(load)
