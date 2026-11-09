"""Ingest contract: what the database must contain after insert_chunks.

The historical trap is a silent mismatch between the chunk table and the FTS
table: chunks present but unsearchable, or stale FTS rows surviving a re-ingest.
Every case below uses a temporary database, so no real index is touched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from store import (
    delete_document_chunks,
    get_stats,
    init_db,
    insert_chunks,
    insert_document,
    query_fts,
)


def make_chunk(chunk_id: str, content: str, heading: list[str], doc_id: str = "doc1", index: int = 1) -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "chunk_index": index,
        "content": content,
        "content_hash": f"hash-{chunk_id}",
        "char_count": len(content),
        "chunk_type": "hierarchical",
        "heading_path": heading,
        "page_start": 10,
        "page_end": 11,
        "metadata": {"source": "test"},
    }


def make_doc(doc_id: str = "doc1") -> dict:
    return {
        "doc_id": doc_id,
        "source_path": "test.pdf",
        "source_hash": "abc",
        "title": "测试教材",
        "format": "pdf",
        "parse_method": "pymupdf",
        "unit_type": "page",
        "unit_count": 20,
        "char_count": 1000,
        "language": "zh",
        "metadata": {},
    }


@pytest.fixture()
def conn(tmp_dir: Path) -> sqlite3.Connection:
    connection = init_db(tmp_dir / "kb.sqlite")
    insert_document(connection, make_doc())
    yield connection
    connection.close()


def test_rows_match_input(conn: sqlite3.Connection) -> None:
    chunks = [
        make_chunk("c1", "进程是程序的一次执行过程。", ["第2章", "2.1 进程"]),
        make_chunk("c2", "死锁需要四个必要条件。", ["第3章", "3.5 死锁"]),
    ]
    assert insert_chunks(conn, chunks) == 2
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 2


def test_heading_path_is_joined_with_separator(conn: sqlite3.Connection) -> None:
    insert_chunks(conn, [make_chunk("c1", "正文内容。", ["第2章", "2.1 进程", "2.1.1 定义"])])
    heading = conn.execute("SELECT heading_path FROM chunks WHERE chunk_id='c1'").fetchone()[0]
    assert heading == "第2章 > 2.1 进程 > 2.1.1 定义"


def test_fragment_is_stored_but_not_searchable(conn: sqlite3.Connection) -> None:
    chunks = [
        make_chunk("c1", "进程是程序的一次执行过程。", ["第2章"]),
        make_chunk("c2", "虚拟存储器", ["第6章"], index=2),
    ]
    insert_chunks(conn, chunks)
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 1
    assert query_fts(conn, "虚拟存储器", top_k=5) == []


def test_reingest_replaces_instead_of_duplicating(conn: sqlite3.Connection) -> None:
    chunk = make_chunk("c1", "进程是程序的一次执行过程。", ["第2章"])
    insert_chunks(conn, [chunk])
    insert_chunks(conn, [chunk])
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 1


def test_query_returns_chunk_and_respects_top_k(conn: sqlite3.Connection) -> None:
    chunks = [
        make_chunk("c1", "死锁的定义与四个必要条件。", ["第3章"], index=1),
        make_chunk("c2", "死锁的检测与解除方法。", ["第3章"], index=2),
        make_chunk("c3", "页面置换算法概述。", ["第6章"], index=3),
    ]
    insert_chunks(conn, chunks)
    hits = query_fts(conn, "死锁", top_k=1)
    assert len(hits) == 1
    assert "死锁" in hits[0]["content"]


def test_delete_document_clears_both_tables(conn: sqlite3.Connection) -> None:
    insert_chunks(conn, [make_chunk("c1", "进程是程序的一次执行过程。", ["第2章"])])
    delete_document_chunks(conn, "doc1")
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 0


def test_stats_agree_with_tables(conn: sqlite3.Connection) -> None:
    insert_chunks(
        conn,
        [
            make_chunk("c1", "进程是程序的一次执行过程。", ["第2章"]),
            make_chunk("c2", "死锁需要四个必要条件。", ["第3章"], index=2),
        ],
    )
    stats = get_stats(conn)
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert stats["chunks"] == chunks
