# VassilFlow backend

See [hardening contracts](docs/HARDENING.md) for atomic account initialization,
conditional password rehashing, retryable thread deletion, run replacement and
embedded execution boundaries. The reusable core release is 0.1.1; keep provider
SDKs and domain adapters optional in projects built from the template.

VassilFlow provides a reusable agent harness and a FastAPI Gateway with an embedded LangGraph runtime. Use the source base to build new agents with shared tools, skills, memory, sandbox access, delegation, persistence, and streaming. The base ships the default lead agent and personal-agent support, with no built-in product agents or Office renderer.

Start with the [backend documentation index](docs/README.md). The [architecture contract](docs/ARCHITECTURE.md) defines Agent identity, capability adapters, Actions, lifecycle hooks, readiness, and repository boundaries for future products.

## Source layout

```text
backend/
  app/
    gateway/                  # HTTP APIs, authentication, runtime composition
    channels/                 # IM integrations and user binding flows
  packages/core/
    pyproject.toml            # Independent vassilflow-core distribution
    vassilflow_core/          # Injected-model agents, RAG and bounded delegation
    tests/                    # Standalone package tests
  packages/harness/
    pyproject.toml            # Reusable harness package
    vassilflow/               # Public Python import namespace
      agents/                 # Factories, prompts, middleware, memory
      capabilities/           # Generic capability adapter contracts
      actions/                # Mutation provenance
      config/                 # Configuration and runtime paths
      runtime/                # Runs, streams, checkpoints, lifecycle
      persistence/            # Application and repository contracts
      sandbox/                # Sandbox interfaces, local provider, file tools
      subagents/              # Delegated workers
      tools/                  # Built-in tools
      community/              # Configurable integrations and AIO provider
      mcp/                    # MCP discovery, sessions, and tools
      models/                 # Model adapters and factory
      skills/                 # Skill discovery and installation
      client.py               # Direct in-process client
  tests/
  docs/
```

Application code may import `vassilflow.*`; the harness must not import `app.*`.
Core must import neither namespace. The harness depends on core and reexports
its `DanglingToolCallMiddleware`, preserving the existing harness import path.

## Build a small domain project

The [foundation guide](docs/FOUNDATION.md) explains the current source structure,
what each domain customizes and how to adapt the starter to HR policy RAG.

Use [`vassilflow-core`](packages/core/README.md), imported as `vassilflow_core`,
with the [copyable project template](../templates/rag-agent/README.md) for a
standalone RAG or agent application. Pass the model and retriever explicitly;
keep domain prompts, data and tools in the copied project. Provider SDKs are
optional `openai` and `anthropic` extras; the `sqlite` extra adds a LangGraph
checkpoint adapter. The template's standard-library SQLite FTS5 index performs
lexical retrieval and does not require that checkpoint extra.

The template offers ingestion, cited RAG, a coordinator/research-subagent flow
and a deterministic offline demo. Installing only core avoids installing the
full harness and Gateway. The existing full-application installation and its
dependencies remain unchanged in scope.

## Start Gateway

From the repository root, after preparing configuration:

```bash
cd backend
uv sync
uv run uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001 --reload
```

Gateway exposes `/health`, `/health/ready`, `/docs`, and `/openapi.json`. For the complete application, follow [setup](docs/SETUP.md); nginx on port 2026 routes frontend traffic to port 3000 and API traffic to Gateway on port 8001.

Use one Gateway worker, including with PostgreSQL. `GATEWAY_WORKERS` and `WEB_CONCURRENCY`, when set, must each be `1`. Runtime-home defaults differ between direct embedding and repository launchers, and SQLite has its own directory setting; see [path resolution](docs/PATH_EXAMPLES.md).

The local sandbox runs on the host and disables bash by default. Container-backed execution is a separate provider choice. Token limits use returned provider usage and can overshoot during concurrent work; pending memory extraction is an in-process best-effort queue. The feature guides document these limits rather than promising uniform isolation or durability.

## Build a new agent

Within the full harness, use the [pure-argument factory](docs/rfc-create-vassilflow-agent.md) to compose a model, tools, middleware, and `RuntimeFeatures`, or use `VassilFlowClient` for configuration-driven synchronous embedding. Gateway provides authenticated HTTP/SSE and application lifecycle integration.

Keep product-specific code outside the generic harness. Use the existing capability and policy contracts when adding trusted inputs, specialized tools, domain storage, and frontend extensions.

## Validate changes

From `backend/`:

```bash
uv run pytest tests/ -v
uvx ruff check .
uvx ruff format --check .
```

See [contribution guidance](CONTRIBUTING.md), [blocking I/O checks](docs/BLOCKING_IO_DETECTION.md), and [replay E2E](docs/REPLAY_E2E.md). External-service integration tests require their configured prerequisites; replay tests provide a model-key-free contract check.

Validate core separately with `python -m pytest backend/packages/core/tests --confcutdir=backend/packages/core`
from the repository root, using an environment where core and its test extras
are installed. For distribution verification, activate a **new disposable
virtual environment**, install the built wheel with its `test` extra, then run
from the repository root:

```bash
python -m pip install "/path/to/vassilflow_core-0.1.1-py3-none-any.whl[test]"
python scripts/check_core_distribution.py
```

The script rejects full-stack environments, clears `PYTHONPATH`, installs a
copied template into the active environment and runs its demo and acceptance
tests outside the checkout. It makes no live model calls. Do not run it inside
the existing backend environment or an environment containing another
`domain-assistant` installation.
