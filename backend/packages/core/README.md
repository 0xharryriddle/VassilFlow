# VassilFlow Core

Build a domain RAG pipeline, an agent, or a small delegated team without running
the VassilFlow web application. Models, retrievers, tools, prompts and persistence
are supplied by the consuming project. Importing the package does not load YAML,
create workspaces, read credentials, or start background workers.

In a source checkout, `backend/docs/FOUNDATION.md` explains the shared/domain
source structure and walks through an HR policy project. This package README
is the standalone reference for its runtime APIs and installation.

The mandatory dependencies are LangChain, LangChain Core, LangGraph and Pydantic.
Provider SDKs, database drivers, FastAPI, Kubernetes, document conversion, MCP,
sandbox services, UI and messaging channels are not mandatory core dependencies.
LangChain's own transitive dependencies still apply; this is a focused Python
library, not a zero-dependency runtime.

## Install and reuse

Python 3.12 or newer is required. From a source checkout:

```bash
python -m pip install ./backend/packages/core
```

Build a versioned wheel from the repository root:

```bash
uv build --project backend/packages/core --out-dir dist
```

Install the resulting wheel in each domain project's own environment. This source
change does not publish a package to PyPI. For local releases, keep the wheel in
a wheelhouse or internal package registry and pin/update its version per project.
Optional extras `openai`, `anthropic`, and `sqlite` install upstream model or
checkpoint adapters; the caller still constructs those adapters explicitly.

Copy the repository's `templates/rag-agent` directory to start a separate domain
project. Its README explains installation from a local core wheel, offline demo,
ingestion, live model configuration, and replacing lexical retrieval with a
vector/hybrid retriever. The template never imports the full application harness.

## A RAG pipeline

```python
from vassilflow_core import RagPipeline

# model: an initialized langchain_core.language_models.BaseChatModel
# retriever: BaseRetriever, or Runnable[str, list[Document]]
rag = RagPipeline(
    model=model,
    retriever=retriever,
    top_k=4,
    max_context_chars=12_000,
    system_prompt="Answer questions about our product's support policies.",
)
answer = await rag.ainvoke("What is the refund policy?")
print(answer.text)
print([source.to_dict() for source in answer.sources])
```

The pipeline retrieves documents, deduplicates them, bounds the complete evidence
JSON, and asks the model to answer with `[S1]`-style citations. Source records keep
the original document ID, detached metadata and the actual excerpt included in
context. No usable evidence means no model call. Missing, malformed or unknown
citation IDs raise `CitationError`; an explicit insufficient-evidence answer is
allowed. An unfinished model response containing tool calls raises `ValueError`.
Citation validation establishes provenance IDs, not semantic entailment or the
truth of every model claim. Numeric source-like markers are reserved for citations;
unrelated bracketed domain text such as SQL identifiers `[Sales].[Orders]` remains
ordinary text. Use separate exact markers (`[S1] [S2]`), not grouped citations.

`top_k` caps included sources, not the retriever's upstream search request. Configure
ranking, search limits and access filters on the retriever. The evidence budget is
in characters, including escaped JSON and metadata, not tokens or total prompt
length. Retrieval and model errors/cancellation propagate to the caller.
The pipeline owns a native Runnable tracing root: a caller's `run_id` identifies
that root, and retrieval/model calls receive distinct child IDs. Tags, metadata
and public configurable values continue to reach the injected components.

Ingestion, embedding models, vector databases, document parsers, domain schemas
and authorization filters belong to the consuming project or its adapters. The
pipeline uses ordinary LangChain interfaces so those choices can change without
rewriting the RAG flow.

## An agent that can retrieve

```python
from vassilflow_core import create_agent, create_retrieval_tool

search = create_retrieval_tool(retriever, name="search_knowledge")
agent = create_agent(
    model=model,
    tools=[search],
    system_prompt="Use search_knowledge for policy questions and cite the evidence.",
    max_model_calls=20,
)
result = await agent.ainvoke({"messages": [("user", "What is the refund policy?")]})
print(result["messages"][-1].text)
```

`create_agent` returns a native compiled LangGraph graph with `invoke`, `ainvoke`,
`stream`, `astream`, callbacks and optional injected checkpointers. It defaults to
interrupted-tool-call recovery and a per-invocation model-call limit. Exceeding
the limit raises LangChain's `ModelCallLimitExceededError`. It does not enforce a
token budget or wall-clock timeout; caller middleware and invocation config can
add controls. Async-only tools require the async graph APIs.

The retrieval tool has a `query` input and returns bounded evidence plus source
artifacts. Citation markers are scoped to that tool result. An arbitrary agent's
final response is not automatically checked by the standalone RAG validator.

## Explicit subagents

```python
from vassilflow_core import create_agent, create_subagent_tool

researcher = create_agent(
    model=research_model,
    tools=[search],
    system_prompt="Find the relevant policy and report the evidence.",
    checkpointer=False,
    max_model_calls=8,
)
delegate = create_subagent_tool(
    name="research_policy",
    description="Delegate a policy research task.",
    agent=researcher,
    max_concurrency=2,
    timeout_seconds=60,
    recursion_limit=40,
)
coordinator = create_agent(model=model, tools=[delegate])
result = await coordinator.ainvoke({"messages": [("user", "Research our refund policy.")]})
```

Delegation supplies only the task as the child's initial conversation, forwards
explicit runtime context and tracing, and excludes parent checkpoint identifiers.
The child must be compiled with `checkpointer=False`; persistent children are
rejected instead of accidentally sharing parent state. Graphs with static
breakpoints, including explicit nested graph nodes, are rejected at construction;
a dynamic interrupt raises `ValueError` instead of returning a draft as completed.
This helper does not resume children. Arbitrary Python nodes can conceal graph
calls from inspection; their authors must propagate incomplete outcomes instead
of returning a previous draft as the final answer.

Timeout includes waiting for the concurrency slot and requests cooperative
cancellation. Awaited cleanup may delay when the timeout reaches the caller.
Concurrency bounds awaiting invocations per tool instance per event loop.
Synchronous work running in an executor cannot be forcibly stopped and may
continue after its slot is released; those integrations must enforce their own
I/O deadlines and resource limits. Cancellation and child errors propagate;
no global scheduler or task registry is created. This is in-process delegation,
not a durable/distributed job queue.

The returned `ToolMessage.artifact` keeps `agent`, `invocation_id`, completion
status, token usage (when supplied by the model), and the child's `tool_artifacts`.
Each entry retains `tool_name`, `tool_call_id` and its original artifact. Scope
retrieval citations by `(invocation_id, tool_call_id, citation_id)`; `S1` alone
is not globally unique. Only final assistant text reaches the parent model.
Applications must map citation scopes before synthesizing across several searches;
this helper preserves evidence but does not validate an agent's final citations.
Custom tool artifacts can contain arbitrary Python values; callers own external
serialization.

## Package boundaries

The full `vassilflow-harness` remains the application layer for skills, sandbox,
personal agents, memory, streaming service and product integrations. Core never
imports `vassilflow` or `app`. The full harness reuses core's interrupted-tool
recovery through its original import path. Other application behavior is retained.

Core intentionally has no global domain registry. Each project constructs its own
model, retriever, tools, prompts, context and storage. For an authenticated server,
enforce access control in the server and retriever; an agent prompt is not an
authorization boundary.

## Validation

Install core with its `test` extra in an isolated environment, then run this
package's `tests` with `--confcutdir` pointing at this directory. These tests are
separate from the full app's global test fixtures. CI also builds a wheel, installs
only that wheel's dependencies, and runs the copied template outside the monorepo.
All core/template tests use deterministic local models; live model quality and
provider compatibility require the consuming project's own evaluations.
