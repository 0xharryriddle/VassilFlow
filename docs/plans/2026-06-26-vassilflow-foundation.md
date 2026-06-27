# VassilFlow Foundation Plan

## Context

VassilFlow starts from the current upstream-shaped repository as a working v0 foundation. The goal is not to rewrite the inherited runtime immediately. The goal is to preserve the runnable vertical slice, then add VassilFlow-owned boundaries around policy, ledger, sandbox, tool permission, memory, evaluation, and repair.

Primary research inputs:

- `research/Nghiên Cứu SuperAgent Harness.md`
- `research/reports/05-deerflow.md`
- `research/reports/15-vassilflow-blueprint.md`

## Architecture Decision

Use the upstream-derived runtime as the foundation runtime for v0.

```text
VassilFlow v0 = inherited runtime/gateway/sandbox/skills/frontend
             + VassilFlow boundary contracts
             + policy and ledger adapters
             + evaluation and memory gates
```

Do not start with broad package renames or internal rewrites. The repository still needs a clean baseline commit and smoke verification first.

## Non-Negotiable Boundaries

VassilFlow owns these product and safety boundaries even while the inherited runtime remains the implementation substrate:

- Session identity and ownership.
- Run lifecycle and completion evidence.
- Tool permission and policy decision flow.
- Sandbox provider contract and side-effect routing.
- Trace and ledger export.
- Memory write gate with provenance.
- Evaluation and verification contract.
- Approval workflow for high-risk actions.
- Harness repair workflow after trace and eval are stable.

## Phase 0 - Baseline And Architecture Lock

1. Commit the current upstream-derived snapshot as the VassilFlow foundation baseline.
2. Record the upstream source, branch, and commit hash in project docs.
3. Run the inherited foundation unchanged and document exact setup commands, env requirements, smoke commands, and known failures.
4. Keep runtime behavior untouched while adding VassilFlow docs and contracts.
5. Validate `contracts/vassilflow_boundary_contract.json` and use it as the shared vocabulary for backend, frontend, CLI, and tests.

Success criteria:

- Baseline state is reproducible.
- No runtime behavior changed during architecture lock.
- VassilFlow boundary names are explicit and reviewable.

## Phase 1 - Facade And Contracts

1. Add a VassilFlow facade module over existing gateway/run APIs.
2. Map inherited thread/run/sandbox state to VassilFlow `Session`, `Run`, `TraceStep`, `ToolSpec`, `PolicyDecision`, `ApprovalRequest`, and `CompletionEvidence`.
3. Add contract tests that load `contracts/vassilflow_boundary_contract.json`.
4. Export run ledger data without changing the current stream behavior.
5. Add policy adapter hooks around tool execution in audit-only mode.

Success criteria:

- One existing task path still works end to end.
- VassilFlow can export a stable run trace.
- Tool policy decisions are recorded even when they only allow.

## Phase 2 - Governance And Verification

1. Add allow/deny/ask policy enforcement for core tool tiers.
2. Add approval request persistence and resolution.
3. Add AgentShield-style egress integration in opt-in mode.
4. Add Superagent-style guard/redact/scan adapters in opt-in mode.
5. Add DeepEval-compatible trace export and one regression eval.

Success criteria:

- Risky actions can pause for approval.
- Network egress can be controlled outside the prompt.
- A run can be evaluated from trace evidence, not just final text.

## Phase 3 - Memory And Repair Readiness

1. Add memory write candidates with provenance and confidence.
2. Add project memory and run-summary memory surfaces.
3. Make trace schema HTIR-ready for later HarnessFix-style repair.
4. Add completion evidence gate before finalization.

Success criteria:

- Long-term memory writes are explicit and auditable.
- Completion requires evidence.
- Failed runs have enough trace structure for diagnosis.

## Immediate Engineering Order

1. Validate the current repo state and create a clean baseline commit.
2. Run backend smoke checks without modifying runtime code.
3. Add VassilFlow facade and contract tests.
4. Add audit-only policy decisions around tool calls.
5. Add ledger export for run trace steps.

Keep rebranding separate from behavior changes. Renaming packages, env vars, docs, and UI labels should happen in dedicated commits after the baseline is stable.
