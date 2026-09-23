# Core Backend Performance and Simplification Audit

**Audit baseline:** `08db8a6d13a4632240417e16ef3ac00fd2ede9dd` (`main` at audit start)

**Audit branch:** `refactor/core-backend-audit-plan`

**Date:** 2026-09-23

**Scope:** `backend/app/`, `backend/packages/harness/vassilflow/`, `docker/provisioner/`, backend tests, backend packaging/CI/deployment entry points, and backend architecture/runtime/sandbox/persistence docs.
**Status:** Source audit and local baselines collected. A small post-audit event-loop cleanup fix is now in the worktree, with strict-gate regression evidence; it is not a memory optimization. No service was started, no Kubernetes API was called, and no real configuration/secret file was read.

## Executive findings

1. The Python Gateway has a measured **130.5 MiB median cold-import peak RSS** on this macOS machine; the separately imported Python provisioner measured **92.6 MiB**. These numbers are import-only, not idle or workload memory. Docker was unavailable, so no Linux container RSS/cgroup or total-deployment workload baseline could be taken. They do not establish which running component causes the reported memory pressure.
2. The Gateway is not a stateless HTTP front door: it owns the embedded LangGraph runtime, run manager, stream bridge, checkpointer, and run-event store. Run execution is created as an in-process asyncio task and streamed through an in-process bridge. The runtime rejects multiple Uvicorn workers because coordination and streaming remain process-local (`backend/app/gateway/deps.py:50-61`; `backend/docs/ARCHITECTURE.md:422-430,488-492`). A Go replacement of API routes alone would not remove this Python runtime.
3. There is a source-backed retained-state concern to measure first: `RunManager.cleanup()` exists, but repository search found only its definition and test callers, not a production caller. `run_agent()` schedules stream-bridge cleanup after 60 seconds, but does not schedule run-record cleanup (`backend/packages/harness/vassilflow/runtime/runs/manager.py:690-698`; `backend/packages/harness/vassilflow/runtime/runs/worker.py:452-461`). `RunRecord` retains metadata, kwargs, message summaries, token data, and a task reference (`manager.py:74-106`). This can retain completed-run state in the Gateway process; the actual growth rate and operational significance are not yet measured.
4. The optional `MemoryRunEventStore` has no retention limit in its implementation. It keeps event/message records and per-run projections in process memory (`backend/packages/harness/vassilflow/runtime/events/store/memory.py:15-30,38-65,138-158`). This is conditional: the checked-in `config.example.yaml` sets `database.backend: sqlite` and `run_events.backend: db` (`config.example.yaml:1382-1403`). Do not infer that a deployment uses the unbounded memory implementation without checking its non-secret effective settings.
5. Several large/complex files are real legibility targets, but splitting a file alone does not reduce LOC. Largest measured functions include `run_agent()` (338 lines), `VassilFlowClient.stream()` (294), `FileRepository.inventory()` (223), `services.start_run()` (203), `SubagentExecutor._aexecute()` (187), and channel message handlers up to 187 lines. Large files include `sandbox/tools.py` (1,987 physical lines), `channels/manager.py` (1,681), `channels/wechat.py` (1,456), and `runtime/lifecycle_journal.py` (1,295). Refactor at behavior boundaries; preserve channel- and protocol-specific semantics.
6. A Go provisioner is the clearest *isolated Go experiment*, not yet a justified production migration. It is already a separate optional service with one 563-line Python entrypoint (`docker/provisioner/app.py`), about 446 counted production LOC, and an import-only peak of 92.6 MiB. A Go rewrite could reduce that optional service's interpreter/dependency footprint, but will not reduce Gateway RSS and has no measured total-stack benefit yet. Its Kubernetes API contract, path/PVC isolation, cleanup/idempotence, TLS/auth trust boundary, and deployment rollback require parity tests before cutover.
7. The repository’s production LOC baseline is **62,172 counted lines across 372 tracked Python/Go files** under the defined core roots. Tests are reported separately: **87,096 counted lines across 346 tracked backend test files**. A 30% net reduction requires at least **18,652 counted production lines removed** (same tool and scope before/after). The provisioner accounts for 446 counted lines, less than 1% of the target scope, so porting it cannot by itself approach the 30% target.

## Verified architecture and main flows

### Service/dependency topology

```text
HTTP/SSE clients, browser, IM channels
                |
                v
Nginx :2026 (deployment entry point)
       |                         |
       v                         v
Gateway :8001                  Frontend :3000
FastAPI + embedded             Next.js
LangGraph runtime
       |
       +-- app DB / checkpointer / run-event store
       +-- VASSILFLOW_HOME workspaces, uploads, outputs, journals
       +-- model providers, MCP/search, channel APIs
       +-- sandbox provider
              |
              +-- local / Docker / Apple Container
              `-- optional RemoteSandboxBackend --> Provisioner :8002 --> Kubernetes API
                                                      |
                                                      `--> per-sandbox Pod + NodePort Service
```

The canonical runtime ownership and storage authority are documented in `backend/docs/ARCHITECTURE.md:26-54,101-130,422-435`. The harness/app dependency firewall is documented in `backend/CLAUDE.md:157-183` and enforced by `backend/tests/test_harness_boundary.py`.

### Run and stream path

1. Gateway routes mount the thread/stateless run APIs (`backend/app/gateway/app.py:380-433`). A stream route calls `services.start_run()` (`backend/app/gateway/routers/runs.py:44-48`; thread-run routes are under `backend/app/gateway/routers/thread_runs.py`).
2. `start_run()` resolves canonical Agent identity, validates claims/model allowlist, checks user/thread ownership and Agent identity, resolves trusted capability inputs/readiness, builds run configuration and checkpoint selection, persists/creates a run record, then schedules `run_agent()` as an asyncio task (`backend/app/gateway/services.py:679-878`). These are security and compatibility invariants, not safe LOC to delete.
3. `run_agent()` establishes runtime context, optional run journal, checkpoints and workspace snapshots, builds the Agent, streams LangGraph chunks, serializes and publishes them, sets terminal status, reconciles metadata, and publishes stream end (`backend/packages/harness/vassilflow/runtime/runs/worker.py:124-138,173-280,294-350,351-461`).
4. `MemoryStreamBridge` maintains per-run replay buffers, heartbeat/end semantics, and event IDs. Event count is bounded by `queue_maxsize` (default 256) but streams remain present until delayed cleanup (`backend/packages/harness/vassilflow/runtime/stream_bridge/memory.py:25-43,67-100,108-152`; `worker.py:460-461`).
5. The SSE consumer honors reconnect IDs, disconnection, cancellation, and end events (`services.py:884-963`). These semantics must be retained through any service split.
6. Store/checkpointer/run-event providers select memory, SQLite/Postgres, or JSONL implementations (`backend/app/gateway/deps.py:185-245`; `backend/packages/harness/vassilflow/runtime/checkpointer/async_provider.py:167-202`; `runtime/store/async_provider.py:141-173`; `runtime/events/store/__init__.py:5-23`). The two runtime state planes are not one transaction.

### Provisioner boundary and contract

- `RemoteSandboxBackend` calls a separate provisioner over HTTP with timeouts for list/create/delete/status/discovery (`backend/packages/harness/vassilflow/community/aio_sandbox/remote_backend.py:32-101,105-218`). The service contract includes `GET /health`, `POST /api/sandboxes`, `GET /api/sandboxes/{id}`, `DELETE /api/sandboxes/{id}`, and `GET /api/sandboxes` (`docker/provisioner/app.py:11-16,420-563`).
- The request validates thread/user IDs; creation is idempotent by `sandbox_id`, creates a Pod and NodePort Service, and rolls back Pod creation if Service creation fails (`docker/provisioner/app.py:208-218,426-489`). Destroy attempts Service and Pod cleanup; list/status/discovery semantics and error shapes are part of compatibility.
- Pod construction fixes labels, image, probes, 256Mi request / 1Gi limit, workspace/skills mounts, PVC subPath isolation, and security context (`docker/provisioner/app.py:294-362`). Those are not observed memory measurements.
- Provisioner startup loads mounted kubeconfig or in-cluster credentials, may create its namespace, and can override the API endpoint (`docker/provisioner/app.py:115-148,151-199`). The Kubernetes client trust/RBAC boundary is sensitive. The Python provisioner is not the sandbox: Pod working-set memory belongs to sandbox containers and must be measured separately.
- Production and dev Compose build/run the Gateway and (optionally) the provisioner separately (`docker/docker-compose.yaml:64-81,125-153`; `docker/docker-compose-dev.yaml:120-189`). The Gateway image uses Python 3.12 (`backend/Dockerfile:10-11,83-85`); the provisioner is also Python 3.12 and installs FastAPI/Uvicorn/Kubernetes (`docker/provisioner/Dockerfile:1-29`).

## Inventory and LOC baseline

The reproducible counter is `scripts/core_backend_loc.py`:

- Production roots: tracked `.py` and `.go` files under `backend/app/`, `backend/packages/harness/vassilflow/`, and `docker/provisioner/`.
- Excludes tests, generated/vendor code, dependencies, and documentation.
- Counts nonblank source lines other than full-line `#`/`//` comments; docstrings and inline comments remain counted. This is a stable, simple LOC proxy, not a semantic measure of code complexity.
- Tests are counted separately as tracked `.py` files under `backend/tests/`.

At baseline `08db8a6d13a4632240417e16ef3ac00fd2ede9dd`:

| Area | Tracked files | Counted lines | Physical lines |
| --- | ---: | ---: | ---: |
| `backend/app/` | 75 | 17,268 | — |
| `backend/packages/harness/vassilflow/` | 296 | 44,458 | — |
| `docker/provisioner/` | 1 | 446 | — |
| **Core production total** | **372** | **62,172** | **78,284** |
| `backend/tests/` (separate) | 346 | 87,096 | 115,127 |

Re-run: `python3 scripts/core_backend_loc.py` from repo root. The audit branch’s added tool and documents are outside the counted source roots, so they do not alter the production baseline.

## Reproducible local import baseline (not service RSS)

Environment: macOS 26.5.1, arm64; backend project virtual environment (Python 3.12); `/usr/bin/time -l`; five fresh processes per case. The values below are median maximum-resident-set size, with min–max across five repetitions. No lifespan, HTTP requests, model calls, database initialization, or Kubernetes calls were run. The Gateway import test set `VASSILFLOW_CONFIG_PATH` to a deliberately nonexistent scratch path so it would not read the repository’s real configuration. Its module import can still start the skills-cache background thread; this is not a production configuration or a warm service.

| Fresh process | Median peak RSS | Range | Median wall time | Interpretation |
| --- | ---: | ---: | ---: | --- |
| `python -c 'pass'` | 15.3 MiB | 15.3–15.3 | 0.010 s | interpreter baseline |
| `import fastapi` | 42.5 MiB | 42.4–42.5 | 0.120 s | FastAPI import cost in this environment |
| `from kubernetes import client, config` | 75.8 MiB | 75.7–75.9 | 0.150 s | Kubernetes client import cost; overlaps other imports, do not add rows |
| `import langchain.agents` | 67.0 MiB | 66.9–67.1 | 0.240 s | LangChain agent import cost; overlaps other imports |
| `import app.gateway.app` | 130.5 MiB | 130.4–130.6 | 0.690 s | Gateway module/app-construction import only, not lifespan |
| `import app` from `docker/provisioner/` | 92.4 MiB | 92.4–92.6 | 0.240 s | provisioner module import only, not lifespan |

Example exact single-process command (repeat five times for the reported distribution):

```bash
cd backend
VASSILFLOW_CONFIG_PATH=/Users/sense/.hermes/cache/scratch/vassilflow-audit-config-does-not-exist.yaml \
  /usr/bin/time -l .venv/bin/python -c 'import app.gateway.app'

cd ../docker/provisioner
/usr/bin/time -l ../../backend/.venv/bin/python -c 'import app'
```

These cannot answer warm-idle/active-run memory, cgroup peak, process overlap, whole-stack memory, or sandbox Pod memory. `docker info` reported that the Docker daemon is not running in this environment. No Kubernetes cluster was queried. Collect those figures on a disposable Linux test deployment before approving a production Go cutover.

## Test and quality baselines

Before implementation, the unchanged production-code baseline had the following results:

| Gate | Command | Result |
| --- | --- | --- |
| Full backend tests | `cd backend && PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest tests/ -q --tb=short` | One failing test: `test_execute_command_path_replacement`; see focused reproduction below |
| Known failure, isolated | `cd backend && PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest tests/test_local_sandbox_provider_mounts.py::TestMultipleMounts::test_execute_command_path_replacement -q --tb=short` | **1 failed**; reproduces on this POSIX/macOS host |
| Ruff | `cd backend && uv run ruff check . && uv run ruff format --check .` | **pass**; 727 files already formatted |
| Blocking-I/O runtime gate | `cd backend && make test-blocking-io` | **37 passed** in 10.90s |
| Blocking-I/O static scan | `cd backend && make detect-blocking-io` | **38 candidates**: 2 HIGH, 19 MEDIUM, 17 LOW; informational scan, not proof |
| Root system check | `make check` | **blocked/fails** because nginx is not installed |
| Container baseline | `docker info` | **blocked**; Docker daemon not running |

After PR 1 changes, the full suite is **5,849 passed, 20 skipped**; Ruff is clean with 728 files formatted; the blocking-I/O runtime gate is **39 passed**; static scan is **36 candidates** (19 MEDIUM, 17 LOW, no HIGH findings). Exact current commands/results are recorded in `CORE_BACKEND_REFACTOR_PLAN.md`. The initial test run's pass/skip totals were not preserved in this audit log; only its single failure was verified and fixed.

The isolated failure is in `backend/tests/test_local_sandbox_provider_mounts.py:478-507`: the test replaces `subprocess.run` and expects it to capture the resolved command; POSIX production code takes `_run_posix_command()` and uses `subprocess.Popen` (`backend/packages/harness/vassilflow/sandbox/local/local_sandbox.py:483-485,501-519`). The test’s mock/assertion does not follow that POSIX path, so classify this as a cross-platform test-fixture gap pending a focused fix, not as evidence of a production command-path defect. Do not suppress or weaken the test.

Static scan candidates include two high-priority recursive deletions in `backend/packages/harness/vassilflow/workspace_changes/recorder.py:60,111`; the scanner found 38 total file-I/O candidates (28 direct async, 10 same-file-reachable). Manual/runtime regression anchors should be added before changing any candidate. This affects event-loop latency, not proven memory use.

## Ranked findings

| Rank | Finding | Impact / confidence | Risk and next evidence |
| ---: | --- | --- | --- |
| 1 | Completed `RunRecord`s appear to remain in `RunManager._runs`: cleanup API exists but has no production caller; the worker only schedules stream cleanup. | Potential high cumulative memory; high confidence that cleanup is not called in tracked production paths; actual memory impact unmeasured. | Before cleanup behavior changes, establish API read-after-completion expectations, persistent-store fallback, memory backend behavior, and RSS slope under a fake-model run soak. Then add explicit retention semantics and parity tests. |
| 2 | `MemoryRunEventStore` maintains whole-thread event/message collections plus run projections and sequence maps with no built-in retention. | Potentially high in memory-backend deployments; high source confidence, conditional deployment applicability. | Confirm effective runtime backend without exposing credentials; measure bytes/event and growth at load. Preserve message history/pagination and thread delete semantics. Checked-in example uses DB, so this is not automatically the deployed backend. |
| 3 | Heavy framework imports are a plausible cold-start/RSS floor: import-only Gateway is 130.5 MiB; LangChain agent imports 67.0 MiB; Kubernetes client imports 75.8 MiB. | Medium; measurement is repeatable but import-only and dependencies overlap. | Use Linux cgroup/process profiling, import-time profile, and feature-specific route/runtime import tracing. Test lazy/optional imports as an isolated experiment; do not remove package support based on import figures alone. |
| 4 | Gateway memory cannot be scaled by simply adding Uvicorn workers; active runs/streams are process-local. | High architectural confidence. | Any future multi-worker Go/Python split needs a shared run coordinator/stream transport, durable state, sticky/reconnect behavior, and race/shutdown tests. Do not introduce multiple workers as a memory workaround. |
| 5 | God functions/files create review and change-risk, especially `run_agent`, `start_run`, client streaming, sandbox tools, channel manager/providers, and durable journals. | High source confidence; LOC opportunity is unquantified. | Extract along named lifecycle phases or protocol boundaries with characterization tests; preserve security/persistence invariants. File splitting alone does not meet LOC target. |
| 6 | Provisioner is a bounded Go port candidate: separate process and simple HTTP/Kubernetes boundary; import-only RSS is 92.6 MiB. | Medium potential memory opportunity; actual deployment and total-stack benefit unknown. | Build contract tests and a Go parity prototype only after Linux total-stack baseline. Preserve request/response/status/error, idempotency, PVC/user path isolation, Pod security/resources, kubeconfig/in-cluster auth, namespace startup, cancellation/timeouts, and health/shutdown. Roll back by switching image/command to Python. |
| 7 | Static I/O scan finds async file work, including recursive cleanup, but it is not proof of latency or memory impact. | High confidence about scan outputs, low-to-medium confidence on runtime effect. | For each finding, add a strict Blockbuster/runtime anchor and offload only blocking work; benchmark event-loop lag separately from RSS. |

## Go boundary decision

**Do not rewrite LangGraph orchestration, model-provider SDK integration, checkpoint ownership, or application persistence in Go in this plan.** They are Python-native integrations and own state semantics, callbacks, middleware, and streaming behavior. A thin Go Gateway would still need to call the Python runtime and would likely add a process rather than remove the dominant allocation.

**Candidate for a conditional Go proof-of-parity:** `docker/provisioner/app.py`, only if the measured optional Kubernetes-mode stack shows its process is a material part of total RSS and a Go implementation measurably reduces whole-stack memory. It manages K8s resource lifecycle but does not execute sandbox commands; sandbox Pod RSS is a separate product/resource concern. Import-only measurements are evidence to investigate, not authorization to cut over.

**No Go implementation is in this audit branch.** It would be premature to port before workload/idle/cgroup measurements and contract characterization.

## Known unknowns and explicit limits

- The user has not supplied which running component is high, real memory measurements, workload, concurrency, deployment mode, or a target capacity. The local numbers cannot replace this evidence.
- No production-like Linux runtime/cgroup or total-service workload data is available because Docker is not running. Do not claim a measured steady-state memory reduction or throughput/latency improvement.
- Current deployment settings may differ from `config.example.yaml`; no real configuration or secret was read.
- LOC is a source-size proxy. It does not establish maintainability or behavior removal. Python and Go remain counted with the same rule after any migration.
- The 30% LOC reduction target is not yet shown to be safely achievable. Required reduction is 18,652 counted lines. Do not delete behavior, contracts, migrations, safety checks, tests, or docs to hit it.
- The initial audit baseline produced no source changes. After the plan was written, a bounded first PR-sized slice was implemented; see the current execution results in `CORE_BACKEND_REFACTOR_PLAN.md`. It is a draft PR only. No production config/data mutation, merge, Go cutover, or deployment occurred.
