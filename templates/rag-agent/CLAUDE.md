# Starter development guide

This is a standalone domain application, not part of the legacy backend runtime.
Keep prompts, ingestion and domain tools here; import reusable agent and RAG
primitives from `vassilflow_core`. Never import the full `vassilflow` harness or
`app.*`, and do not add a monorepo-relative dependency to `pyproject.toml`.

Validate from this directory with `python -m pytest -q` and `rag-agent demo`.
All default examples and tests are deterministic and offline. Optional provider
imports belong inside `make_model(live=True)` so the base installation remains
usable without a provider SDK. Updating code also requires keeping this guide and
README instructions aligned.

The local retriever intentionally uses SQLite FTS5 lexical search. Its complete
snapshot ingestion streams chunks into one rollback-safe transaction and removes
stale documents atomically. It retains one file's text and the sorted path list,
not every corpus chunk. `RunnableLambda` offloads
sync retrieval for async callers. The `DemoModel` is a test fixture that echoes
evidence and follows a fixed tool sequence; never describe it as semantic search
or an actual LLM. Child agents must retain `checkpointer=False` so parent graph
checkpoints cannot leak into delegated invocations.
Delegated children cannot use static breakpoints, and dynamic interrupts must
surface as errors instead of completed drafts. Delegation timeouts are cooperative:
cleanup may delay return, and synchronous executor work can outlive cancellation.
Keep underlying I/O timeouts and resource controls in the domain adapters.

Agent source output comes from delegation `tool_artifacts`, with source identity
scoped by child `invocation_id` and retrieval `tool_call_id`. Never deduplicate
sources by `S1` alone. The demo tests prove provenance survives delegation and
separate invocations keep separate scopes; they do not establish semantic
validation of a live agent's final answer.

When renaming the project namespace, update imports, the Hatch wheel package
path, console script target and test subprocess module names together. Tool names
also affect behavior: `DemoModel` distinguishes `research_assistant` from retrieval
by name, and `collect_agent_sources` accepts `search_documents`. Keep those names,
their input schemas, prompts and tests aligned. Domain metadata and access/date
filters must be implemented explicitly in the adapter; they are not supplied by
prompt changes. Keep this copied template's documentation self-contained.
