#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite + FTS5 storage for the build-knowledge-base skill."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from utils import sanitize_obj, tokenize_for_fts, write_jsonl

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_hash TEXT,
    title TEXT,
    format TEXT,
    parse_method TEXT,
    unit_type TEXT,
    unit_count INTEGER,
    char_count INTEGER,
    language TEXT,
    created_at TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT,
    char_count INTEGER,
    chunk_type TEXT,
    heading_path TEXT,
    page_start INTEGER,
    page_end INTEGER,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(chunk_type);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content_tokens,
    heading_path,
    doc_id UNINDEXED,
    chunk_id UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_document(conn: sqlite3.Connection, doc: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO documents
        (doc_id, source_path, source_hash, title, format, parse_method, unit_type,
         unit_count, char_count, language, created_at, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc["doc_id"],
            doc["source_path"],
            doc.get("metadata", {}).get("source_hash"),
            doc.get("title"),
            doc.get("format"),
            doc.get("parse_method"),
            doc.get("unit_type"),
            doc.get("unit_count"),
            doc.get("char_count"),
            doc.get("language"),
            doc.get("created_at"),
            json.dumps(sanitize_obj(doc.get("metadata", {})), ensure_ascii=False),
        ),
    )


def delete_document_chunks(conn: sqlite3.Connection, doc_id: str) -> None:
    """Remove a document's chunks before re-ingesting so stale chunks do not survive."""
    conn.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
    conn.commit()


def insert_chunks(conn: sqlite3.Connection, chunks: Iterable[dict[str, Any]]) -> int:
    chunks = list(chunks)
    count = 0
    chunk_ids = []
    for ch in chunks:
        chunk_ids.append(ch["chunk_id"])
        conn.execute(
            """
            INSERT OR REPLACE INTO chunks
            (chunk_id, doc_id, chunk_index, content, content_hash, char_count,
             chunk_type, heading_path, page_start, page_end, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ch["chunk_id"],
                ch["doc_id"],
                ch["chunk_index"],
                ch["content"],
                ch.get("content_hash"),
                ch.get("char_count"),
                ch.get("chunk_type"),
                " > ".join(ch.get("heading_path") or []),
                ch.get("page_start"),
                ch.get("page_end"),
                json.dumps(sanitize_obj(ch.get("metadata", {})), ensure_ascii=False),
            ),
        )
        count += 1

    # Remove stale FTS rows for the same chunk ids before re-inserting.
    if chunk_ids:
        for batch_start in range(0, len(chunk_ids), 500):
            batch = chunk_ids[batch_start:batch_start + 500]
            placeholders = ",".join("?" for _ in batch)
            conn.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", batch)
        for ch in chunks:
            conn.execute(
                "INSERT INTO chunks_fts (content_tokens, heading_path, doc_id, chunk_id) VALUES (?, ?, ?, ?)",
                (
                    tokenize_for_fts(ch["content"]),
                    " > ".join(ch.get("heading_path") or []),
                    ch["doc_id"],
                    ch["chunk_id"],
                ),
            )
    conn.commit()
    return count


def query_fts(conn: sqlite3.Connection, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    tokens = tokenize_for_fts(query).split()
    if not tokens:
        return []
    # OR keeps recall high for long questions; BM25 still ranks exact-term hits first.
    match = " OR ".join(f'"{t.replace(chr(34), "")}"' for t in tokens if t)
    if not match:
        return []
    sql = """
        SELECT c.chunk_id, c.doc_id, c.chunk_index, c.content, c.heading_path,
               c.page_start, c.page_end, c.chunk_type, c.char_count,
               bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
        WHERE chunks_fts MATCH ?
        ORDER BY score
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, (match, top_k)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    chars = conn.execute("SELECT COALESCE(SUM(char_count), 0) FROM chunks").fetchone()[0]
    by_type = {
        row["chunk_type"]: row["n"]
        for row in conn.execute(
            "SELECT chunk_type, COUNT(*) AS n FROM chunks GROUP BY chunk_type ORDER BY n DESC"
        ).fetchall()
    }
    return {
        "documents": docs,
        "chunks": chunks,
        "total_chars": chars,
        "avg_chars": round(chars / chunks, 1) if chunks else 0,
        "chunks_by_type": by_type,
    }


def export_chunks_jsonl(chunks: Iterable[dict[str, Any]], path: str | Path) -> int:
    return write_jsonl(path, chunks)


def rebuild_fts(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM chunks_fts")
    rows = conn.execute("SELECT chunk_id, doc_id, content, heading_path FROM chunks").fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO chunks_fts (content_tokens, heading_path, doc_id, chunk_id) VALUES (?, ?, ?, ?)",
            (
                tokenize_for_fts(row["content"]),
                row["heading_path"] or "",
                row["doc_id"],
                row["chunk_id"],
            ),
        )
    conn.commit()
    return len(rows)
