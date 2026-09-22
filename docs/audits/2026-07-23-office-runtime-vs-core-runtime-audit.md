# VassilFlow Office Runtime Versus Core Runtime Audit

Date: 2026-07-23

Status: internal architecture audit

## Scope

This audit compares the implemented Office experience with the VassilFlow
runtime that existed immediately before Office was introduced. It answers a
narrow architectural question: is Office still a domain capability of the
existing super-agent harness, or has it accidentally become a second agent
runtime with incompatible lifecycle, persistence, and product contracts?

The comparison uses three source baselines:

| Baseline       | Commit                                                               | Meaning                                                                                   |
| -------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Core runtime   | `feb62dbab0a791735ff0751644b3fb878a22f7e1`                           | Agent runtime immediately before Office                                                   |
| Office engine  | `e91c578198f8d5b125550390dffdb4efe31e54b7`                           | Structured Office tools, package engine, renderer, and visual QA                          |
| Office product | `84317ec259d99375c770911d9ebfc7e2e042a78a` plus the current worktree | Agent contract, project/revision APIs, templates, project UI, and shared Agent chat shell |

The Office engine batch changed 70 files with 36,907 insertions. The Office
product batch changed 197 files with 41,049 insertions. That scale makes an
explicit runtime-boundary audit necessary even though the Office feature tests
are healthy.

The audit is based on direct source reads, including:

- `backend/app/gateway/services.py`
- `backend/app/gateway/routers/thread_runs.py`
- `backend/app/gateway/routers/threads.py`
- `backend/app/gateway/routers/office_projects.py`
- `backend/app/gateway/routers/office_templates.py`
- `backend/packages/harness/vassilflow/runtime/runs/worker.py`
- `backend/packages/harness/vassilflow/agents/lead_agent/agent.py`
- `backend/packages/harness/vassilflow/agents/middlewares/agent_policy_middleware.py`
- `backend/packages/harness/vassilflow/agents/data_policy.py`
- `backend/packages/harness/vassilflow/community/office/tools.py`
- `backend/packages/harness/vassilflow/community/office/revisions.py`
- `backend/packages/harness/vassilflow/community/office/templates.py`
- `backend/packages/harness/vassilflow/community/office/project_workflow.py`
- `frontend/src/components/workspace/chats/thread-chat-page.tsx`
- `frontend/src/components/workspace/agents/agent-chat-extension.tsx`
- `frontend/src/components/workspace/office/office-agent-chat-extension.tsx`
- `frontend/src/core/threads/types.ts`

## Executive Verdict

Office has **not** become a second LangGraph agent runtime. Office chat uses the
same run creation, `RunRecord`, stream bridge, journal, checkpointer,
`ThreadState`, model factory, tool loop, middleware composition, and SSE
protocol as the original lead Agent. The Office Agent is a policy-bound
specialization of the core graph, which is the correct direction.

Office has, however, introduced a separate and necessary **domain project
plane**:

- user-scoped projects and templates;
- immutable package revisions and semantic receipts;
- render evidence, reviews, and final selections;
- an isolated renderer service;
- project and template management APIs;
- a project-oriented UI in addition to chat.

That separation is appropriate. A durable Office project must not be reduced
to one chat thread or one mutable output file. The architectural problem is not
the existence of the project plane. The problem is that the bridge between the
core runtime and that plane is still Office-specific and incomplete.

The current system therefore has this shape:

> One shared Agent runtime, but two partially disconnected lifecycle,
> persistence, and audit planes.

Office V1 is functionally testable, but VassilFlow is not yet ready to repeat
the current integration pattern for ten more domain Agents. Doing so would add
domain imports, request fields, middleware, storage rules, and UI switches to
the core for every new Agent.

## Operational Trace

### Original Core Runtime

```text
Workspace chat
  -> POST thread run
  -> start_run()
  -> canonical thread + RunRecord
  -> run_agent()
  -> one LangGraph agent / ThreadState / checkpoint
  -> model selects a bounded tool
  -> tool reads or writes thread uploads/workspace/outputs
  -> RunJournal + SSE events
  -> Workspace Changes snapshots workspace/outputs
  -> run status + checkpoint + thread metadata
```

The original durable identity is the thread. Files are isolated under the
thread, runs are indexed by thread, checkpoints are indexed by thread, and
thread deletion removes the thread directory and checkpoint state.

### Office Through Chat

```text
Office Agent chat
  -> the same POST thread run
  -> the same start_run() and run_agent()
  -> the same LangGraph agent and ThreadState
  -> Agent policy filters tools
  -> optional Office selection is re-resolved from canonical bytes
  -> office_generate / office_edit / office_render
  -> trusted Office revision or render evidence is committed first
  -> artifact is materialized into the thread sandbox second
  -> the same RunJournal, SSE, checkpoint, and Workspace Changes flow
```

This path correctly reuses the core runtime. The intentional difference is
that the Office project revision is canonical and the thread file is a
materialized working copy.

### Office Through Project UI

```text
Office project or template page
  -> direct Office resource API
  -> OfficeProjectWorkflowService / OfficeTemplateStore
  -> filesystem project or template store
  -> optional isolated renderer
  -> immutable evidence, review, restore, final, or template record
  -> direct HTTP response
```

This path does not create a `RunRecord`, does not publish through the stream
bridge, does not write a generic run journal event, and is not represented by
Workspace Changes. That is acceptable for non-LLM management actions only if a
separate generic action/audit contract exists. It does not yet exist.

## Layer Comparison

| Layer                  | Core before Office                                       | Office now                                                         | Assessment                                             |
| ---------------------- | -------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------ |
| Agent graph            | One `create_agent` graph using `ThreadState`             | Same graph factory and state schema                                | Correct reuse                                          |
| Run lifecycle          | `RunRecord`, run manager, SSE, journal, checkpoint       | Same lifecycle for Office chat                                     | Correct reuse                                          |
| Agent identity         | Lead/custom Agent hints                                  | Canonical `assistant_id`, built-in Office identity                 | Improvement to core                                    |
| Tool policy            | Tool groups and skill filtering                          | Exact Agent allowlist plus execution-time middleware               | Improvement to core                                    |
| Data policy            | Thread uploads/workspace/outputs                         | Same scopes; Office IDs conservatively imply every thread scope    | Incomplete domain model                                |
| Trusted context        | Generic runtime context                                  | Office selection resolved by Gateway and injected request-only     | Secure behavior, domain-coupled integration            |
| Working files          | Thread-scoped mutable files                              | Same sandbox files remain available                                | Correct compatibility                                  |
| Canonical Office state | None                                                     | User-scoped immutable project revisions                            | Necessary specialization                               |
| Rendering              | Tool-local or external artifact behavior                 | Isolated, bounded renderer with source-bound evidence              | Necessary specialization                               |
| Project actions        | No project plane                                         | Direct render/review/restore/final/template APIs                   | Correct product need, missing common audit envelope    |
| Change evidence        | Thread Workspace Changes                                 | Workspace Changes plus separate Office semantic receipts           | Both are useful, but not linked                        |
| Deletion               | Delete thread files/checkpoints/metadata                 | Office projects survive and retain their original thread reference | Lifecycle gap                                          |
| Persistence evolution  | Configured stores and Alembic-managed application tables | Strict v1 JSON schemas in a local filesystem store                 | Deployment and migration gap                           |
| Availability           | Runtime dependencies resolved when used                  | Catalog checks tool imports, not live renderer readiness           | Readiness gap                                          |
| Frontend shell         | Generic chat page                                        | Shared `ThreadChatPage` plus Office extension and project pages    | Correct direction, extension still keyed by Agent name |

## What Correctly Follows The Core

### One Agent Runtime

`_make_lead_agent()` still creates one LangGraph agent with the same model
factory, `ThreadState`, checkpointer, store, and core middleware. The built-in
Office definition changes tools, skills, prompt identity, and policy; it does
not create a parallel graph implementation.

This should remain invariant. Office does not need a separate orchestration
engine merely because it has a project UI and domain storage.

### Canonical Agent Identity And Policy

The current Agent contract is stronger than the pre-Office runtime:

- the server normalizes `assistant_id`;
- a thread is bound to one canonical Agent identity;
- the model only sees policy-allowed tools;
- execution-time middleware rejects a disallowed tool even if a forged call
  reaches the tool node;
- MCP and ACP access fail closed unless explicitly allowed.

These are core improvements, not Office-only behavior, and should be retained
for every future Agent.

### Thread Sandbox Compatibility

Office tools continue to use `/mnt/user-data/uploads`, `workspace`, and
`outputs`. This keeps uploads immutable, preserves the existing file tools, and
lets the standard Workspace Changes recorder observe materialized files.

The project store should remain outside the sandbox. Mounting the whole Office
library into an Agent would weaken user/resource boundaries and make typed
project authorization ineffective.

### Fail-Closed Domain Operations

Office adds valid domain invariants that the generic file runtime cannot supply:

- exact package and relationship validation;
- typed selectors and operations;
- optimistic parent revision matching;
- source and result SHA-256 evidence;
- append-only revisions;
- exact object-selection re-resolution;
- hash-bound human approval;
- source-bound render evidence;
- explicit visual review and final selection.

These are appropriate domain services, not signs of a duplicate Agent runtime.

### Product Placement

The current product placement is sound:

- Office appears as a built-in Agent in the catalog;
- ordinary work still happens through the shared chat shell;
- durable projects, previews, revisions, reviews, and templates have a domain
  workspace;
- the current worktree removes Office logic from the Agent route body and puts
  it behind `AgentChatExtension`.

Chat alone cannot represent immutable revisions, render evidence, reusable
templates, or final selection. Conversely, the project UI should not replace
chat as the natural-language mutation surface.

## Findings

### F1 - High: Project Revisions Are Not Bound To Exact Runs Or Actions

The worker injects both `thread_id` and `run_id` into runtime context. Office
tools read and persist only `thread_id`. Revision provenance stores the thread,
source/output paths, and tool name, but no `run_id` or generic action ID.

Direct project actions such as render, review, restore, final selection,
template publication, and instantiation call Office services directly. The
Office routers do not use the run manager, run-event store, or workspace-change
recorder.

Consequences:

- a revision cannot be traced to the exact model run that created it;
- a run cannot reliably list the project revisions it committed;
- direct user actions and Agent tool actions have different audit models;
- partial commit states are visible in a tool response but not guaranteed to
  appear as a durable domain-operation event;
- future Activity and cross-Agent views cannot use one event contract.

The earlier scalable-Agent design explicitly required a run to point to its
Project, Conversation, Agent, and worker spans. That relationship is still
missing.

Required direction:

1. Add a generic immutable `ActionRecord` or domain-operation journal. It must
   support user actions without pretending that every click is an LLM run.
2. Record `action_id`, actor, Agent identity, project/resource identity,
   operation kind, status, timestamps, optional `thread_id` and `run_id`,
   before/after artifact identities, and evidence references.
3. Pass the current `run_id` into new Office commits and link the resulting
   project/revision IDs back to the run event stream.
4. Represent partial outcomes such as
   `revision_committed_output_failed` as first-class action status.

### F2 - High: Project And Thread Lifecycles Are Only Loosely Linked

Thread deletion removes the thread directory, checkpoints, and thread metadata.
It does not inspect Office projects. Office project metadata retains
`primary_thread_id` and, in the current worktree, the canonical primary thread
Agent identity.

The project artifact remains safe, which is preferable to cascading deletion,
but the reference can become stale. There is no detached/tombstoned link state,
conversation collection, or lifecycle test covering project survival after
thread deletion.

Restore exposes a related materialization ambiguity. The project workflow
appends a new canonical restore revision and carries forward an `output_path`,
but the direct restore API does not write those bytes back to the old thread
workspace. The project is current while the path named in provenance may still
contain an older artifact or may no longer exist.

Required direction:

1. Model Project-to-Conversation references explicitly instead of treating
   `primary_thread_id` as permanent ownership.
2. On thread deletion, detach or tombstone the reference while preserving the
   project and immutable evidence.
3. Distinguish revision provenance from materialization state. A requested or
   historical `output_path` must not imply that current revision bytes exist at
   that path.
4. Let restore either materialize into a selected live conversation explicitly,
   or remain project-only and report that state honestly.
5. Add lifecycle tests for delete, branch, restore, and reopen behavior.

### F3 - High: Office Persistence Has No Deployment Or Migration Abstraction

Core application persistence supports managed stores and Alembic migrations.
Office projects and templates are strict JSON/file layouts under:

```text
{runtime_home}/users/{user_id}/office/
```

The stores provide careful path validation, atomic replacement, append-only
directories, fsync, and process/file locking. Those are strong single-storage
invariants. They do not provide:

- a repository/provider interface;
- an explicit shared-storage or single-writer deployment contract;
- metadata migration between schema versions;
- project-level backup/export/restore tooling;
- transactional linkage with run/action metadata;
- a scalable index beyond bounded directory scans.

Strict equality checks for `vassilflow.office.project.v1`, revision v1, and
template v1 correctly fail closed, but there is no upgrade path when v2 is
needed.

Required direction:

1. Introduce repository interfaces before adding a second project-backed
   domain, while keeping binary artifacts separate from relational metadata.
2. Document current single-root/shared-volume assumptions immediately.
3. Add schema inventory and migration tooling before changing persisted Office
   schemas.
4. Do not perform a speculative database rewrite until project/action contracts
   and a second domain validate the abstraction.

### F4 - Medium: Office Domain Code Leaks Into Core Runtime Contracts

The shared runtime currently imports Office directly in several places:

- Gateway run services import Office selection models, stores, errors, and
  selectors;
- the generic `RunCreateRequest` has an `office_selection` field;
- the core lead-agent middleware chain always installs both Office selection
  middlewares, although they are inert without selection context;
- frontend thread types import Office types and expose
  `office_selection_request`;
- generic thread hooks accept an `officeSelection` option;
- the frontend extension registry maps the literal Agent name `office` to one
  implementation.

The current `AgentChatExtension` is a meaningful improvement because it keeps
the shared page from duplicating Office behavior. It is not yet a complete
capability contract. Repeating the current backend pattern for ten Agents would
turn core run services and middleware composition into a domain switchboard.

Required direction:

Introduce a server-owned capability adapter registry. A domain adapter should
be able to contribute:

- readiness requirements and probes;
- typed request-context validation;
- trusted context resolution;
- middleware factories attached only to the relevant Agent;
- domain resource/data capabilities;
- action-journal projection;
- a stable frontend extension key.

The core should know the generic envelope and adapter protocol, not Office
project IDs or PPTX object selectors. Frontend dynamic imports can remain
explicit for bundle safety, but should be selected by a server-owned extension
key rather than inferred from an Agent name.

### F5 - Medium: Catalog Availability Does Not Represent Runtime Readiness

`evaluate_builtin_agent()` checks whether required tool definitions are
configured, importable, correctly named, and inside the Agent tool groups. It
does not probe the renderer URL or its `/health` contract.

The Docker topology waits for the renderer at startup, but the catalog can
still advertise Office as available when:

- local development did not start the renderer;
- the renderer becomes unavailable after startup;
- the configured renderer URL is invalid or unreachable.

Rendering and complete visual QA are mandatory parts of the Office delivery
contract, so static tool presence is not enough.

Required direction:

- extend Agent availability with bounded cached dependency checks;
- distinguish `available`, `degraded`, and `unavailable`;
- expose machine-readable missing/degraded requirements;
- keep tool-level failure handling because readiness can change after a probe.

### F6 - Medium: Agent Data Policy Models Paths, Not Domain Resources

`AgentDataAccess` currently contains only thread upload, workspace, and output
scopes. When tool arguments contain `project_id`, `revision_id`, or
`parent_revision_id`, data policy conservatively treats them as references to
all thread scopes.

This fails closed for the current Office allowlist, but it does not express the
actual authority involved. An Office project and a published template are
user-scoped resources outside all three thread directories. Direct Office APIs
enforce user isolation through their selected store root, while Agent policy
has no first-class language for those resources.

Required direction:

- keep filesystem scopes for thread mounts;
- add typed resource capabilities such as project read/write, template read,
  and template publish;
- enforce resource capabilities in domain services and capability adapters;
- do not infer domain authorization by scanning opaque IDs as filesystem paths.

### F7 - Medium: Run Success And Office Operation Success Can Diverge

Office tools catch domain exceptions and return JSON with `ok: false`.
Committed-but-not-materialized outcomes are also returned in-band. The worker
marks a run successful when graph streaming completes without a provider or
runtime exception; it does not interpret Office result JSON.

This is useful for model self-repair and for returning recovery IDs after a
partial commit. It also means `RunStatus.success` does not prove every Office
operation succeeded, and Workspace Changes cannot prove the canonical project
commit because it scans only thread workspace and outputs.

Required direction:

- preserve recoverable structured tool results;
- emit normalized domain-operation events for success, rejection, failure, and
  partial commit;
- let run summaries expose warning/partial counts without making every
  recovered tool error fail the full conversational run;
- link semantic receipts and Workspace Changes instead of treating either as a
  complete substitute for the other.

### F8 - Low: Architecture Documentation Still Describes A Thread-Only System

`backend/docs/ARCHITECTURE.md` documents runs, threads, uploads, artifacts, and
thread deletion, but does not describe:

- the built-in Agent registry and policy enforcement;
- Office project/template routers;
- user-scoped Office persistence;
- the renderer sidecar;
- canonical revision versus thread materialization;
- direct project actions and their different lifecycle.

The feature-specific Office docs are detailed, but the top-level architecture
document no longer explains the whole system boundary.

## Classification

### Already Aligned - Keep

| Area                                                              | Decision                                                         |
| ----------------------------------------------------------------- | ---------------------------------------------------------------- |
| Shared LangGraph graph, run manager, checkpoint, journal, and SSE | Keep one runtime for lead, personal, and built-in domain Agents. |
| Canonical Agent identity                                          | Keep server ownership of `assistant_id` and thread binding.      |
| Exact tool allowlist and execution-time enforcement               | Keep as the common Agent contract.                               |
| Thread sandbox for uploads and working files                      | Keep; do not mount complete project libraries into the sandbox.  |
| Immutable Office revisions and source-bound evidence              | Keep as Office domain invariants.                                |
| Renderer isolation and bounded validation                         | Keep as a domain dependency.                                     |
| Office project workspace plus shared chat shell                   | Keep the current product placement.                              |
| `AgentChatExtension` extraction in the current worktree           | Keep the extension boundary and generalize its selection key.    |

### Needs Improvement

| Area                     | Required change                                                              |
| ------------------------ | ---------------------------------------------------------------------------- |
| Run/project provenance   | Add exact run/action linkage and domain-operation events.                    |
| Project/thread lifecycle | Add explicit conversation links, detach behavior, and materialization state. |
| Office persistence       | Add repository, deployment, backup, index, and migration contracts.          |
| Core/domain boundary     | Replace direct Office imports in core with capability adapters.              |
| Agent readiness          | Include operational dependency health and degraded status.                   |
| Data policy              | Add domain resource capabilities alongside thread path scopes.               |
| Observability            | Separate conversational run success from domain-operation outcomes.          |
| Architecture docs        | Document the actual two-plane system and its invariants.                     |

### Not Appropriate

| Proposal                                                          | Reason                                                                                        |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Make Office a separate LangGraph runtime                          | Duplicates run, stream, checkpoint, memory, and policy behavior without adding domain safety. |
| Store the complete Office project in thread checkpoints           | Couples durable project history to one conversation and inflates checkpoint state.            |
| Treat a thread output file as the project source of truth         | Loses immutable revision, receipt, review, and final-selection guarantees.                    |
| Put all direct project actions through an LLM run                 | User management actions need audit records, not fabricated model runs.                        |
| Split Word, Excel, and PowerPoint into separate Agents            | Fragments one coherent Office capability and multiplies product/runtime contracts.            |
| Generalize Office selectors into raw XML or a browser scene graph | Bypasses package-preserving typed operations and native corpus evidence.                      |

### Defer

| Area                                                 | Defer condition                                                                       |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------- |
| One universal project schema for every Agent         | Wait for a second project-backed domain to identify genuinely shared fields.          |
| Full Office metadata migration to SQL/object storage | First define repository, action, and lifecycle contracts; preserve current artifacts. |
| Organization template governance                     | Wait for organization identity, membership, roles, and authorization.                 |
| Scheduled or event-driven Office workflows           | Wait for generic Activity, action audit, idempotency, and scheduler contracts.        |
| Cross-Agent project delegation                       | Wait for project/run linkage and server-validated capability context.                 |

## Target Boundary

The desired architecture is not one giant project runtime. It is a stable core
runtime plus optional domain adapters and domain repositories:

```text
Core Agent Runtime
  Agent identity
  Run / thread / checkpoint / SSE
  Tool and data policy
  Generic trusted-context envelope
  Generic action journal
          |
          v
Domain Capability Adapter
  Readiness
  Typed context resolver
  Middleware contribution
  Resource capabilities
  Product extension key
          |
          v
Office Domain Plane
  Project repository
  Revision and template repository
  Package engine
  Renderer
  Review/final/materialization services
```

Important invariants:

1. A domain Agent may specialize the shared graph but may not replace run,
   thread, checkpoint, or stream semantics.
2. A project may outlive any conversation.
3. Every mutation has one action identity; an action may optionally belong to
   an Agent run.
4. Canonical project artifacts and thread materializations are distinct and
   explicitly linked.
5. Core packages depend on adapter interfaces, not domain implementations.
6. Domain repositories enforce authenticated resource access independently of
   model/tool policy.
7. Catalog status reflects both configured capability and operational
   readiness.

## Recommended Batches

### OR1 - Action And Provenance Contract

Implement first because it closes the largest audit gap without changing the
Office package engine:

- define a generic action record and statuses;
- attach `run_id` to Agent-originated Office actions;
- create action records for direct render/review/restore/final/template actions;
- include project/revision/action references in run events;
- test success, rejection, partial materialization, and direct user actions.

#### OR1 Implementation Checkpoint

Implemented on 2026-07-23 with these boundaries:

- `vassilflow.action.v1` is the generic public projection. Its terminal states
  are `succeeded`, `rejected`, `failed`, and `partial`; an action with only its
  immutable start record projects as `running`.
- The current repository implementation is a synchronous, user-scoped,
  append-only file store under the runtime user directory. `started.json` and
  `outcome.json` are separately immutable, bounded, integrity-checked records.
  This deliberately avoids introducing async database access inside Agent tool
  worker threads. A repository migration remains part of OR4.
- `GET /api/actions` and `GET /api/actions/{action_id}` resolve only the current
  user's records. Filtering is available by operation or exact resource
  identity.
- Agent-originated `office.generate`, `office.edit`, and `office.render`
  actions require canonical Assistant, thread, and run identity. Their terminal
  projections are linked into the exact run as `domain.action` events.
- Direct Project and Template mutations use `source=user_api` and never create
  a synthetic run. Render, review, restore, final selection, template import,
  slot update, template render/review/publish, and instantiation all return an
  action ID.
- Revision and render evidence provenance carries the action ID. Agent
  mutations additionally carry the exact run ID and Assistant identity.
  Direct restore and template instantiation revisions carry an action ID with
  no fabricated run identity.
- A committed revision or render evidence followed by materialization failure
  is recorded as `partial`, preserving the committed resource references and a
  bounded error. Domain rejections are distinct from infrastructure failures.
- Frontend core types expose Office action IDs and a generic read client for the
  Action API. OR1 does not add an activity-feed UI; that remains a product
  decision built on the now-resolvable contract.

Verification at this checkpoint:

- backend full suite: 6,207 passed and 52 skipped;
- OR1-focused backend suite after final integrity tightening: 169 passed and
  one platform-dependent symlink test skipped;
- frontend lint/typecheck: passed;
- frontend unit suite: 482 passed.

OR1 intentionally does not change Office package edit semantics, move Office
projects into thread checkpoints, or make the action store the source of truth
for project artifacts.

### OR2 - Lifecycle And Materialization

- define Project-to-Conversation references;
- detach links on thread deletion without deleting projects;
- model canonical, materialized, missing, and stale artifact states;
- make direct restore materialization behavior explicit;
- test thread deletion, branch, restore, reopen, and download.

#### OR2 Implementation Checkpoint

Implemented on 2026-07-23 with these boundaries:

- The core runtime now publishes domain-neutral `ThreadDeleted` and
  `ThreadBranched` notifications through a small lifecycle dispatcher. Office
  is registered only at the Gateway composition root; the generic thread
  router does not import Office.
- Office projects persist explicit, user-scoped conversation links with
  `origin`, `continuation`, or `branch` kind and `attached` or `detached`
  status. The former `primary_thread_id` fields remain a compatibility
  projection, not the lifecycle source of truth.
- Projects written before OR2 remain readable. When lifecycle fields are
  absent, the store derives one deterministic origin link from the legacy
  primary thread fields without rewriting immutable revision evidence.
- Thread deletion tombstones matching conversation links before thread
  metadata is removed. Canonical project artifacts, revision history, render
  evidence, reviews, final selections, and downloads remain available.
  Lifecycle failure is fail-visible and leaves thread metadata available for a
  retry.
- A latest-turn branch projects the attached Office link and the latest
  materialization observations only when thread user data was actually copied.
  Historical branches do not claim to contain working files that were not
  cloned.
- Agent generation and edit tools append a materialization observation only
  after output bytes have been replaced successfully. A committed revision
  followed by output failure records a `missing` observation and remains a
  partial Action outcome.
- Project detail resolves current working-copy state against actual
  Gateway-visible bytes. `materialized` means a verified copy equals the
  canonical artifact, `stale` means an existing or recorded copy represents
  different bytes, `missing` means the expected copy is absent, failed, or
  detached, and `canonical` means no working-copy observation exists. Recent
  project lists use the recorded state to avoid hashing every file; detail
  performs verification.
- Direct restore is explicitly `project_only`. It appends a new canonical
  restore revision and never overwrites an existing conversation file. A prior
  live copy is consequently reported as stale until an Agent action
  materializes the new revision.
- The Office Project API exposes bounded conversation and materialization
  projections but does not expose host or sandbox virtual paths. The project
  UI follows a currently attached conversation only, hides Continue in chat
  after detach, and keeps preview and download available.
- Lifecycle metadata fails closed on malformed links, orphan materialization
  provenance, or materializations without a conversation link.

Verification at this checkpoint:

- backend full suite: 6,214 passed and 52 skipped;
- OR2-focused backend suite: 121 passed after lifecycle and compatibility
  coverage was added;
- lifecycle integrity subset after final state-precedence tightening:
  21 passed;
- frontend lint/typecheck: passed;
- frontend unit suite: 482 passed;
- Office browser suite: 8 passed, including detach/reopen/download and
  project-only restore behavior.

Residual risks intentionally left for later batches:

- thread delete and branch handlers currently scan the user's file-backed
  project directory. An indexed repository belongs in OR4 before project
  volume grows materially;
- branch creation is already durable when domain projection runs, so projection
  failure is logged and does not roll back the branch. A repair queue or
  indexed reconciliation pass should accompany the future repository;
- OR2 does not add a direct restore-to-conversation command. Re-materialization
  remains an explicit Agent edit/generation workflow rather than an implicit
  side effect of restore.

### OR3 - Capability Adapter Boundary

- move Office selection resolution out of generic run services;
- attach Office middleware only through the Office capability adapter;
- replace Office-specific thread request fields with a discriminated trusted
  capability-input envelope;
- add a server-owned frontend extension key;
- enforce import-boundary tests that prevent new domain imports in core.

#### OR3 Implementation Checkpoint

Implemented on 2026-07-29 with these boundaries:

- Run requests now use the bounded
  `vassilflow.capability_input.v1` envelope, discriminated by capability and
  input kind. Direct REST and SDK-context forms converge on one parser, reject
  conflicting or duplicate inputs, and cap each run at eight inputs.
- The Gateway strips every client-provided `capability_inputs` copy before
  rebuilding runtime context. The selected built-in Agent's server-owned
  adapter resolves each optimistic payload against canonical, user-scoped
  resources before a run record is created.
- Generic Gateway run services, thread-run request models, the embedded client,
  and the lead-agent package no longer import Office modules. Adapter loading is
  reflective from immutable built-in Agent definitions.
- The Office adapter owns PPTX selection payload validation, current-revision
  checks, canonical object resolution, domain-to-capability error mapping, and
  construction of selection-context and approval middleware. Those middlewares
  are installed only for the Office Agent.
- Runtime middleware and Office tools read only the strict trusted envelope.
  Legacy Office-specific request/context keys have no compatibility fallback.
- Agent catalog metadata now exposes an optional `chat_extension` key. The
  generic Agent route dispatches its extension by that server-owned key rather
  than by Agent name; the Office extension alone creates the Office selection
  envelope.
- AST import-boundary tests prevent static Office imports in generic run
  services, the embedded client, and the Agent package, and assert that
  Office-owned middleware no longer resides in the generic middleware package.

Verification at this checkpoint:

- backend full suite: 6,216 passed and 52 skipped;
- OR3-focused backend suite: 150 passed;
- backend Ruff checks for all touched OR3 modules and tests: passed;
- frontend lint/typecheck: passed;
- frontend unit suite: 483 passed;
- Office browser suite on a dedicated production-build port: 8 passed.

Residual risks intentionally left for later batches:

- capability adapters are currently declared only by immutable built-in Agents;
  there is no user-authored adapter loading surface;
- adapter instances are process-local and resolution is synchronous work
  offloaded from the event loop; durable adapter readiness and repository
  health belong in OR4;
- the frontend registry still requires a reviewed local component for each
  extension key. Catalog metadata selects an extension but cannot load arbitrary
  remote code.

### OR4 - Readiness And Persistence Hardening

- expose renderer readiness and degraded catalog state;
- document current storage deployment assumptions;
- add repository interfaces and schema inventory/migration commands;
- validate the repository contract with a second project-backed domain before
  choosing a broad database schema.

#### OR4 Implementation Checkpoint

Implemented on 2026-07-29 with these boundaries:

- Capability adapters now own bounded, non-mutating readiness checks and
  project-repository contributions. Check keys are adapter-owned, validated,
  deduplicated, offloaded from the event loop, deadline-bounded, single-flight,
  cached for 15 seconds, and projected without URLs, filesystem paths, user
  IDs, or exception text. Probe failures and timeouts use bounded public
  fallbacks. Adapter objects are instantiated per resolution rather than shared
  across requests.
  Global dependency probes are shared across users while user-scoped storage
  checks remain isolated, preventing renderer probe amplification without
  weakening repository isolation. Independent built-in Agent checks run
  concurrently in catalog and health requests, avoiding linear cold-probe
  latency as the catalog grows.
- The Office adapter probes the real renderer `/health` contract, including
  renderer identity, pipeline contract version, and pipeline fingerprint. Those
  values are validated internally; public health metadata does not expose a
  renderer version or fingerprint. Renderer failure is optional and makes
  Office `degraded`; project, template, or Action-journal storage failure is
  required and makes Office `unavailable`.
- Agent product metadata and the frontend now distinguish `available`,
  `degraded`, and `unavailable`. Degraded Agents remain launchable and pinned,
  while Agent cards, profiles, chat welcome, and the Office workspace expose
  the limited state. The shared chat shell disables submit, regeneration, and
  clarification callbacks for unavailable Agents. The Gateway enforces the
  canonical built-in Agent product contract before creating a run record and
  returns a sanitized `agent_unavailable` HTTP `503` for a missing required
  dependency. Optional renderer failure remains launchable. Every operation
  retains its own checks because readiness evidence can become stale.
- `GET /health` remains a compatible liveness endpoint.
  `GET /health/ready` adds the versioned
  `vassilflow.health.readiness.v1` contract for runtime initialization,
  application database connectivity/durability, built-in tool requirements,
  and capability checks. It returns `503` only when core Gateway readiness is
  `not_ready`; an unavailable optional Agent dependency reports `degraded`.
- The operational repository interface deliberately covers readiness, bounded
  schema inventory, explicit migration planning, and exact migration apply.
  It does not introduce generic project CRUD or move binary artifacts into SQL.
  Adapter repository contributions are deduplicated by adapter identity before
  repository-key validation, so one shared adapter can support multiple Agents.
- One shared user-scoped JSON scanner now inventories the Action journal,
  Office Projects, and Office Template Library. It does not follow symlinks,
  rejects Windows junctions in every traversed component and hard-linked
  records, records directory traversal failures, caps user roots, all
  filesystem entries, record counts, and record bytes, and validates file
  identity around descriptor-anchored reads. It aggregates path-free issues and
  blocks unknown schemas with no registered migration.
- `make repository-inventory`, `make repository-migration-plan`, and
  `make repository-migrate` expose the operator workflow. The direct script
  supports an optional user scope but never echoes that identity. Applying a
  migration requires the explicit apply command; no current v1 store has a
  speculative migration. The registry rejects duplicate, stale, altered,
  cross-kind, overlapping, or incomplete plans and requires exact result
  counts. Repository descriptors declare `maintenance_window` or
  `transactional` migration safety; multi-writer repositories must be
  transactional. Apply commands re-inventory storage and fail unless every
  repository is current.
- The final live inventory found all Action and Office project records on their
  declared v1 schemas, no template records, and no pending migrations. A no-op
  apply completed with identical current post-inventories.
- The repository registry is validated against a second, non-Office
  database-shaped project implementation in tests. That contract test performs
  a real v1-to-v2 plan/apply cycle with a different record kind and deployment
  mode, proving the manager does not depend on Office IDs or filesystem fields.
  It is a contract fixture, not a shipped Research product.
- `docs/PERSISTENCE.md` documents the actual SQL/file storage split,
  `VASSILFLOW_HOME` durability, single-writer deployment, consistent backup
  window, health semantics, and migration commands.

Verification at this checkpoint:

- OR4-focused backend suite: 208 passed and two platform-dependent directory
  link tests skipped;
- backend full suite: 6,257 passed and 54 skipped;
- backend Ruff lint and format checks for the OR4 modules and tests: passed;
- frontend lint/typecheck: passed;
- frontend unit suite: 484 passed;
- combined Agent and Office browser suite on a production build: 22 passed,
  including unavailable and degraded readiness, disabled existing-thread
  actions, project evidence, approval/restore, and mobile preview behavior;
- live Gateway smoke test: liveness returned healthy, readiness returned
  `degraded` only because the renderer was unavailable, and the application
  database plus all three domain repositories remained ready.

Residual risks intentionally left explicit:

- readiness evidence is process-local and can be up to 15 seconds old; every
  operation must retain its own dependency and integrity checks;
- a timed-out synchronous dependency probe cannot be forcibly terminated; its
  late result is ignored, while the bounded single-flight fallback prevents
  request amplification during the cache window;
- Office and Action metadata remain single-writer filesystem repositories with
  bounded directory scans and no transactional commit with SQL run metadata;
- the registry cannot roll back a completed migration across multiple storage
  systems as one global transaction, so file-backed apply requires a backup,
  quiesced writers, and a maintenance window;
- descriptor-anchored reads and pre/post directory identity checks narrow
  concurrent path replacement, but cross-platform path APIs cannot eliminate a
  malicious local ancestor swap at every instant; the current contract assumes
  a trusted host and single writer;
- filesystem readiness is a non-mutating preflight and cannot guarantee a
  future ACL write will succeed;
- no persisted v1 schema currently needs migration, so production migration
  apply remains exercised by the generic second-domain contract rather than a
  fabricated Office v2;
- two directory-link tests are skipped on this Windows host because link
  creation is not permitted; junction rejection is implemented and hard-link
  rejection is exercised;
- a second production project-backed domain is still required before selecting
  a broad relational project schema or multi-writer artifact architecture.

### OR5 - Architecture Documentation

Update the top-level architecture after OR1 through OR4 so it documents stable
contracts rather than immediately becoming stale again.

#### OR5 Implementation Checkpoint

Implemented on 2026-07-29:

- `backend/docs/ARCHITECTURE.md` is now the canonical backend architecture
  contract. It uses stable ownership and dependency boundaries instead of a
  volatile middleware/route inventory and documents the deployed topology,
  harness-to-app dependency direction, composition roots, two-plane state
  model, authority rules, request flows, frontend extension levels, storage
  ownership, and operational constraints.
- The extension decision table distinguishes a Skill, tool/MCP integration,
  personal Agent, built-in chat Agent, and project-backed Agent. The ten-step
  project-Agent sequence now covers canonical identity, runtime policy, tools,
  capability adapters, repositories, Action provenance, lifecycle projection,
  authenticated routers, shared-shell UI extension, and cross-layer tests.
- Top-level and backend documentation indexes now point to the canonical
  architecture and the persistence/readiness contract rather than treating
  developer notes as the public architecture source.
- Executable import-boundary coverage now scans the generic Agent, Action,
  capability, persistence, and runtime packages for concrete Office imports.
  The Gateway lifecycle module is tested explicitly as a composition root, and
  the duplicated harness-boundary scan root was removed.
- Existing-thread Agent identity is now checked immediately after ownership and
  before capability resolution, readiness probes, Agent factory resolution, or
  checkpoint lookup. Legacy identity compatibility is validated without
  mutating at this early stage, then upgraded only inside the existing locked
  thread-binding path.
- `ThreadLifecycleDispatcher` now attempts every registered idempotent handler
  and raises one aggregate dispatch error after fan-out. One failing domain can
  no longer prevent later domains from observing delete or branch events.
- A checked-in frontend Agent-extension manifest is validated against the local
  component registry at runtime. Backend contract coverage requires every
  built-in `chat_extension` key to be present in that manifest, while frontend
  unit coverage distinguishes registered, unknown, and absent keys.
- The architecture wording was tightened after direct source review: the
  harness, not the Gateway, derives runtime policy during graph construction;
  readiness bounds the caller wait rather than terminating a synchronous
  worker; canonical domain state and receipts remain mutation authority; Action
  outcomes are linked provenance and can lag a committed mutation.

Verification at this checkpoint:

- OR5-focused backend suite: 91 passed;
- backend full suite: 6,264 passed and 54 skipped;
- backend Ruff lint and format checks for all OR5 modules and tests: passed;
- frontend lint/typecheck: passed;
- frontend unit suite: 485 passed;
- canonical documentation and local-link checks: passed.

Residual risks intentionally left explicit:

- lifecycle projection still has no durable outbox, retry cursor, or automatic
  reconciliation command. Delete failure leaves thread metadata for retry after
  files/checkpoints may already be gone; branch projection failure is logged
  after the branch is durable;
- one domain lifecycle handler can partially update multiple resources before
  failing. Handlers must remain idempotent until durable operation journaling
  and per-resource retry state exist;
- Action terminal persistence is not atomic with a domain commit. A failed
  outcome write can leave a valid domain mutation with an Action still
  projected as `running`; there is no stale-Action repair command yet;
- a timed-out synchronous readiness probe continues in its worker thread.
  Repeated permanently hung adapter probes can consume executor capacity even
  though callers receive bounded fallback responses;
- curated built-ins currently have no explicit MCP/ACP opt-in fields. They
  remain denied under their restricted policy; add fields only when a reviewed
  built-in use case requires them.

#### Next Recommended Batch

The next stability batch should introduce a durable projection-repair contract:

1. journal lifecycle operations before projection with idempotency keys and
   per-handler status;
2. replay failed delete/branch projections without repeating completed handler
   work;
3. detect stale `running` Actions and reconcile them against canonical domain
   state and receipts;
4. expose bounded aggregate repair health without leaking resource identities;
5. test process interruption, partial multi-resource projection, repeated
   retries, and operator repair commands.

### OR6 - Durable Projection Repair

Implemented on 2026-07-29:

- `vassilflow.runtime.lifecycle_journal` now persists deterministic,
  user-scoped source intents before the core thread mutation. Immutable
  `source_committed` and `source_aborted` markers separate source truth from
  projection status. Only committed events enter fan-out; an interrupted
  prepared intent remains visible and is never guessed into a commit.
- Every stable handler key owns immutable attempt start/outcome records.
  Repeated dispatch and operator replay skip completed handlers, retry failed
  handlers, reclaim only stale interrupted attempts, and report pagination
  rather than treating a full page as a clean backlog.
- `ThreadLifecycleDispatcher.replay_user` replays unfinished delete and branch
  projections without repeating completed domains. Coverage includes failure
  fan-out, process interruption, repeated retry, and an idempotent handler that
  stops after its first of two resources. Branch events carry their durable
  source-commit time, so a delayed Office projection can prove that the source
  conversation was attached when the branch happened even if a later delete
  detached it before replay.
- `vassilflow.actions.ActionRepairService` scans only bounded stale `running`
  Actions whose renewable worker lease has expired. Apply acquires one atomic,
  short-lived repair claim before canonical reconciliation; normal completion
  and repair completion share the Action store lock. Gateway direct mutations
  and Agent-facing Office tools heartbeat their leases while running.
- Reconciliation delegates each operation to exactly one domain reconciler and
  appends an outcome only for a `committed` or `not_committed` verdict backed by
  canonical evidence. Unsupported, missing, legacy, or ambiguous evidence
  remains `indeterminate`.
- The Office reconciler reads actual revision, materialization, render, review,
  final-selection, and template-version records. New template mutations persist
  typed Action receipts inside their canonical version update. At this
  checkpoint, final selection added its marker after updating the project
  pointer; OR7 below replaces that ordering to close the remaining crash gap.
- `make projection-repair-status`, `make projection-repair-plan`, and
  `make projection-repair` expose read-only inspection, planning, and explicit
  apply. Reports contain aggregate counts only and never echo user or resource
  identities. `GET /health/ready` uses a short deadline and reads only lifecycle
  backlog and Action lease state; it does not scan Office canonical evidence.
- Action leases/claims, lifecycle source/attempt markers, and final-selection
  commit markers are registered in operational repository inventory. Template
  Action receipts retain a bounded recent window instead of blocking future
  template mutations when the window is full.

Verification at this checkpoint:

- focused durability suite: 46 passed and 3 skipped;
- backend full suite: 6,278 passed and 54 skipped;
- backend Ruff lint and format checks for OR6-owned modules and tests: passed;
- frontend lint and typecheck: passed;
- frontend unit suite: 485 passed;
- live projection-repair inspection: six user scopes, no unresolved work, no
  identities in output;
- live repository inventory: all four registered repositories `current`.

Residual risks intentionally retained at this checkpoint:

- source intent, core thread state, and source outcome are separate durable
  writes. The previously unrecorded gap is closed, but a crash can leave a
  prepared intent that still requires source-state diagnosis;
- retry state is per handler, not per domain resource. A handler that updates
  several resources must remain idempotent and can repeat its own completed
  substeps after interruption;
- lifecycle handler-attempt leases do not yet heartbeat. Operators should not
  run repair concurrently with a known long-running lifecycle handler;
- stale Action repair deliberately leaves old template mutations,
  workspace-only render Actions, rejected pre-commit operations, and any
  ambiguous evidence `indeterminate`;
- template versions retain the latest 1,000 Action receipts. An unusually old
  stale Action whose receipt aged out remains `indeterminate`;
- readiness scans at most ten user scopes under a 1.5-second caller deadline
  and reports a limit when more exist. The operator CLI performs the broader
  bounded canonical pass.

### Post-OR6 Classification

This classification comes from direct comparison of the Action, lifecycle,
Office revision/template, router, and repair implementations after OR6.

| Classification                  | Finding                                                                                   | Decision                                                                                         |
| ------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Already in VassilFlow           | Two-phase lifecycle source intent, per-handler retry, Action leases/claims, exact evidence | Keep these as the base contract; do not add another queue, runtime, or Office-specific journal. |
| Implement in OR7                | Long handler lease ownership, direct API commit handoff, final-selection crash ordering    | Add attempt heartbeat and generation fencing; finish Actions from typed domain commits.         |
| Not appropriate for VassilFlow  | Infer source or mutation outcome from current file presence                                | Never force a terminal state without an exact source marker, Action receipt, or canonical link. |
| Defer until evidence is mature  | Per-resource lifecycle cursors, prepared-source diagnosis, unbounded receipt retention      | Keep operator-visible and bounded; design only with a proven second domain or production need.   |

### OR7 - Canonical Commit Handoff And Lease Fencing

Implemented on 2026-07-30:

- Lifecycle handler attempts now own a renewable `lease.json` with a monotonic
  generation. The dispatcher heartbeats long-running work, replay can reclaim
  only an expired generation, and the displaced worker is fenced from renewal
  or terminal outcome writes.
- Direct Office project and template mutations now return typed domain commits.
  Routers finalize the Action from those canonical facts before performing
  optional response readback, so a response-projection error cannot relabel a
  committed mutation as `failed`.
- A mutation exception with an uncertain commit boundary is reconciled against
  exact Office Action evidence during the request. Proven commit/non-commit
  outcomes are finalized; unresolved server errors stop heartbeat renewal and
  remain `running` for stale repair. Pre-commit client conflicts remain
  `rejected`.
- Mutable template operations write ancillary template timestamps first and
  publish the Action-bearing version record last as the canonical handoff.
- Final selection publishes its immutable selection and Action marker before
  updating `project.json`. The project pointer is the last canonical write, and
  reconciliation accepts a selection only when marker, selection, revision,
  artifact, and current project pointer agree.
- Stale Agent-originated `office.render` reconciliation is conservative:
  canonical render evidence without a durable workspace-materialization witness
  repairs to `partial`, not `succeeded`. Direct `office.project.render` can
  still be proven successful from its complete canonical render set.

Verification at this checkpoint:

- OR7-focused backend suite: 78 passed and 2 skipped;
- blocking-I/O router suite: 5 passed;
- backend full suite: 6,286 passed and 54 skipped;
- backend Ruff lint and OR7-scoped format checks: passed;
- frontend lint and typecheck: passed;
- frontend unit suite: 485 passed;
- live repository inventory: all four repositories `current`, including the
  lifecycle attempt-lease schema;
- live read-only repair inspection and plan: six user scopes, no failed checks,
  lifecycle backlog, repairable Actions, or indeterminate Actions. Two
  age-stale Actions remained protected by active worker leases.

Residual risks intentionally retained:

- prepared source intents still require source-state diagnosis because no
  durable witness spans the core thread store and lifecycle journal;
- lifecycle retry remains per handler rather than per domain resource;
- template versions retain only the latest 1,000 Action receipts, and Action
  discovery remains bounded rather than indexed;
- a superseded historical final selection with no terminal Action outcome can
  become indeterminate after the current project pointer moves;
- Agent `office.render` remains conservatively `partial` after stale repair
  until workspace materialization has its own durable completion witness.

## Final Decision

Office is organized in the correct **product position** and uses the correct
**Agent execution runtime**. It should remain one built-in domain Agent with a
project workspace, not become a separate harness and not be collapsed back into
generic chat files.

OR5 documents the resulting two-plane architecture and extension sequence as
stable public contracts. OR6 adds durable handler replay and evidence-backed
Action repair without moving Office semantics into the generic runtime. OR7
fences lifecycle ownership and makes the typed canonical domain commit the
handoff for direct Action provenance. A second production project-backed Agent
should still validate the repository shape before any broad relational project
schema or multi-writer artifact redesign.
