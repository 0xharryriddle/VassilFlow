# Superagent Orchestrator Runbook

## Objective

Coordinate a VassilFlow release-readiness review through one lead agent and three focused execution lanes.

## Lanes

- Lead: split the objective into traceable work packets.
- Skill routing: select `public:artifact-builder`, `custom:policy-review`, and `team:release-packager`.
- Runtime readiness: verify config, sandbox, memory, and artifact paths.
- Handoff: merge lane outputs into a concise release runbook.

## Policy Gates

- Filesystem writes stay under the active workspace.
- Shell and MCP tools require the configured sandbox boundary.
- Artifacts must be listed in the thread state before handoff.

## Completion Evidence

- Run metadata records selected skills and subagent lanes.
- `orchestrator-runbook.md` is attached as a workspace artifact.
- The final answer includes readiness state, open risks, and next actions.
