"""Offline acceptance tests for the copied domain project."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from vassilflow_core.rag import NO_CONTEXT_ANSWER

from domain_assistant.cli import answer_question, demo, run_agent
from domain_assistant.index import SqliteRetriever
from domain_assistant.models import make_model


@pytest.fixture
def index(tmp_path: Path) -> SqliteRetriever:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "refunds.md").write_text("Refunds are available within 30 days of purchase.", encoding="utf-8")
    (documents / "hours.txt").write_text("Support hours are Monday through Friday.", encoding="utf-8")
    retriever = SqliteRetriever(tmp_path / "index.sqlite3")
    assert retriever.ingest(documents) == 2
    return retriever


def test_index_survives_reopen_and_reingest_removes_deleted_documents(index: SqliteRetriever, tmp_path: Path):
    reopened = SqliteRetriever(index.path)
    results = reopened.search("refunds")
    assert len(results) == 1
    assert results[0].metadata["source"] == "refunds.md"
    assert reopened.ingest(tmp_path / "documents") == 2
    assert reopened.search("refunds")[0].metadata["chunk_id"] == results[0].metadata["chunk_id"]
    (tmp_path / "documents" / "refunds.md").unlink()
    assert reopened.ingest(tmp_path / "documents") == 1
    assert reopened.search("refunds") == []


def test_invalid_document_does_not_destroy_existing_index(index: SqliteRetriever, tmp_path: Path):
    (tmp_path / "documents" / "bad.txt").write_bytes(b"\xff\xfe\xfa")
    with pytest.raises(UnicodeDecodeError):
        index.ingest(tmp_path / "documents")
    assert "30 days" in index.search("refunds")[0].page_content


def test_late_ingestion_failure_rolls_back_already_written_replacement_chunks(index: SqliteRetriever, tmp_path: Path):
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    (replacement / "a-valid.md").write_text("Replacement-only knowledge. " * 200, encoding="utf-8")
    (replacement / "z-bad.txt").write_bytes(b"\xff\xfe\xfa")

    with pytest.raises(UnicodeDecodeError):
        index.ingest(replacement)

    reopened = SqliteRetriever(index.path)
    assert "30 days" in reopened.search("refunds")[0].page_content
    assert reopened.search("replacement") == []


def test_empty_ingestion_removes_previous_snapshot(index: SqliteRetriever, tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert index.ingest(empty) == 0
    assert SqliteRetriever(index.path).search("refunds") == []


def test_query_operators_are_treated_as_words(index: SqliteRetriever):
    assert index.search('refunds") OR ("anything*:')
    assert index.search('"*()') == []
    assert len(index.search("refunds")) == 1


def test_rag_returns_real_retrieved_source_and_citation(index: SqliteRetriever):
    response = asyncio.run(answer_question("refunds", index))
    assert "30 days" in response["answer"]
    assert response["cited_source_ids"] == ["S1"]
    assert response["sources"][0]["metadata"]["source"] == "refunds.md"
    assert response["sources"][0]["content"] == "Refunds are available within 30 days of purchase."


def test_no_match_abstains(index: SqliteRetriever):
    response = asyncio.run(answer_question("astronomy", index))
    assert response["answer"] == NO_CONTEXT_ANSWER
    assert response["sources"] == []
    assert response["cited_source_ids"] == []


def test_agent_delegates_and_preserves_research_answer(index: SqliteRetriever):
    response = asyncio.run(run_agent("refunds", index))
    assert response["delegations"] == ["research_assistant"]
    assert "30 days" in response["answer"]
    assert "[S1]" in response["answer"]
    source = response["sources"][0]
    assert source["citation_id"] == "S1"
    assert source["metadata"]["source"] == "refunds.md"
    assert source["content"] == "Refunds are available within 30 days of purchase."
    assert source["scope"]["invocation_id"]
    assert source["scope"]["tool_call_id"] == "demo-call"


def test_repeated_citation_ids_keep_distinct_invocation_scopes(index: SqliteRetriever):
    refunds = asyncio.run(run_agent("refunds", index))
    hours = asyncio.run(run_agent("hours", index))
    first = refunds["sources"][0]
    second = hours["sources"][0]
    assert first["citation_id"] == second["citation_id"] == "S1"
    assert first["scope"]["tool_call_id"] == second["scope"]["tool_call_id"] == "demo-call"
    assert first["scope"]["invocation_id"] != second["scope"]["invocation_id"]
    assert first["metadata"]["source"] == "refunds.md"
    assert second["metadata"]["source"] == "hours.txt"


def test_installed_cli_runs_outside_source_checkout(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, "-m", "domain_assistant.cli", "demo"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    output = json.loads(result.stdout)
    assert output["indexed_chunks"] == 1
    assert output["rag"]["cited_source_ids"] == ["S1"]
    assert output["agent"]["delegations"] == ["research_assistant"]
    assert output["agent"]["sources"][0]["metadata"]["source"] == "refunds.md"
    assert "30 days" in output["agent"]["sources"][0]["content"]
    assert output["agent"]["sources"][0]["scope"]["invocation_id"]


def test_demo_is_self_contained_without_config_or_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("VASSILFLOW_CONFIG_PATH", str(tmp_path / "missing-config.yaml"))
    output = asyncio.run(demo())
    assert "30 days" in output["rag"]["answer"]
    assert "30 days" in output["agent"]["answer"]
    assert list(tmp_path.iterdir()) == []


def test_live_requires_explicit_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        make_model(live=True)
