# Persistence And Readiness

VassilFlow uses separate persistence layers because runtime execution records,
user files, and domain artifacts have different consistency and storage needs.
Changing the application database backend does not move every layer into that
database. The base ships no built-in product Agents or product repositories;
the generic Action, lifecycle, and operational repository contracts remain
available for domain extensions.

## Storage Layers

| Layer                                | Current storage                                                                                  | Migration mechanism                                 |
| ------------------------------------ | ------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| Application data and LangGraph state | `memory`, SQLite, or PostgreSQL from `database`                                                  | Alembic bootstrap and upgrades                      |
| Run events                           | `memory`, application database, or JSONL from `run_events`                                       | Backend-specific                                    |
| Thread workspaces and uploads        | Files under `VASSILFLOW_HOME`                                                                    | No cross-backend migration                          |
| Action journal                       | User-scoped append-only JSON records under `VASSILFLOW_HOME`                                     | Domain repository inventory and explicit migrations |
| Lifecycle projection journal         | User-scoped source intents, immutable outcomes, and per-handler attempts under `VASSILFLOW_HOME` | Repository inventory and replay                     |
| Optional domain data                 | Storage selected and owned by a registered extension                                           | Extension-owned inventory and explicit migrations   |

The default runtime root is `.vassilflow` under the project root. Set
`VASSILFLOW_HOME` to one persistent writable directory when the default is not
appropriate.

## Deployment Contract

- Persist or mount the complete `VASSILFLOW_HOME` directory. Mounting only the
  SQLite file loses workspaces, Action records, and lifecycle journals. Include
  any separately configured extension storage in the same backup plan.
- SQLite and the file-backed domain repositories are single-node storage.
- The Action and lifecycle repositories currently advertise
  `single_writer`.
  Run one Gateway worker (`GATEWAY_WORKERS=1`) and do not let multiple Gateway
  deployments write the same runtime root.
- Startup rejects `GATEWAY_WORKERS` and `WEB_CONCURRENCY` values other than `1`,
  including invalid values. Docker forwards its CLI worker count to this guard.
  Custom launch commands and replica counts must also stay at one: the app
  cannot detect arbitrary process-manager or command-line overrides.
- PostgreSQL makes the application database durable and shareable. It does not
  make file-backed domain repositories multi-writer or multi-host, or share
  the process-local RunManager and StreamBridge.
- Docker production mounts `VASSILFLOW_HOME` into the Gateway. Keep that host
  directory or volume across container replacement.
- Do not edit repository JSON manually. Readers fail closed on unknown,
  malformed, oversized, or unsupported schema records.
- File-backed inventory does not traverse symbolic links or Windows junctions,
  rejects hard-linked records, bounds directory entries and record bytes, and
  verifies file identity around descriptor-anchored reads.

## Backup And Restore

There is no transaction spanning the application database and file-backed
domain repositories. For a consistent backup:

1. Stop the Gateway or otherwise quiesce writes.
2. Back up the application database.
3. Back up the complete `VASSILFLOW_HOME` directory in the same maintenance
   window.
4. Restore both layers before restarting the Gateway.
5. Run the repository inventory command and the Gateway readiness probe.

## Repository Operations

Inventory is read-only and reports aggregate record/schema counts without
filesystem paths or user identifiers:

```bash
make repository-inventory
```

Preview registered migrations without changing data:

```bash
make repository-migration-plan
```

Apply only the exact migrations registered by each owning domain:

```bash
make repository-migrate
```

Take a backup and use a maintenance window before applying migrations. Each
repository declares either `maintenance_window` or `transactional` migration
safety; a `multi_writer` repository must provide transactional migrations.
Migration plans are bound to one declared record kind. An unknown schema with
no registered migration is reported as `blocked`; it is never upgraded
heuristically. Before applying, the registry rejects duplicate, stale, altered,
cross-kind, overlapping, or incomplete plans. After applying, the command runs
inventory again and exits nonzero unless every repository is `current`.

The registry validates each repository result but cannot provide one atomic
rollback across multiple storage systems. Quiesce writes for the complete
plan/apply/re-inventory cycle when any participating repository declares
`maintenance_window`.

Without GNU Make, run the commands from `backend`:

```bash
uv run python scripts/domain_repositories.py inventory
uv run python scripts/domain_repositories.py migrate
uv run python scripts/domain_repositories.py migrate --apply
```

Use `--user-id USER_ID` before the subcommand to limit an operation to one
user scope. The identifier is not echoed in the report.

## Projection Repair

Inspect aggregate unresolved lifecycle projections and stale `running` Actions
without changing data:

```bash
make projection-repair-status
```

Build the same evidence-backed repair plan:

```bash
make projection-repair-plan
```

Replay only unfinished lifecycle handlers and append only domain-verified
Action outcomes:

```bash
make projection-repair
```

Without GNU Make, run these commands from `backend`:

```bash
uv run python scripts/projection_repair.py inspect
uv run python scripts/projection_repair.py repair
uv run python scripts/projection_repair.py repair --apply
```

The default stale threshold is five minutes. Use
`--stale-after-seconds 60..86400` and `--limit 1..500` before the subcommand to
change a bounded pass. `--user-id USER_ID` limits the scope and is never echoed
in output.

Lifecycle mutation uses a two-phase journal. The Gateway writes a source intent
before changing thread state, then writes an immutable `source_committed` or
`source_aborted` marker. Only committed operations enter handler fan-out.
Deterministic event IDs and immutable per-handler attempts let replay skip a
completed handler and reclaim an interrupted handler attempt only after its
lease expires. Active attempts renew a durable lease under one monotonic
generation. Reclaim creates the next generation, and the displaced attempt is
fenced from renewing or writing an outcome. A prepared intent without a source
outcome remains visible for operator diagnosis and is never guessed into a
committed operation.

Every new Action starts with a renewable worker lease. Integrations using the
Action contract must heartbeat that lease while a mutation is active. Repair must
wait for lease expiry and acquire an atomic, short-lived claim before asking
the owning domain for canonical evidence or writing a terminal outcome. The
domain must find an exact Action marker; legacy, unsupported, missing, or
ambiguous evidence remains `indeterminate`.

A domain integration should finalize provenance from its typed canonical commit
before performing optional response readback. If a mutation raises after it may
have committed, a registered domain reconciler must verify exact Action
evidence before finalizing an outcome. Unresolved evidence remains `running`
for operator diagnosis instead of being guessed into `failed`. The base has no
product-specific reconciler.

## Health Endpoints

`GET /health` is a lightweight liveness endpoint kept for process and nginx
compatibility.

`GET /health/ready` returns
`vassilflow.health.readiness.v1` with:

- core runtime initialization;
- application database connectivity and durability mode;
- a deadline-bounded, lightweight lifecycle and Action lease backlog check;
- built-in Agent tool requirements;
- cached capability dependency checks declared by registered extensions.

Independent built-in Agent probes run concurrently, so adding Agents does not
make a cold readiness request wait for each dependency in sequence.
Capability probes are single-flight, deadline-bounded, and cached in-process
for at most 15 seconds. The cache is status evidence, not authorization or a
substitute for dependency checks at operation time.

The projection backlog check does not run domain reconciliation or scan
canonical domain evidence. Canonical evidence is read only by the explicit
operator repair command.

The readiness response uses:

- `ready`: all core and Agent checks passed;
- `degraded`: the Gateway can serve requests, but at least one Agent is limited
  or unavailable;
- `not_ready`: a required Gateway runtime or persistence dependency failed.

The endpoint returns HTTP `503` only for `not_ready`. An optional failed
dependency may leave a registered Agent degraded and launchable. With the
shipped empty built-in Agent registry, readiness evaluates the core runtime and
persistence without product-specific dependency probes.

Before a built-in Agent run is recorded, the Gateway evaluates the same
server-owned product contract. It rejects an Agent with an unavailable required
tool or repository using a sanitized `agent_unavailable` HTTP `503` response.
Optional unavailable dependencies remain degraded and launchable.
