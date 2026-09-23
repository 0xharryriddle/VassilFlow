# Core Backend Refactoring and Performance Plan

**Baseline:** `08db8a6d13a4632240417e16ef3ac00fd2ede9dd`

**Audit:** [CORE_BACKEND_AUDIT.md](CORE_BACKEND_AUDIT.md)
**Status:** Plan and first safe PR-sized slice are implemented and locally verified on this branch. Retention changes and any Go production cutover remain gated on Linux whole-deployment profiling.

## Goals and gates

1. Reduce measured memory use of the actual constrained workload; report Gateway, provisioner, sandbox Pods, and total deployment separately. Never call an import-only result a steady-state improvement.
2. Preserve all existing public HTTP/SSE contracts, persisted schemas, migrations, auth/authorization, user/thread isolation, sandbox path and resource semantics, and lifecycle behavior.
3. Target at least **30% net production LOC reduction** against the audit baseline of 62,172 counted lines (at least 18,652 lines removed), using `python3 scripts/core_backend_loc.py` on both baseline and final. Tests, migrations, safety checks, interfaces, required behavior, and useful docs do not get deleted to meet the number. Report miss/gap plainly if the safe refactor cannot attain the target.
4. Keep changes in independently revertible PR-sized branches. No monolithic rewrite, merge, push, or deploy without explicit instruction.
5. Keep LangGraph orchestration, model SDK integration, checkpoint ownership, and persistence in Python unless a future parity study proves a safe, materially better alternative. A Go HTTP facade that still launches the Python runtime is not a memory optimization.

### Measurement acceptance criteria

Capture Linux production-like cgroup/process memory for cold start, warm idle, representative 1/10/50 concurrent workloads, and a soak long enough to expose retained state. Repeat each case at least five times after warm-up. Record environment, image digest, Python/Go versions, workload seed/model, warm-up, request mix, concurrency, CPU, p50/p95 latency, throughput, failures, per-process peak/current RSS, cgroup peak/current, and the sum for the backend deployment. Keep sandbox Pod memory as a separate series and include it in full-system totals when those Pods are part of the constrained resource pool.

- For a memory-targeting change, require at least **20% lower whole-target cgroup peak and steady-state memory** at the same workload, with the confidence range exceeding measured run-to-run noise. The 20% threshold is a project gate, not an asserted current result; revise it only if baseline variability makes it statistically indistinguishable, and document the replacement before the implementation PR.
- Throughput and success rate must not regress. Require p95 latency to remain within 5% of baseline (or improve); report p50 and event-loop lag as well.
- For Go, count Gateway + provisioner + any adapters/sidecars as a single total. A process-memory reduction alone is not a pass if aggregate memory merely moves elsewhere.
- Memory optimization is blocked from production cutover until Linux cgroup workload data exists. The local macOS import baseline is for comparison/debug only.

## PR sequence

### PR 1 — reproducible inventory and safe regression anchors

**Scope**
- Keep `scripts/core_backend_loc.py` as the canonical baseline/final LOC counter, including `--ref` for reproducible baseline comparisons.
- Add deterministic runtime/blocking-I/O regression tests for async workspace snapshot cache lifecycle.
- Fix the async filesystem boundary in `backend/packages/harness/vassilflow/workspace_changes/recorder.py` only where the new tests demonstrate synchronous filesystem work on the event loop.
- Repair the POSIX mount-path test fixture to mock the command abstraction actually used on POSIX; retain the Windows subprocess mock.
- Link the audit and plan from the backend docs indexes.

**Why first**
- The static scan reports HIGH-priority `shutil.rmtree` reachable from async snapshot code. This is a responsiveness/correctness-under-load risk, not yet a measured memory fix.
- This is a bounded, reversible task and validates the “test first / runtime proof” workflow before larger transformations.

**Preserve**
- Snapshot and diff results, temp-cache lifetime, error propagation, cancellation semantics, and event payloads.
- Strict blocking-I/O gate must still catch a deliberately unoffloaded synchronous filesystem call.

**Verification**
- Focused tests under `backend/tests/blocking_io/` and `tests/test_workspace_changes.py`.
- `make test-blocking-io`, relevant full workspace tests, Ruff, static scan.
- Confirm the final static scan no longer reports the fixed call sites; investigate all new findings.

**Rollback**
- Revert only the recorder change and its new tests/docs.

**Completion**
- Exact behavior and background-thread assertions pass; no full-suite regression. Do not claim lower RSS from this PR.

### PR 2 — production-like performance harness and baseline artifacts

**Scope**
- Add an opt-in benchmark/profile harness under `backend/scripts/` and documentation under `backend/docs/`.
- Reuse deterministic fake/local-model fixtures already present in backend tests where possible; do not call external model providers or a real Kubernetes cluster.
- Capture run create/stream first response/event, subsequent events, history reads, memory slope over completed runs, and event-loop lag. Provisioner lifecycle timing is a separate mocked contract benchmark and later an opt-in disposable-cluster run.
- Add Linux container/cgroup procedure (and optionally a Compose profile) that starts only a disposable test stack with generated fake config/credentials and isolated scratch volumes.

**Preserve**
- Never read or echo `.env` or user `config.yaml`; benchmark must accept an explicit synthetic config path and refuse repository secret files.
- Clearly separate backend memory, optional provisioner memory, and sandbox Pod memory.

**Verification**
- Run the synthetic local benchmark repeatedly on Linux, compare stable output/schema, and test that missing Docker/cluster produces a clear BLOCKED result rather than a pass.
- Attach raw JSON/CSV and exact commands; no model-provider network call.

**Rollback**
- Remove only opt-in scripts/docs/workflow.

**Completion**
- Reproducible baseline collected in Linux and matches documented measurements. The current environment does not satisfy this gate because Docker is unavailable.

### PR 3 — run-state retention after workload evidence

**Scope candidates**
- `backend/packages/harness/vassilflow/runtime/runs/manager.py` (`RunManager._runs`, secondary index, existing `cleanup()`), `runtime/runs/worker.py` terminal lifecycle, persistent `RunStore`, and run/status/history routes.
- Only proceed after PR 2 demonstrates completed run-state growth and tests establish what reads remain valid after completion.

**Design constraints**
- Separate active in-memory coordination state from durable run history. Keep `RunStore` history queryable and preserve status, cancellation, reconnect, wait, resume, and error semantics.
- Make terminal cleanup deterministic and bounded; active runs are never evicted. Do not invent a TTL or delete run history to reduce memory.
- Bound task/reference retention and ensure cleanup tasks are owned, observed, and drained on shutdown; preserve current in-flight shutdown behavior.

**Verification / acceptance**
- Characterization tests for active, completed, failed, cancelled, disconnected, replayed, and persisted runs; race tests for concurrent cleanup/read and shutdown.
- Memory soak shows at least 20% lower target process/whole-deployment memory at equal completed-run volume, with API parity and p95 within 5%.

**Rollback**
- Feature/config switch to prior in-memory retention behavior for one release; keep persisted records intact.

### PR 4 — memory-backend retention policy (conditional)

**Scope candidates**
- `runtime/events/store/memory.py`, its provider/configuration, thread deletion lifecycle, and `MemoryRunStore` only if profiling shows these stores are active and materially growing.
- The checked-in example uses SQLite and DB run-events; first verify actual effective deployment settings. Do not make the production behavior depend on memory-store defaults silently.

**Design constraints**
- Keep database/JSONL history semantics untouched. Any in-memory cap must be explicit/configurable, observable, and preserve documented pagination/reconnect semantics. Do not truncate user message/checkpoint history without an explicit product retention contract.
- Account for the same event dictionaries referenced in multiple indexes; avoid accidental duplicate copies when simplifying.

**Verification / acceptance**
- Deterministic bounds tests, pagination/delete/replay compatibility, multi-thread isolation, cancellation, and memory slope. No silent history loss.
- Same 20% aggregate target and p95/throughput gates.

**Rollback**
- Restore previous store provider/config; no persisted data migration.

### PR 5 — core decomposition and actual simplification

**Scope candidates, ordered by measured change risk**
1. `backend/app/gateway/services.py::start_run()` and its request normalization/identity/context phases.
2. `backend/packages/harness/vassilflow/runtime/runs/worker.py::run_agent()` and terminal/finalization phases.
3. `backend/packages/harness/vassilflow/client.py::stream()`; retain its synchronous public API and separate consumer semantics.
4. `backend/packages/harness/vassilflow/sandbox/tools.py` and `backend/app/channels/manager.py` by true tool/transport boundaries.
5. Large channel providers and journal/storage implementations only with complete per-provider contract tests.

**Required approach**
- Build a behavior/contract map and full unit/integration tests before moving code.
- Delete duplication only when its behavior is genuinely identical. Keep distinct sync vs async client paths, StreamBridge SSE semantics, and provider-specific message protocols distinct where their contracts differ (`backend/docs/STREAMING.md`).
- Extract helpers/modules to make control flow legible; count only actual net first-party line reduction toward 30%.
- Track LOC before/after each PR with the same script. Stop and report if the remaining safe excess code cannot reach the target; do not weaken behavior or tests.

**Verification**
- Full backend tests, boundary checks, blocking-I/O tests, Ruff, contract/API snapshots, and representative fake-model runtime tests for every touched phase.
- Benchmark equivalence for run create, first stream event, ongoing stream, history, and memory before/after.

**Rollback**
- Revert each focused module/behavior change independently; avoid a cross-cutting “big bang” branch.

### PR 6 — Go provisioner parity prototype (conditional, optional)

**Prerequisite gate**
- Linux cgroup baseline demonstrates the Python provisioner is a material part of the memory-constrained deployment and the whole-stack benchmark identifies a credible margin above noise. The current 92.6 MiB import-only result is not enough by itself.

**Initial scope**
- Add a parallel Go implementation under a new `docker/provisioner-go/` or repository-conventional Go service directory; keep Python provisioner as the default until parity and aggregate resource gains are proven.
- Use maintained Kubernetes Go client and pin Go/module versions. Build a minimal static/non-root OCI image where compatible; do not widen permissions or embed credentials.
- Keep exact HTTP paths, methods, request validation/defaults, JSON fields/statuses, idempotent create, list/discover behavior, error mapping, TLS/in-cluster/kubeconfig behavior, NodePort host URL, Pod/service labels/spec/probes/resources, PVC subPath/user/thread isolation, and partial-delete rollback semantics.
- Set HTTP/client/API-server deadlines and cancellation. Provide health/readiness and graceful shutdown; avoid retaining unbounded sandbox records in process memory.
- Build contract fixtures from existing tests (`tests/test_provisioner_kubeconfig.py`, `tests/test_provisioner_pvc_volumes.py` and other provisioner tests). Unit-test resource manifests, mocked K8s calls, HTTP contract, concurrent duplicate creates, deletion failure/rollback, auth/TLS, startup/shutdown, race detector, `go test`, `go vet`, and production image build.

**Cutover acceptance**
- Python stays the rollback/default until side-by-side contract parity passes and the complete Gateway + provisioner + any helper process stack shows >=20% lower peak and steady-state cgroup memory at the same workload, no throughput/success regression, and p95 within 5%.
- Canary is an explicit deployment choice; no automatic migration or user-data rewrite. Roll back by selecting existing Python image/command. Sandbox Pod memory is independently reported.

**LOC reality check**
- The current provisioner is 446 counted production LOC, less than 1% of the measured core. Even a net deletion of all Python provisioner code cannot reach the 18,652-line target. Do not count Go twice: the same LOC tool includes both languages and reports net combined LOC.

### PR 7 — final hardening and measured closeout

- Run the exact final CI-equivalent suite on supported Linux/Python 3.12 and Go version (if Go code is admitted); preserve macOS-only test skips/failures transparently.
- Full tests, Ruff check/format, blocking-I/O runtime/static gates, harness boundary, persistence/schema compatibility, fake-model E2E, API contract, Go tests/vet/race, container build, and sandbox isolation tests as applicable.
- Repeat baseline workloads (minimum five measured repetitions) and compare LOC, RSS/cgroup, latency, throughput, CPU, error rates, event-loop lag, and active/completed state growth.
- Review exact final diff for API/schema/security regressions, accidental generated/secrets files, and rollback readiness.
- Prepare independent PRs/branches if permissions permit; verify remote PR URL/ref/SHA by readback. Never merge/deploy.

## Current execution status

- [x] Recheck baseline branch, HEAD, and clean worktree.
- [x] Read backend contributor guidance, architecture, streaming, memory and sandbox profiling docs, packaging, Compose, provisioner, and core run flow.
- [x] Run local backend tests, Ruff, blocking-I/O runtime/static checks, root system check, and isolate the initial failing test.
- [x] Add and execute reproducible production/test LOC counter.
- [x] Record repeatable cold-import memory baseline without running service lifespan or contacting external services.
- [x] Write audit and staged plan before implementation.
- [x] Add tests first for workspace snapshot cleanup; the new strict-gate tests failed on both direct recursive-delete paths before the code change.
- [x] Offload both cleanup calls from the event loop; focused behavior tests, full strict gate, and full backend suite pass.
- [x] Repair the pre-existing POSIX command-path test mock without changing sandbox production behavior; isolated test and full suite now pass.
- [x] Verify current Ruff, blocking-I/O runtime and static gates, LOC counter, and `git diff --check`.
- [ ] Collect Linux cgroup workload baseline before retention policy or Go cutover.

## Baseline and current verification

- Before the source fixes, the unchanged full suite was **5,846 passed, 20 skipped, 1 failed**. The only failure was `test_execute_command_path_replacement`: test setup replaced `subprocess.run` although POSIX uses `Popen` through `_run_posix_command`.
- After two workspace-cleanup regression tests and a platform-correct test mock were added, the full backend suite is **5,849 passed, 20 skipped**. Exact command: `PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest tests/ -q --tb=short` from `backend/`.
- `uv run ruff check . && uv run ruff format --check .`: pass; 728 files formatted.
- `make test-blocking-io`: 39 passed.
- `make detect-blocking-io`: 36 candidates (19 medium, 17 low); the two previous HIGH cleanup findings are gone. Remaining static findings require individual runtime review.
- `python3 scripts/core_backend_loc.py`: production 62,172 lines / 372 files; tests 87,145 lines / 347 files including the two new tests. Production LOC remains at the baseline because current changes are docs, tests, and a code adjustment, not production-code deletion.
- `make check` remains blocked by missing nginx; Docker container/cgroup baseline remains blocked because Docker daemon is not running.
- No production config/secret was read; no Kubernetes cluster was contacted; no production deployment, merge, or user-data mutation occurred. The review branch is pushed to `origin` and linked to draft PR #1.
