"""Compose shared runtime primitives with this project's own domain choices."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from vassilflow_core import RagPipeline, create_agent, create_retrieval_tool, create_subagent_tool

from domain_assistant.index import SqliteRetriever
from domain_assistant.prompts import COORDINATOR_PROMPT, RAG_PROMPT, RESEARCH_PROMPT


def build_rag(model: BaseChatModel, index: SqliteRetriever) -> RagPipeline:
    return RagPipeline(model=model, retriever=index.as_runnable(), top_k=index.top_k, system_prompt=RAG_PROMPT)


def build_agent(model: BaseChatModel, index: SqliteRetriever):
    """Coordinator → isolated research subagent → retrieval tool.

    The child owns only retrieval access. It has no inherited chat history or
    persistent checkpoint, and receives the task explicitly supplied by its parent.
    """
    retrieval = create_retrieval_tool(index.as_runnable(), name="search_documents", top_k=index.top_k)
    research = create_agent(
        model=model,
        tools=[retrieval],
        system_prompt=RESEARCH_PROMPT,
        checkpointer=False,
        max_model_calls=4,
    )
    delegate = create_subagent_tool(
        name="research_assistant",
        description="Research a knowledge-base question and return an answer with source citations.",
        agent=research,
        max_concurrency=2,
        timeout_seconds=60,
        recursion_limit=20,
    )
    return create_agent(
        model=model,
        tools=[delegate],
        system_prompt=COORDINATOR_PROMPT,
        checkpointer=False,
        max_model_calls=4,
    )
