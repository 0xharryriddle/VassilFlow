"""Composition and bounded inspection for durable domain projection repair."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.gateway.domain_lifecycle import build_thread_lifecycle_dispatcher
from vassilflow.actions import (
    ActionRepairReport,
    ActionRepairService,
    FileActionStore,
)
from vassilflow.config.paths import Paths, get_paths
from vassilflow.runtime.lifecycle_journal import (
    FileThreadLifecycleJournal,
)
from vassilflow.runtime.thread_lifecycle import (
    ThreadLifecycleReplayReport,
)

_MAX_USER_SCOPES = 1_000
_DEFAULT_REPAIR_LIMIT = 500


class ProjectionRepairError(RuntimeError):
    """Raised when repair scope discovery or inspection is unsafe."""


@dataclass(frozen=True, slots=True)
class ProjectionRepairInspection:
    """Identity-free repair state for one user scope."""

    lifecycle_pending: int
    lifecycle_limit_reached: bool
    actions: ActionRepairReport


@dataclass(frozen=True, slots=True)
class ProjectionRepairResult:
    """Identity-free result for one user-scoped apply pass."""

    lifecycle: ThreadLifecycleReplayReport
    actions: ActionRepairReport


@dataclass(frozen=True, slots=True)
class ProjectionRepairHealthInspection:
    """Lightweight repair backlog state without domain reconciliation."""

    lifecycle_pending: int
    stale_actions: int
    active_actions: int
    limit_reached: bool


def discover_repair_user_ids(
    *,
    paths: Paths | None = None,
    user_id: str | None = None,
) -> tuple[str, ...]:
    """Resolve bounded user scopes without projecting identities into reports."""

    paths = paths or get_paths()
    if user_id is not None:
        paths.user_dir(user_id)
        return (user_id,)
    users_dir = paths.base_dir / "users"
    if not users_dir.exists():
        return ()
    if users_dir.is_symlink() or not users_dir.is_dir():
        raise ProjectionRepairError("User repair root is unsafe")
    user_ids: list[str] = []
    for entry in users_dir.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_symlink() or not entry.is_dir():
            raise ProjectionRepairError("User repair scope is unsafe")
        paths.user_dir(entry.name)
        user_ids.append(entry.name)
        if len(user_ids) > _MAX_USER_SCOPES:
            raise ProjectionRepairError("User repair scope exceeds the safety limit")
    return tuple(sorted(user_ids))


def _action_service(
    paths: Paths,
    user_id: str,
) -> ActionRepairService:
    return ActionRepairService(
        FileActionStore(
            paths.user_actions_dir(user_id),
            owner_user_id=user_id,
        ),
        (),
    )


def inspect_user_repairs(
    user_id: str,
    *,
    paths: Paths | None = None,
    stale_after: timedelta = timedelta(minutes=5),
    limit: int = _DEFAULT_REPAIR_LIMIT,
) -> ProjectionRepairInspection:
    """Inspect unresolved lifecycle projections and stale running Actions."""

    paths = paths or get_paths()
    lifecycle = FileThreadLifecycleJournal(
        paths.user_lifecycle_dir(user_id),
        owner_user_id=user_id,
    ).list(
        limit=10_000,
        unfinished_only=True,
        oldest_first=True,
    )
    actions = _action_service(paths, user_id).repair(
        stale_after=stale_after,
        limit=limit,
        apply=False,
    )
    return ProjectionRepairInspection(
        lifecycle_pending=len(lifecycle),
        lifecycle_limit_reached=len(lifecycle) > limit,
        actions=actions,
    )


def inspect_user_repair_health(
    user_id: str,
    *,
    paths: Paths | None = None,
    stale_after: timedelta = timedelta(minutes=5),
    limit: int = _DEFAULT_REPAIR_LIMIT,
    clock: Callable[[], datetime] | None = None,
) -> ProjectionRepairHealthInspection:
    """Read bounded journal/lease state without scanning domain repositories."""

    if stale_after < timedelta(0):
        raise ProjectionRepairError("Projection health stale threshold is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ProjectionRepairError("Projection health limit is invalid")
    paths = paths or get_paths()
    lifecycle = FileThreadLifecycleJournal(
        paths.user_lifecycle_dir(user_id),
        owner_user_id=user_id,
    ).list(
        limit=limit + 1,
        unfinished_only=True,
        oldest_first=True,
    )
    action_store = FileActionStore(
        paths.user_actions_dir(user_id),
        owner_user_id=user_id,
        clock=clock,
    )
    now = clock() if clock is not None else datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    actions = action_store.list(
        limit=limit + 1,
        status="running",
        started_before=now.astimezone(UTC) - stale_after,
        oldest_first=True,
    )
    active_actions = 0
    stale_actions = 0
    for action in actions[:limit]:
        state = action_store.inspect_reconciliation_state(action["action_id"])
        if state == "active":
            active_actions += 1
        elif state != "terminal":
            stale_actions += 1
    return ProjectionRepairHealthInspection(
        lifecycle_pending=min(len(lifecycle), limit),
        stale_actions=stale_actions,
        active_actions=active_actions,
        limit_reached=(len(lifecycle) > limit or len(actions) > limit),
    )


async def repair_user_projections(
    user_id: str,
    *,
    paths: Paths | None = None,
    stale_after: timedelta = timedelta(minutes=5),
    limit: int = _DEFAULT_REPAIR_LIMIT,
) -> ProjectionRepairResult:
    """Replay unfinished handlers and finalize evidence-backed Actions."""

    paths = paths or get_paths()
    dispatcher = build_thread_lifecycle_dispatcher(paths)
    lifecycle = await dispatcher.replay_user(
        user_id,
        limit=limit,
    )
    actions = _action_service(paths, user_id).repair(
        stale_after=stale_after,
        limit=limit,
        apply=True,
    )
    return ProjectionRepairResult(
        lifecycle=lifecycle,
        actions=actions,
    )


def aggregate_repair_inspection(
    inspections: tuple[ProjectionRepairInspection, ...],
) -> dict[str, int | bool]:
    """Combine scopes into a bounded health/CLI projection."""

    return {
        "user_scopes": len(inspections),
        "lifecycle_pending": sum(inspection.lifecycle_pending for inspection in inspections),
        "stale_actions": sum(inspection.actions.stale_running for inspection in inspections),
        "repairable_actions": sum(inspection.actions.repairable for inspection in inspections),
        "indeterminate_actions": sum(inspection.actions.indeterminate for inspection in inspections),
        "active_actions": sum(inspection.actions.deferred_active for inspection in inspections),
        "failed_checks": sum(inspection.actions.failed for inspection in inspections),
        "limit_reached": any(inspection.lifecycle_limit_reached or inspection.actions.limit_reached for inspection in inspections),
    }


def aggregate_repair_results(
    results: tuple[ProjectionRepairResult, ...],
) -> dict[str, int | bool]:
    """Combine apply results without exposing resource or owner identities."""

    return {
        "user_scopes": len(results),
        "lifecycle_scanned": sum(result.lifecycle.scanned for result in results),
        "lifecycle_repaired": sum(result.lifecycle.repaired for result in results),
        "lifecycle_pending": sum(result.lifecycle.still_pending for result in results),
        "actions_scanned": sum(result.actions.scanned for result in results),
        "actions_reconciled": sum(result.actions.reconciled for result in results),
        "actions_indeterminate": sum(result.actions.indeterminate for result in results),
        "failed": sum(result.lifecycle.failed + result.actions.failed for result in results),
        "limit_reached": any(result.lifecycle.limit_reached or result.actions.limit_reached for result in results),
    }


def aggregate_repair_health(
    inspections: tuple[ProjectionRepairHealthInspection, ...],
) -> dict[str, int | bool]:
    """Combine lightweight health state without canonical domain reads."""

    return {
        "user_scopes": len(inspections),
        "lifecycle_pending": sum(inspection.lifecycle_pending for inspection in inspections),
        "stale_actions": sum(inspection.stale_actions for inspection in inspections),
        "active_actions": sum(inspection.active_actions for inspection in inspections),
        "limit_reached": any(inspection.limit_reached for inspection in inspections),
    }


__all__ = [
    "ProjectionRepairError",
    "ProjectionRepairInspection",
    "ProjectionRepairHealthInspection",
    "ProjectionRepairResult",
    "aggregate_repair_inspection",
    "aggregate_repair_health",
    "aggregate_repair_results",
    "discover_repair_user_ids",
    "inspect_user_repairs",
    "inspect_user_repair_health",
    "repair_user_projections",
]
