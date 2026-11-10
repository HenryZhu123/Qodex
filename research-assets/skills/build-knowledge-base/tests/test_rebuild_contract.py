"""Rebuild and export paths must obey the same rules as ingest.

`rebuild_fts` is the escape hatch that reconstructs the index from `chunks`. If it
skips the fragment filter or the heading strip, running it once silently undoes
both fixes: 147 fragments become searchable again and headings are counted twice.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from store import (
    export_chunks_jsonl,
    init_db,
    insert_chunks,
    insert_document,
    query_fts,
    rebuild_fts,
)

DOC = {
    "doc_id": "doc1",
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


def make_chunk(chunk_id: str, content: str, heading: list[str], index: int = 1) -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": "doc1",
        "chunk_index": index,
        "content": content,
        "content_hash": f"hash-{chunk_id}",
        "char_count": len(content),
        "chunk_type": "hierarchical",
        "heading_path": heading,
        "page_start": 1,
        "page_end": 1,
        "metadata": {},
    }


@pytest.fixture()
def conn(tmp_dir: Path) -> sqlite3.Connection:
    connection = init_db(tmp_dir / "kb.sqlite")
    insert_document(connection, DOC)
    yield connection
    connection.close()


def test_rebuild_keeps_fragments_out_of_the_index(conn: sqlite3.Connection) -> None:
    insert_chunks(
        conn,
        [
            make_chunk("c1", "进程是程序的一次执行过程。", ["第2章"]),
            make_chunk("c2", "虚拟存储器", ["第6章"], index=2),
        ],
    )
    before = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    indexed = rebuild_fts(conn)
    after = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    assert before == after == 1
    assert indexed == 1
    assert query_fts(conn, "虚拟存储器", top_k=5) == []


def test_rebuild_matches_the_ingest_index(conn: sqlite3.Connection) -> None:
    insert_chunks(
        conn,
        [
            make_chunk("c1", "死锁的定义与四个必要条件。", ["第3章"], index=1),
            make_chunk("c2", "死锁的检测与解除方法。", ["第3章"], index=2),
            make_chunk("c3", "图5.23　图5.19中树的二叉链表", ["第5章"], index=3),
        ],
    )
    before = conn.execute(
        "SELECT chunk_id FROM chunks_fts ORDER BY chunk_id"
    ).fetchall()
    rebuild_fts(conn)
    after = conn.execute(
        "SELECT chunk_id FROM chunks_fts ORDER BY chunk_id"
    ).fetchall()
    assert [r[0] for r in before] == [r[0] for r in after] == ["c1", "c2"]


def test_rebuild_drops_duplicated_heading_text(conn: sqlite3.Connection) -> None:
    # The heading is repeated as the first line; after the strip the body has no
    # occurrence of the heading term, so a heading-only query must not match it.
    insert_chunks(
        conn,
        [make_chunk("c1", "7.8.3 基于扫描的磁盘调度\n\nSCAN 算法会优先考虑磁头移动方向。", ["7.8.3 基于扫描的磁盘调度"])],
    )
    rebuild_fts(conn)
    tokens = conn.execute("SELECT content_tokens FROM chunks_fts WHERE chunk_id='c1'").fetchone()[0]
    assert "扫描" not in tokens.split()[:3]


def test_export_round_trip(conn: sqlite3.Connection, tmp_dir: Path) -> None:
    chunks = [make_chunk("c1", "进程是程序的一次执行过程。", ["第2章"])]
    insert_chunks(conn, chunks)
    path = tmp_dir / "chunks.jsonl"
    assert export_chunks_jsonl(chunks, path) == 1
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["content"] == chunks[0]["content"]


def test_rebuild_on_empty_table_returns_zero(conn: sqlite3.Connection) -> None:
    assert rebuild_fts(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 0
