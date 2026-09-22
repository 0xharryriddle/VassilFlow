"""Domain-neutral repair contract for stale running Actions."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from .models import ACTION_TERMINAL_STATUSES, ActionStatus
from .store import FileActionStore

logger = logging.getLogger(__name__)

_RECONCILER_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_DETAIL_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")


class ActionReconciliationError(RuntimeError):
    """Base error for stale Action reconciliation."""


@dataclass(frozen=True, slots=True)
class ActionReconciliationDecision:
    """One domain verdict derived from canonical mutation evidence."""

    verdict: Literal["committed", "not_committed", "indeterminate"]
    detail_code: str
    status: ActionStatus | None = None
    references: tuple[Mapping[str, Any], ...] = ()
    before_artifact: Mapping[str, Any] | None = None
    after_artifact: Mapping[str, Any] | None = None
    evidence: tuple[Mapping[str, Any], ...] = ()
    error: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if _DETAIL_CODE_RE.fullmatch(self.detail_code) is None:
            raise ValueError("Action reconciliation detail code is invalid")
        if self.verdict == "indeterminate":
            if self.status is not None:
                raise ValueError("Indeterminate Action reconciliation cannot have an outcome")
            return
        if self.status not in ACTION_TERMINAL_STATUSES:
            raise ValueError("Resolved Action reconciliation requires a terminal outcome")
        if self.status in {"failed", "rejected", "partial"} and self.error is None:
            raise ValueError("Unsuccessful Action reconciliation requires an error")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("Successful Action reconciliation cannot have an error")


class ActionReconciler(Protocol):
    """Domain adapter that verifies one Action against canonical state."""

    key: str
    operations: frozenset[str]

    def reconcile(
        self,
        action: Mapping[str, Any],
    ) -> ActionReconciliationDecision:
        """Return a fail-closed verdict for one stale running Action."""


@dataclass(frozen=True, slots=True)
class ActionRepairReport:
    """Aggregate, identity-free result of one bounded repair pass."""

    scanned: int
    stale_running: int
    supported: int
    repairable: int
    reconciled: int
    indeterminate: int
    deferred_active: int
    failed: int
    limit_reached: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ActionRepairService:
    """Detect stale Actions and delegate evidence checks to their domains."""

    def __init__(
        self,
        store: FileActionStore,
        reconcilers: Sequence[ActionReconciler],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or _utc_now
        self._by_operation: dict[str, ActionReconciler] = {}
        seen_keys: set[str] = set()
        for reconciler in reconcilers:
            if _RECONCILER_KEY_RE.fullmatch(reconciler.key) is None:
                raise ValueError("Action reconciler key is invalid")
            if reconciler.key in seen_keys:
                raise ValueError(f"Action reconciler key {reconciler.key!r} is duplicated")
            seen_keys.add(reconciler.key)
            if not reconciler.operations:
                raise ValueError("Action reconciler must own at least one operation")
            for operation in reconciler.operations:
                if _OPERATION_RE.fullmatch(operation) is None:
                    raise ValueError("Action reconciler operation is invalid")
                if operation in self._by_operation:
                    raise ValueError(f"Action operation {operation!r} has multiple reconcilers")
                self._by_operation[operation] = reconciler

    def repair(
        self,
        *,
        stale_after: timedelta = timedelta(minutes=5),
        limit: int = 500,
        apply: bool = False,
    ) -> ActionRepairReport:
        """Plan or apply terminal outcomes backed by current canonical evidence."""

        if stale_after < timedelta(0):
            raise ActionReconciliationError("Action stale threshold is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ActionReconciliationError("Action repair limit is invalid")
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now.astimezone(UTC) - stale_after
        discovered = self._store.list(
            limit=10_000,
            status="running",
            started_before=cutoff,
            oldest_first=True,
        )
        actions = sorted(
            discovered,
            key=lambda action: action["operation"] not in self._by_operation,
        )[:limit]

        supported = 0
        repairable = 0
        reconciled = 0
        indeterminate = 0
        deferred_active = 0
        failed = 0
        for action in actions:
            reconciler = self._by_operation.get(action["operation"])
            if reconciler is None:
                indeterminate += 1
                continue
            supported += 1
            claim_id: str | None = None
            try:
                current = self._store.get(action["action_id"])
                if current["status"] != "running":
                    continue
                state = self._store.reconciliation_state(current["action_id"])
                if state in {"active", "claimed"}:
                    deferred_active += 1
                    continue
                if state == "terminal":
                    continue
                if apply:
                    claim_id = self._store.claim_reconciliation(current["action_id"])
                    if claim_id is None:
                        deferred_active += 1
                        continue
                    current = self._store.get(current["action_id"])
                    if current["status"] != "running":
                        self._store.release_reconciliation(
                            current["action_id"],
                            claim_id,
                        )
                        continue
                decision = reconciler.reconcile(current)
                if decision.verdict == "indeterminate":
                    indeterminate += 1
                    if claim_id is not None:
                        self._store.release_reconciliation(
                            current["action_id"],
                            claim_id,
                        )
                    continue
                repairable += 1
                if not apply:
                    continue
                if claim_id is None:
                    raise ActionReconciliationError("Action repair claim was not acquired")
                self._store.finish_reconciliation(
                    current["action_id"],
                    claim_id,
                    status=decision.status,
                    references=list(decision.references),
                    before_artifact=decision.before_artifact,
                    after_artifact=decision.after_artifact,
                    evidence=list(decision.evidence),
                    error=decision.error,
                    metadata={
                        **dict(decision.metadata or {}),
                        "reconciled": True,
                        "reconciliation_verdict": decision.verdict,
                        "reconciliation_detail": decision.detail_code,
                    },
                )
                reconciled += 1
            except Exception:
                if claim_id is not None:
                    try:
                        self._store.release_reconciliation(
                            action["action_id"],
                            claim_id,
                        )
                    except Exception:
                        logger.exception("Action repair claim could not be released")
                logger.exception("Action reconciliation failed inside a domain adapter")
                failed += 1

        return ActionRepairReport(
            scanned=len(actions),
            stale_running=len(actions),
            supported=supported,
            repairable=repairable,
            reconciled=reconciled,
            indeterminate=indeterminate,
            deferred_active=deferred_active,
            failed=failed,
            limit_reached=len(discovered) > limit,
        )


__all__ = [
    "ActionReconciler",
    "ActionReconciliationDecision",
    "ActionReconciliationError",
    "ActionRepairReport",
    "ActionRepairService",
]
