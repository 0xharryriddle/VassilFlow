# Consistency and lifecycle contracts

These contracts describe the architecture-review repairs in the current source
tree and `vassilflow-core` 0.1.1. Domain projects using only core and the template
do not inherit the application's Gateway, channels or full harness dependencies.

## Authentication and persistence

- Initial administrator creation serializes the count and insert in one database
  transaction: SQLite reserves the writer with `BEGIN IMMEDIATE`; PostgreSQL
  locks the users table for the short bootstrap transaction. Hashing happens
  before acquiring the lock. Concurrent initialization has exactly one winner.
- Legacy password upgrades use a conditional password-only update matching the
  original hash and token version. A changed credential snapshot rejects that
  login; it cannot restore a reset password, revoked token version or stale role.
- Thread metadata patches retain shallow dictionary-merge semantics, including
  explicit null values. The repository locks before reading so independent
  concurrent patches survive instead of overwriting one another.
- Failed checkpoint deletion returns `503`, aborts the prepared domain lifecycle
  projection, and retains thread ownership. Retry the deletion after recovery.
  Earlier filesystem cleanup may already have happened, so this is a retryable
  partial operation, not an all-storage transaction. Legacy unowned-thread read
  compatibility remains; this repair does not introduce a migration policy.

The database-specific locking code supports SQLite and PostgreSQL. The local
regression cases exercise independent SQLite connections in DELETE and WAL modes;
PostgreSQL requires its own integration environment before deployment certification.

## Run and task ownership

Replacement admission serializes by thread and waits for the prior worker's
rollback/finalization without holding the global registry lock. The default wait
is five seconds; `RunManager(replacement_timeout=...)` controls this positive,
finite interval. If the prior worker remains active, admission fails with a
conflict instead of launching another writer. A cancelled checkpoint snapshot
read does not authorize deleting the thread's pre-existing history.

Run-history merging fetches enough persisted records before deduplicating live
copies. Embedded token accounting carries a private invocation key through graph
state instead of using the changing Runtime wrapper identity. Memory updates use
the authoritative runtime user ID, falling back to the authentication context.

Channel managers retain their spawned handlers. Shutdown stops dispatch and
waits for handler cancellation/cleanup before outbound transports close.
Cancellation is cooperative; integrations must honor cancellation and use bounded
I/O operations. A shutdown caller must not infer completion from a cancellation
request alone.

## Core and template

RAG owns one native Runnable trace with distinct retrieval/model child runs.
Valid domain brackets such as `[Sales].[Orders]` coexist with citations like
`[S1]`. Numeric citation markers remain strict, and citation validation still
checks identifiers rather than factual entailment.

Stateless delegation rejects dynamic interruption results and visible static
breakpoints instead of reporting partial drafts as completed. A domain tool that
internally hides another execution engine must itself return only finished
results or propagate interruption as an error.

The subagent semaphore limits awaiting invocations per tool and event loop.
Timeout includes queueing and requests cooperative cancellation; cleanup may
delay return. Running synchronous executor code can outlive that wait and its
released slot. Apply integration-level I/O deadlines and resource limits when
strict underlying-work bounds are required.

Evidence assembly caps the candidate text before JSON encoding and avoids
repeatedly serializing accepted sources. Retriever result size and metadata still
belong to the caller's resource budget. Template ingestion streams chunks into
one atomic database replacement: a read/insert failure preserves the previous
index, and an empty successful snapshot removes old documents.

## Frontend boundaries

Private queries use an account-keyed, session-owned query client. A changed user
gets a new client before private descendants render; unmount clears the old
cache and cancels pending queries. Keep new private consumers inside this boundary.

Artifact loading uses the credentialed transport, propagates cancellation, and
rejects HTTP errors before caching text. The preview displays a retry action.
Both memory proxy routes use the private server Gateway configuration, matching
server-side authentication rather than a browser-facing URL override.

## Regression checks

From `backend/`:

```bash
python -m pytest tests/test_gateway_state_consistency.py tests/test_harness_audit_regressions.py tests/test_channel_shutdown_regression.py -q
python -m pytest tests/test_vassilflow_docs.py -q
```

Run core tests from `backend/packages/core/` and template tests from
`templates/rag-agent/` with `python -m pytest -q`. Test the built wheel and copied
template in an independent environment using
[`check_core_distribution.py`](../../scripts/check_core_distribution.py).

From `frontend/`, run `pnpm test`, `pnpm typecheck`, and the relevant lint checks.
The regression tests cover account-cache remount isolation, artifact transport
and HTTP errors, and private Gateway routing. A full browser authentication flow
and real provider/channel integrations remain separate integration checks.
