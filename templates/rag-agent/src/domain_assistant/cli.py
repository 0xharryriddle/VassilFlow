"""CLI for ingestion, cited RAG and bounded subagent delegation."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

from domain_assistant.composition import build_agent, build_rag
from domain_assistant.index import SqliteRetriever
from domain_assistant.models import make_model


async def answer_question(question: str, index: SqliteRetriever, *, live: bool = False) -> dict[str, Any]:
    answer = await build_rag(make_model(live=live), index).ainvoke(question)
    return {
        "mode": "live" if live else "offline evidence echo (no language reasoning)",
        "answer": answer.text,
        "sources": [source.to_dict() for source in answer.sources],
        "cited_source_ids": list(answer.cited_source_ids),
    }


async def run_agent(question: str, index: SqliteRetriever, *, live: bool = False) -> dict[str, Any]:
    result = await build_agent(make_model(live=live), index).ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config={"recursion_limit": 20},
    )
    return {
        "mode": "live" if live else "offline scripted delegation (no language reasoning)",
        "answer": result["messages"][-1].content,
        "delegations": [message.name for message in result["messages"] if isinstance(message, ToolMessage)],
        "sources": collect_agent_sources(result["messages"]),
    }


def collect_agent_sources(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Preserve retrieval provenance without treating repeated S1 as one source.

    The citation key is (invocation_id, tool_call_id, citation_id). Keeping these
    records does not validate which retrieval the parent's final prose refers to.
    """
    sources = []
    for message in messages:
        if not isinstance(message, ToolMessage) or not isinstance(message.artifact, dict):
            continue
        delegation = message.artifact
        invocation_id = delegation.get("invocation_id")
        if not isinstance(invocation_id, str) or not invocation_id:
            continue
        for tool_result in delegation.get("tool_artifacts", []):
            if tool_result.get("tool_name") != "search_documents":
                continue
            artifact = tool_result.get("artifact")
            if not isinstance(artifact, dict):
                continue
            scope = {"invocation_id": invocation_id, "tool_call_id": tool_result["tool_call_id"]}
            for source in artifact.get("sources", []):
                sources.append({**source, "scope": dict(scope)})
    return sources


async def demo() -> dict[str, Any]:
    """Run both complete paths against a temporary, deterministic knowledge base."""
    with tempfile.TemporaryDirectory(prefix="rag-agent-demo-") as directory:
        root = Path(directory)
        documents = root / "documents"
        documents.mkdir()
        (documents / "refunds.md").write_text(
            "Refunds are available within 30 days of purchase. Keep the receipt.", encoding="utf-8"
        )
        index = SqliteRetriever(root / "index.sqlite3")
        count = await asyncio.to_thread(index.ingest, documents)
        question = "What is the refund policy for refunds?"
        return {
            "indexed_chunks": count,
            "rag": await answer_question(question, index),
            "agent": await run_agent(question, index),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Replace a local index from UTF-8 .md and .txt files")
    ingest.add_argument("directory", type=Path)
    ingest.add_argument("--index", type=Path, default=Path(".data/index.sqlite3"))
    for name in ("ask", "agent"):
        command = commands.add_parser(name)
        command.add_argument("question")
        command.add_argument("--index", type=Path, default=Path(".data/index.sqlite3"))
        command.add_argument("--live", action="store_true", help="Call the explicitly configured live model")
    commands.add_parser("demo", help="Run offline RAG and subagent examples without credentials")
    arguments = parser.parse_args()
    try:
        if arguments.command == "demo":
            result = asyncio.run(demo())
        elif arguments.command == "ingest":
            count = SqliteRetriever(arguments.index).ingest(arguments.directory)
            result = {"indexed_chunks": count, "index": str(arguments.index), "retrieval": "SQLite FTS5 lexical"}
        else:
            action = answer_question if arguments.command == "ask" else run_agent
            result = asyncio.run(action(arguments.question, SqliteRetriever(arguments.index), live=arguments.live))
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
