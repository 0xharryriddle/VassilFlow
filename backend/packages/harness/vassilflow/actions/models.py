"""Public constants and types for the action provenance contract."""

from __future__ import annotations

from typing import Literal

ACTION_SCHEMA = "vassilflow.action.v1"
ACTION_START_SCHEMA = "vassilflow.action.start.v1"
ACTION_OUTCOME_SCHEMA = "vassilflow.action.outcome.v1"
ACTION_LEASE_SCHEMA = "vassilflow.action.lease.v1"
ACTION_REPAIR_CLAIM_SCHEMA = "vassilflow.action.repair_claim.v1"

ActionStatus = Literal["running", "succeeded", "rejected", "failed", "partial"]
ActionSource = Literal["agent_run", "user_api"]

ACTION_STATUSES: frozenset[str] = frozenset({"running", "succeeded", "rejected", "failed", "partial"})
ACTION_TERMINAL_STATUSES: frozenset[str] = ACTION_STATUSES - {"running"}
ACTION_SOURCES: frozenset[str] = frozenset({"agent_run", "user_api"})
