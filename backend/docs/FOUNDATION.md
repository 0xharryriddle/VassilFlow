# Reusing the foundation across domains

Use the versioned `vassilflow-core` package for shared runtime behavior and copy
`templates/rag-agent/` for each domain application. A new HR, support or research
project owns its documents, prompts, retrieval adapter, tools and interface. It
imports the shared runtime as `vassilflow_core`.

This guide describes the current package and template. See the
[core API guide](../packages/core/README.md) for runtime contracts and the
[starter README](../../templates/rag-agent/README.md) for its command reference.
The full VassilFlow application remains available separately; its dependencies
have not been reduced to the core package's dependencies.
See [consistency and lifecycle contracts](HARDENING.md) for the 0.1.1 fixes,
including interruption handling, trace ownership and cancellation limits.

## Source structure

Paths in this tree are relative to the repository root:

```text
backend/
  packages/core/
    pyproject.toml                 # Distribution: vassilflow-core
    vassilflow_core/
      __init__.py                  # Public exports
      agents.py                    # Agent composition and model-call limit
      rag.py                       # RAG pipeline, source records, retrieval tool
      subagents.py                 # Bounded in-process child execution
      middleware/
        dangling_tool_calls.py     # Interrupted tool-call recovery
    tests/                         # Core contracts without full-app fixtures
  packages/harness/vassilflow/     # Full harness: skills, memory, sandbox, etc.
  app/                            # Gateway, authentication and channels
templates/rag-agent/
  pyproject.toml                   # Domain package and core version constraint
  data/                            # Example Markdown/text documents
  src/domain_assistant/
    prompts.py                     # RAG, researcher and coordinator instructions
    models.py                      # Offline fixture and optional live provider
    index.py                       # Local ingestion and SQLite FTS5 retrieval
    composition.py                 # Model/retriever/tool/agent wiring
    cli.py                         # ingest, ask, agent and demo commands
  tests/test_starter.py            # Domain starter acceptance tests
frontend/                          # Full application's web interface
scripts/check_core_distribution.py # Installed-wheel and copied-project check
```

Core depends on LangChain, LangChain Core, LangGraph and Pydantic, including
their transitive dependencies. Model providers and checkpoint adapters are
optional extras. Core does not import `vassilflow` or `app`, load the full
application's `config.yaml`, create workspaces or start background workers.

The full harness depends on core and reexports its `DanglingToolCallMiddleware`
at the existing harness import path. That recovery implementation is shared;
the full harness retains its own application orchestration and features.

## What is shared and what belongs to a domain

| Responsibility | Owner | When starting an HR project |
| --- | --- | --- |
| Agent loop, interrupted-tool recovery, model-call limit | Core package | Import `create_agent`; configure limits |
| Retrieve-then-answer flow, bounded evidence and citation ID checks | Core package | Import `RagPipeline`; supply model and retriever |
| Child task execution, timeout and concurrency limit | Core package | Use `create_subagent_tool` when delegation is needed |
| Documents, parsing, chunking, indexing and search ranking | Domain project | Replace sample policies and adapt `index.py` |
| Prompts, domain tools, model construction and composition | Domain project | Edit `prompts.py`, `models.py` and `composition.py` |
| CLI/API/UI, access control and business rules | Domain project | Extend `cli.py` or add the interface your users need |
| Domain-specific expected answers and retrieval evaluations | Domain project | Add policy-focused tests and evaluation cases |

Changing a prompt changes instructions; it does not implement a new data source,
tool, authorization check or workflow. Those changes require the corresponding
adapter and composition code. A pure RAG application can use `build_rag()` without
using the coordinator/subagent example.

## Start an HR policy project

### 1. Build core and copy the template

Use Python 3.12 or newer. From the repository root, build a distributable wheel:

```sh
python -m pip install build
python -m build backend/packages/core --outdir wheelhouse
```

Copy the clean contents of `templates/rag-agent/` into a new project directory,
such as `hr-rag/`, outside the checkout. Exclude `.venv`, caches, build outputs
and any existing `.data` directory. There is no project generator; this is an
ordinary copyable template. Keep a copy of the built core wheel in a local
wheelhouse or your internal package registry.

In the copied project's root, create and activate its own environment:

```sh
python -m venv .venv
```

On PowerShell, activate it with `.\.venv\Scripts\Activate.ps1`. On Bash, use
`source .venv/bin/activate`. If shell policy prevents activation, invoke the
environment's Python directly instead.

Still in the copied project, install the wheel and starter. Replace the wheel
path below with its actual location:

```sh
python -m pip install "/path/to/vassilflow_core-0.1.1-py3-none-any.whl"
python -m pip install -e ".[dev]"
rag-agent demo
python -m pytest -q
```

The package is not assumed to be published on PyPI. The template currently
declares `vassilflow-core>=0.1.1,<0.2.0`, so the installed wheel satisfies that
dependency. Each copied application should have its own dependency lockfile.

### 2. Replace the sample knowledge base

Replace the sample documents in the copied project's `data/` directory with
your approved HR policies. For a small fictional exercise, create
`data/annual-leave.md` containing:

```markdown
# Annual leave requests

Employees request annual leave in the HR portal. Their manager reviews the request.
```

This is demonstration data, not a statement of an organization's actual policy.
The starter reads UTF-8 `.md` and `.txt` files recursively. PDF, Office document
and HTML conversion must be added to your ingestion code if needed.

From the copied project root:

```sh
rag-agent ingest ./data --index .data/hr.sqlite3
rag-agent ask "How do employees request annual leave?" --index .data/hr.sqlite3
```

Ingestion replaces the entire selected index with a snapshot of that directory.
Reingestion does not duplicate chunks, removed files disappear, and an empty
directory clears the index. Document read failures leave the previous index
intact. The default chunks are 1,200 characters with 150 characters of overlap;
the CLI currently uses those defaults.

Search uses SQLite FTS5 lexical word matching. It does not compute embeddings or
understand equivalent wording. The index persists across processes, and the
question must retrieve relevant evidence before an answer can use it.

### 3. Set domain instructions and rules

Edit `src/domain_assistant/prompts.py` in the copied project. For example:

```python
RAG_PROMPT = """Answer employee questions using the retrieved company HR policies.
Preserve exact policy wording where dates or entitlements matter.
Do not infer eligibility or allowances absent from the evidence.
"""
```

If using the agent flow, also adapt `RESEARCH_PROMPT` and `COORDINATOR_PROMPT`.
Retain their `search_documents` and `research_assistant` references unless you
make the coordinated tool-name changes described below.

The starter records source filenames and chunk IDs. It does not parse policy
version, effective date, department or access permissions into structured
metadata, and it does not filter on those fields. If the HR application needs
those rules, add metadata during ingestion and apply the appropriate search
scope in the domain retriever. A prompt saying "use the current policy" does
not implement date filtering. A shared service must obtain its access scope
from its authenticated application context.

### 4. Select offline or live model behavior explicitly

Without `--live`, both `ask` and `agent` use `DemoModel`. It echoes the first
retrieved excerpt and follows a fixed tool sequence. It does not reason about
the question or evaluate the domain prompt. `rag-agent demo` always creates its
own temporary refund-policy example; it does not read your HR documents.

For an actual model response, install the starter's optional provider from the
copied project root:

```sh
python -m pip install -e ".[openai]"
```

Set the provider variables in the same shell. PowerShell example:

```powershell
$env:OPENAI_API_KEY = "replace-with-your-key"
$env:OPENAI_MODEL = "your-enabled-model"
```

Bash equivalent:

```bash
export OPENAI_API_KEY="replace-with-your-key"
export OPENAI_MODEL="your-enabled-model"
```

Then run from the copied project root:

```sh
rag-agent ask "How do employees request annual leave?" --index .data/hr.sqlite3 --live
```

`OPENAI_BASE_URL` can select an OpenAI-compatible endpoint. If `OPENAI_MODEL` is
unset, the current template uses `gpt-4.1-mini`; choose a model enabled by your
provider. `.env.example` documents the variables, but `.env` is not loaded
automatically. Calls without `--live` remain offline even when credentials exist.

The core's `anthropic` extra installs an adapter dependency; it does not change
the starter's `make_model()` implementation. To use another provider, construct
that provider's `BaseChatModel` in `models.py`, add its dependency and configuration,
and pass the instance through the existing composition functions.

### 5. Add delegation only when the application needs it

The copied starter already has a second flow:

```sh
rag-agent agent "How do employees request annual leave?" --index .data/hr.sqlite3 --live
```

Its coordinator can delegate a question to a research child, which can call the
retrieval tool. This composition lives in `src/domain_assistant/composition.py`.
The example gives each agent four model calls; child execution has a 60-second
timeout and at most two concurrent calls per tool instance and event loop.
The child uses `checkpointer=False` and receives its delegated task, not the
parent's conversation history. Both agent graphs in this starter are stateless.

For a straightforward policy Q&A application, the `ask` flow is sufficient.
Additional specialist agents, business tools or an HTTP endpoint require explicit
project code. Neither the template nor core supplies an HR-specific workflow.

Keep the deterministic starter tests and add cases for your domain: expected
policy retrieval, missing evidence, policy replacement and whatever access/date
rules you implement. Live model quality requires separate evaluations; the
offline fixture verifies execution and evidence plumbing.

## Replace lexical retrieval with semantic or hybrid retrieval

Core accepts an initialized LangChain `BaseRetriever` or another
`Runnable[str, list[Document]]`. Its async invocation receives the question and
returns `langchain_core.documents.Document` objects. Preserve useful identifiers
and JSON-compatible metadata so citations retain their provenance.

With your chosen model and vector store already initialized, composition can use:

```python
from vassilflow_core import RagPipeline, create_retrieval_tool

retriever = vector_store.as_retriever(search_kwargs={"k": 8})
rag = RagPipeline(
    model=model,
    retriever=retriever,
    top_k=4,
    system_prompt=RAG_PROMPT,
)
search = create_retrieval_tool(retriever, name="search_documents", top_k=4)
```

This is a composition sketch, not a store initialization recipe. The domain
project selects its embedding model, database, ingestion/update strategy,
ranking and access filters. Add those adapters' dependencies to that project.
Core's `top_k` limits included evidence; it does not configure the upstream
retriever's search count. `max_context_chars` bounds evidence JSON characters,
including metadata, rather than tokens or the complete prompt.

The current template is wired to `SqliteRetriever`, so replacing the store also
requires these project changes:

1. Implement the new ingestion and retrieval adapter in `index.py` or a new module.
2. Update `composition.py`, which currently calls `index.as_runnable()` and reads
   `index.top_k`, or retain those methods in your replacement adapter.
3. Update `cli.py`, which creates `SqliteRetriever` directly for ingestion and
   query commands. Adjust `--index` and the configuration if your store uses a
   collection, endpoint or another identifier.
4. Update domain acceptance tests and keep a deterministic local retriever for
   tests that should not depend on a database service.

No change to the core RAG flow is required when the new retriever satisfies its
contract. Changing the LLM alone does not change the retrieval algorithm.

## Rename a copied project safely

The project directory, distribution name, Python namespace, CLI command and tool
names are separate identifiers. Naming the directory `hr-rag/` does not require
renaming everything else. Separate virtual environments let multiple projects
start with the default `domain_assistant` namespace.

If you choose a complete rename, update the matching locations:

| Identifier | Locations in the copied project |
| --- | --- |
| Distribution, such as `hr-rag` | `[project].name` in `pyproject.toml` |
| Python namespace, such as `hr_assistant` | Rename `src/domain_assistant/`; update imports, the Hatch wheel package path, the CLI script target and test subprocess module names |
| CLI command, such as `hr-rag` | Change the key under `[project.scripts]`; update documentation and CLI command strings in error messages |
| Research tool/agent names | Update `composition.py`, prompt references, the offline model, source collection and tests together |

Two name-sensitive implementation details matter: `DemoModel` uses a `task`
argument only for the exact tool name `research_assistant` and otherwise emits
`query`. `collect_agent_sources()` accepts child artifacts from `search_documents`
only. Renaming either tool without updating those functions can break the demo
or omit returned sources. The offline model is deliberately specific to this
starter, not a generic model simulator.

Reinstall the copied project after changing packaging or script entries, then
rerun its tests and CLI demo. Keep `vassilflow_core` and the `vassilflow-core`
dependency unchanged; those identify the shared library.

## Interpret citations correctly

`RagPipeline` returns answer text, source records and cited source IDs. It checks
the model's citation markers against the provided evidence and accepts an
explicit insufficient-evidence response. With no usable evidence, it returns
that response without calling the model. Identifier validation does not prove
that every claim follows from the cited text.

The agent example preserves retrieval artifacts from the child. Its output
includes filename, excerpt and a scope for each source:

```text
(scope.invocation_id, scope.tool_call_id, citation_id)
```

`S1` is local to one retrieval result. Several searches can each return a
different `S1`. The one-search offline demo has an unambiguous source; a live
agent may make several searches. Its final prose is not automatically mapped
to those scopes or validated by `RagPipeline`. An application synthesizing
multiple results must define unique citation labels and validate that mapping.

## Update shared code and domain projects

A core release changes the installed package only when each consuming project
updates its version/lock and installs the new distribution. Build the new wheel,
review compatibility, update the dependency as needed and run that project's
tests before deploying it. A source edit in the original checkout does not
change applications installed from older wheels.

The template is copied code. Updating `templates/rag-agent/` does not modify
existing domain projects, and updating the core package does not rewrite their
prompts, ingestion, CLI or tests. Port useful template changes deliberately while
preserving each project's domain behavior.

To validate a core release and a fresh copied template, use
[`scripts/check_core_distribution.py`](../../scripts/check_core_distribution.py)
with a built wheel installed with its `test` extra in a disposable core-only
environment. The script installs the copied template into that same environment
and runs it outside the checkout with `PYTHONPATH` cleared. It makes no live
model calls. This distribution check complements the consuming project's own
domain tests; it does not evaluate that project's retrieval quality or policies.
