"""Stable VassilFlow boundary contracts.

These dataclasses mirror ``contracts/vassilflow_boundary_contract.json``. They
are intentionally implementation-neutral: the DeerFlow runtime can keep its
current internal schemas while new integrations depend on the VassilFlow names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

BOUNDARY_CONTRACT_VERSION = 1


class SessionStatus(StrEnum):
    created = "created"
    preparing_workspace = "preparing_workspace"
    sandbox_starting = "sandbox_starting"
    running = "running"
    waiting_approval = "waiting_approval"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    archived = "archived"


class RunStatus(StrEnum):
    pending = "pending"
    running = "running"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    rolled_back = "rolled_back"
    incomplete = "incomplete"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    denied = "denied"
    expired = "expired"
    cancelled = "cancelled"


class PolicyDecisionValue(StrEnum):
    allow = "allow"
    deny = "deny"
    ask = "ask"
    redact = "redact"
    sanitize = "sanitize"
    escalate = "escalate"


class RiskTier(StrEnum):
    tier_0 = "tier_0"
    tier_1 = "tier_1"
    tier_2 = "tier_2"
    tier_3 = "tier_3"
    tier_4 = "tier_4"


RISK_TIER_DESCRIPTIONS: dict[RiskTier, str] = {
    RiskTier.tier_0: "Read-only actions with no external side effect.",
    RiskTier.tier_1: "Sandbox-local file or command effects.",
    RiskTier.tier_2: "Network or API access with low sensitivity.",
    RiskTier.tier_3: "Credential use, external writes, package install, or repository mutation.",
    RiskTier.tier_4: "Production, financial, medical, security-critical, destructive, or irreversible actions.",
}


class EventType(StrEnum):
    session_created = "session.created"
    run_started = "run.started"
    plan_created = "plan.created"
    tool_requested = "tool.requested"
    policy_decided = "policy.decided"
    approval_requested = "approval.requested"
    approval_resolved = "approval.resolved"
    tool_started = "tool.started"
    tool_completed = "tool.completed"
    artifact_created = "artifact.created"
    memory_write_candidate = "memory.write_candidate"
    memory_write_committed = "memory.write_committed"
    verification_started = "verification.started"
    verification_completed = "verification.completed"
    run_completed = "run.completed"
    run_failed = "run.failed"


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    project_id: str
    owner_id: str
    status: SessionStatus | str
    created_at: str
    workspace_id: str | None = None
    sandbox_id: str | None = None
    thread_id: str | None = None
    policy_scope: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Run:
    run_id: str
    session_id: str
    status: RunStatus | str
    goal: str
    created_at: str
    thread_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    root_trace_id: str | None = None
    completion_evidence: CompletionEvidence | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TraceStep:
    step_id: str
    trace_id: str
    type: str
    actor: str
    status: str
    started_at: str
    parent_step_id: str | None = None
    request_ref: str | None = None
    response_ref: str | None = None
    tool_name: str | None = None
    tool_args_ref: str | None = None
    tool_result_ref: str | None = None
    artifact_effects: list[dict[str, Any]] = field(default_factory=list)
    state_effects: list[dict[str, Any]] = field(default_factory=list)
    policy_decisions: list[PolicyDecision] = field(default_factory=list)
    approvals: list[ApprovalRequest] = field(default_factory=list)
    cost: dict[str, Any] | None = None
    latency_ms: int | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    code_refs: list[str] = field(default_factory=list)
    ended_at: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    tool_id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    provider: str
    permission_tier: RiskTier | str
    side_effects: list[str]
    output_schema: dict[str, Any] | None = None
    network_access: bool | None = None
    filesystem_access: str | None = None
    secrets_required: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    timeout_seconds: int | None = None
    retry_policy: dict[str, Any] | None = None
    audit_level: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision_id: str
    decision: PolicyDecisionValue | str
    subject: str
    action: str
    resource: str
    risk_tier: RiskTier | str
    created_at: str
    rule_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
    reason: str | None = None
    redactions: list[dict[str, Any]] = field(default_factory=list)
    approval_request_id: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    approval_id: str
    session_id: str
    run_id: str
    status: ApprovalStatus | str
    requested_action: str
    risk_tier: RiskTier | str
    created_at: str
    tool_call_id: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    expected_side_effect: str | None = None
    resolved_by: str | None = None
    resolved_at: str | None = None
    resolution_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CompletionEvidence:
    task_goal: str
    plan_status: str
    verification_results: list[dict[str, Any]]
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    policy_exceptions: list[str] = field(default_factory=list)
    remaining_risks: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    human_approvals: list[str] = field(default_factory=list)


ENTITY_TYPES = {
    "Session": Session,
    "Run": Run,
    "TraceStep": TraceStep,
    "ToolSpec": ToolSpec,
    "PolicyDecision": PolicyDecision,
    "ApprovalRequest": ApprovalRequest,
    "CompletionEvidence": CompletionEvidence,
}

__all__ = [
    "ApprovalRequest",
    "ApprovalStatus",
    "BOUNDARY_CONTRACT_VERSION",
    "CompletionEvidence",
    "ENTITY_TYPES",
    "EventType",
    "PolicyDecision",
    "PolicyDecisionValue",
    "RISK_TIER_DESCRIPTIONS",
    "RiskTier",
    "Run",
    "RunStatus",
    "Session",
    "SessionStatus",
    "ToolSpec",
    "TraceStep",
]
