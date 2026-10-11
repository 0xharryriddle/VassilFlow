"""Small persistent lexical retriever; no embedding model or vector service.

The SQLite FTS5 index matches words, not semantic similarity. Replace this adapter
with your vector-store retriever when the domain needs semantic retrieval.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda


class SqliteRetriever:
    def __init__(self, path: str | Path, *, top_k: int = 4):
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.path = Path(path)
        self.top_k = top_k

    def ingest(self, directory: str | Path, *, chunk_size: int = 1200, overlap: int = 150) -> int:
        """Atomically replace the index with this directory's UTF-8 .md/.txt files.

        Repeated ingestion is idempotent; deleted files disappear on the next run.
        A failed read leaves the existing index unchanged.
        """
        if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
            raise ValueError("Require chunk_size > overlap >= 0")
        root = Path(directory).resolve()
        if not root.is_dir():
            raise ValueError(f"Document directory does not exist: {root}")
        count = 0

        def rows() -> Iterator[tuple[str, str, str]]:
            nonlocal count
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
                    continue
                source = path.relative_to(root).as_posix()
                content = path.read_text(encoding="utf-8").strip()
                for start in range(0, len(content), chunk_size - overlap):
                    text = content[start : start + chunk_size].strip()
                    if text:
                        chunk_id = hashlib.sha256(f"{source}:{start}:{text}".encode()).hexdigest()[:24]
                        count += 1
                        yield chunk_id, source, text
                    if start + chunk_size >= len(content):
                        break

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            try:
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks "
                    "USING fts5(chunk_id UNINDEXED, source UNINDEXED, text, tokenize='unicode61')"
                )
            except sqlite3.OperationalError as exc:
                raise RuntimeError("This starter requires Python with SQLite FTS5 support") from exc
            connection.execute("DELETE FROM chunks")
            # Consume one document at a time inside the transaction. A late read
            # or insert failure rolls back both deletion and inserted chunks.
            connection.executemany("INSERT INTO chunks (chunk_id, source, text) VALUES (?, ?, ?)", rows())
        return count

    def search(self, question: str) -> list[Document]:
        """Return the best lexical matches; user input cannot become FTS syntax."""
        if not self.path.is_file():
            raise FileNotFoundError(f"Index not found: {self.path}. Run 'rag-agent ingest' first.")
        terms = list(dict.fromkeys(re.findall(r"[^\W_]+", question.casefold())))[:64]
        if not terms:
            return []
        expression = " OR ".join(f'"{term[:256]}"' for term in terms)
        # The callable is wrapped in RunnableLambda, whose async path offloads
        # this synchronous SQLite operation to a worker thread.
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                "SELECT chunk_id, source, text FROM chunks WHERE chunks MATCH ? "
                "ORDER BY bm25(chunks), chunk_id LIMIT ?",
                (expression, self.top_k),
            ).fetchall()
        return [
            Document(id=chunk_id, page_content=text, metadata={"source": source, "chunk_id": chunk_id})
            for chunk_id, source, text in rows
        ]

    def as_runnable(self) -> RunnableLambda:
        return RunnableLambda(self.search)
