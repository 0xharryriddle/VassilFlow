# Domain RAG and agent starter

Copy this directory for each new domain. This project owns the data, prompts,
retrieval adapter and composition; the reusable runtime comes from the versioned
`vassilflow-core` dependency. It needs Python 3.12+ and SQLite with FTS5 support.

The source repository's `backend/docs/FOUNDATION.md` contains the full source
structure and an HR adaptation walkthrough. This README is self-contained for
projects copied or extracted from the template archive.

## Install

Run these commands inside your copied project, after obtaining a built
`vassilflow_core` wheel. The core is not assumed to be published on PyPI.

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install /path/to/vassilflow_core-0.1.1-py3-none-any.whl
python -m pip install -e ".[dev]"
rag-agent demo
python -m pytest -q
```

Once the core is available on your package index, the wheel-install step can be
replaced by the normal dependency resolution of `pip install -e ".[dev]"`.
Resolve and commit a lockfile in the copied application according to your team's
deployment workflow. Do not replace the core dependency with copied source files.

## Ingest and ask

```sh
rag-agent ingest ./data --index .data/index.sqlite3
rag-agent ask "What is the refund policy for refunds?" --index .data/index.sqlite3
rag-agent agent "What is the refund policy for refunds?" --index .data/index.sqlite3
```

`ingest` chunks UTF-8 `.md` and `.txt` files and atomically replaces the local
SQLite index with the directory's current contents. Reingestion does not create
duplicates; removed files disappear. An empty directory intentionally clears the
index. A document read failure preserves the previous index. Conversion of PDF,
Office documents or HTML belongs in your domain's ingestion step.
Chunks are inserted incrementally inside one transaction rather than retained
for the whole corpus; the adapter still reads each individual file into memory
and sorts its file paths. Failed reads or inserts roll back the entire replacement.

Retrieval uses **lexical word matching with SQLite FTS5**, not embeddings or
semantic similarity. The index persists across processes. For semantic retrieval,
replace `SqliteRetriever.as_runnable()` with your own
`Runnable[str, list[Document]]`; preserve useful source metadata on each document.
Update `composition.py` and the direct `SqliteRetriever` construction/ingestion
in `cli.py`, or retain the adapter methods they require. The starter does not
implement policy-date, department or access filters; add those in your domain.

By default the CLI uses `DemoModel`, a deterministic fixture that echoes the first
retrieved excerpt with its citation. It demonstrates execution and sources; it
does not perform language reasoning. `demo` creates temporary sample data, runs
both flows and removes its temporary index, without reading a repository config
or requiring API credentials.

The `ask` flow calls `RagPipeline`, returns sources as JSON and validates citation
identifiers. The `agent` flow demonstrates a coordinator delegating to one
research subagent, which calls the retrieval tool. It preserves the child's
answer and returns its retrieval source records with filename, excerpt and scope.
The source key is `(scope.invocation_id, scope.tool_call_id, citation_id)`.
`[S1]` is local to one retrieval result: two child calls or two searches may both
return an `S1` referring to different documents. Preserve the scope when storing
or displaying citations; do not merge sources globally by `citation_id`.

The offline agent demo performs one search, so its `[S1]` resolves to the one
returned source. A live agent may perform multiple searches. Its final prose is
not automatically mapped to those scopes, nor checked for citation correctness
or factual support. If your application combines results, remap citations to
unique identifiers before synthesis and validate the result. Use the structured
`ask` flow for citation identifier validation; that validation also does not
prove that the cited evidence supports every claim.

## Use a live model

Install the optional provider:

```sh
python -m pip install -e ".[openai]"
```

Set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` and `OPENAI_BASE_URL` in your
shell, then run `rag-agent ask "your question" --live` or
`rag-agent agent "your question" --live`. The default model identifier is
`gpt-4.1-mini`; choose a model enabled by your provider. The `.env.example` file
documents variables; the application does not load `.env` automatically.
Calls without `--live` remain offline even when credentials exist.

## Adapt to a domain

| File | Project responsibility |
| --- | --- |
| `data/` | Example source documents; replace with domain material |
| `src/domain_assistant/prompts.py` | RAG, research and coordinator instructions |
| `src/domain_assistant/index.py` | Ingestion, chunking and retrieval adapter |
| `src/domain_assistant/models.py` | Model provider construction and offline fixture |
| `src/domain_assistant/composition.py` | Tools, RAG and subagent wiring |
| `src/domain_assistant/cli.py` | Local application interface |
| `tests/test_starter.py` | Offline end-to-end acceptance tests |

The research child uses `checkpointer=False`, receives only its delegated task,
and has retrieval access only. The example configures four model calls per agent,
two concurrent child tasks, a 60-second child timeout and explicit graph recursion
limits. Prompts and retrieval tools should remain specific to your project.
Child graphs must finish without static breakpoints or dynamic interrupts;
interrupted drafts are not completed answers. The timeout requests cooperative
cancellation, so awaited cleanup may delay its return. The concurrency limit
covers awaiting child calls; executor-backed synchronous work, including this
starter's SQLite adapter, can continue after cancellation. Configure I/O timeouts
and resource limits in any replacement adapter that needs stricter guarantees.
Add an API, persistent conversations or another store only when your application
needs them.

For an HR project, replace the sample data with approved policy files, update
`RAG_PROMPT` and any agent prompts, ingest those files and use `ask --live` for an
actual model answer. `demo` continues to use its built-in temporary refund data.
Add ingestion metadata and retriever filters for policy dates, departments or
document access when those rules are required; editing a prompt does not implement
them. Keep project-specific evaluation cases alongside the starter tests.

If renaming the Python namespace, update its imports, the Hatch wheel package
path, script target and test subprocess module names. Tool names also have code
dependencies: `DemoModel` uses `task` only for `research_assistant`, and the CLI
source collector accepts `search_documents`. Update those functions, prompts and
tests together when renaming tools. A copied template is project-owned code;
upgrading `vassilflow-core` does not rewrite it.

The copied project installs no Gateway, browser UI, channels, sandbox or host-shell
tools. The SQLite adapter has no tenant or document authorization layer; a shared
service must apply your application's access scope before returning documents.
