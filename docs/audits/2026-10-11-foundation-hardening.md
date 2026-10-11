# Foundation and architecture fixes — 11 October 2026

The reusable foundation is available as `vassilflow-core` 0.1.1 and a copied
domain project under `templates/rag-agent/`. Small projects install core without
the Gateway, frontend, sandbox or messaging-channel dependencies. The full
application retains its harness and reuses core's tool-call recovery middleware.

See the [foundation guide](../../backend/docs/FOUNDATION.md) for domain adaptation
and [lifecycle contracts](../../backend/docs/HARDENING.md) for the repaired
behavior and its limits. This change does not publish a distribution to PyPI.

## Review findings addressed

| Finding | Result |
| --- | --- |
| F01 — Partial thread deletion loses ownership | Checkpoint deletion must succeed before ownership removal; failure returns 503 and aborts the prepared domain projection. |
| F02 — Password upgrade overwrites concurrent account changes | Password-only compare-and-swap matches the original hash and token version. |
| F03 — Replacement overlaps checkpoint rollback | Per-thread admission waits for the previous worker's finalization; cancelled checkpoint capture preserves existing history. |
| F04 — Concurrent bootstrap creates several administrators | Database-level count/insert transaction permits one initial administrator. |
| F05 — Interrupted subagent reported as completed | Reject dynamic interruptions and static breakpoints in visible nested graphs and supported Runnable wrappers. |
| F06 — Account changes retain private query data | Each account session owns its QueryClient; switching remounts the boundary and clears the previous cache. |
| F07 — Citation parser rejects ordinary domain brackets | Preserve ordinary bracketed text while strictly checking numeric citation markers. |
| F08 — RAG trace identities collide | A native Runnable root owns distinct retrieval/model child traces. |
| F09 — Concurrent metadata patches lose fields | Lock before reading and merging metadata in the transaction. |
| F10 — Run history under-fetches persisted records | Fetch the requested persisted limit before merging and deduplicating live records. |
| F11 — Token counters depend on unstable Runtime identity | Carry a private invocation key through graph state and keep concurrent accounting separate. |
| F12 — Memory jobs resolve the wrong owner | Prefer authoritative runtime identity, with authentication-context fallback. |
| F13 — Artifact loading caches HTTP error bodies | Use credentialed transport, reject non-success responses, propagate cancellation, and display retry UI. |
| F14 — Memory proxy uses a browser-facing URL | Both routes use private server Gateway configuration. |
| F15 — Channel shutdown leaves handlers running | Own and drain handler tasks before closing transports; shield shared shutdown from cancelled callers. |
| F16 — Timeout/concurrency contract overstates guarantees | Document and test cooperative cancellation; awaiting-invocation limits do not forcibly terminate synchronous executor work. |

RAG evidence assembly now caps candidate content before JSON encoding and avoids
re-encoding accepted sources. Template ingestion inserts chunks incrementally
inside one replacement transaction, preserving the prior index after a read or
insert failure and clearing it for an empty successful snapshot.

## Local validation

Windows, Python 3.12.14 and Node.js 24.19.0 were used for this validation.

| Check | Result |
| --- | --- |
| Full backend suite | 5,877 passed, 30 skipped, 19 warnings; no failures |
| Core source against backend-locked dependencies | 109 passed |
| Core source against independently resolved dependencies | 109 passed |
| Installed 0.1.1 wheel in the independent environment | 109 passed |
| Copied and installed template outside the repository | 12 passed; offline RAG and delegated-agent demos returned sources |
| Frontend unit tests | 519 passed across 63 files |
| Frontend TypeScript and production build | Passed; 81 static pages generated |
| Mounted Chromium account-switch regression | Passed in normal and StrictMode rendering, including late results and cancellation |
| Python lint and formatting | Passed; 742 backend/core Python files matched formatting rules, plus template/distribution-script checks |
| Changed frontend files | ESLint and Prettier passed |
| Backend lockfile and Git whitespace | Passed |
| Distribution integrity | Wheel source matches the checkout; template ZIP integrity passed |

The backend baseline had 5,831 passes, seven failures and 30 skips. Five failures
were caused by `uv` being absent from the test subprocess PATH, one by the wrong
Python being selected for deployment-extra detection, and one by a documentation
phrase mismatch. The final run used the backend virtual environment and `uv` on
PATH, with `UV_NO_SYNC=1` to avoid mutating that environment during script tests;
the required documentation wording was repaired. No test was disabled to obtain
the passing result.

Core was exercised against both dependency sets:

- Backend lock: LangChain 1.2.15, LangChain Core 1.3.3, LangGraph 1.1.9.
- Independent environment: LangChain 1.4.4, LangChain Core 1.6.9, LangGraph 1.2.14.

The new GitHub workflow builds and tests an installed core wheel and copied
template on both Windows and Linux. Local results above do not certify a remote
workflow run.

## Remaining integration boundaries

Live PostgreSQL, Docker deployment, real model providers, real messaging
transports, and a complete browser login/logout flow were not exercised. SQLite
concurrency tests use independent connections in DELETE and WAL modes. The
browser test mounts the actual cache provider and validates account switching;
it is not a full authentication end-to-end test.

Subagent timeouts request cooperative cancellation. Synchronous executor work
can outlive the waiting task and released slot; domain adapters own strict I/O
deadlines and underlying resource limits. Channel shutdown also relies on
cooperative cleanup. Citation validation checks source identifiers, not factual
entailment. No production throughput or latency guarantee is claimed.
