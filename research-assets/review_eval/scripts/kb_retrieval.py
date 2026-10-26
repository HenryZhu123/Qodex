#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retrieval over the four-textbook knowledge base.

Each book lives in its own SQLite file with the same schema
(chunks(content, heading_path, page_start, ...) and chunks_fts).
A query searches every subject store and returns ranked evidence chunks.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

KB_ROOT = Path(r"D:\Code\hku\LLM\kb_review\books")

SUBJECTS = {
    "data_structure": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_system": "操作系统",
    "computer_network": "计算机网络",
}


@dataclass(frozen=True, slots=True)
class Evidence:
    subject: str
    chunk_id: str
    heading_path: str
    page_start: int | None
    content: str


def _fts_query(text: str) -> str:
    """Build an OR query of the informative tokens.

    FTS5 treats bare text as AND, which is too strict for question text, so we
    join terms with OR and let bm25 rank them.
    """
    import re

    tokens = [
        t for t in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9]{1,}", text)
    ]
    seen, uniq = set(), []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    if not uniq:
        return ""
    return " OR ".join(f'"{t}"' for t in uniq[:24])


def search(query: str, *, top_k: int = 5, subjects: list[str] | None = None) -> list[Evidence]:
    match = _fts_query(query)
    if not match:
        return []
    wanted = subjects or list(SUBJECTS)
    out: list[Evidence] = []
    for subject in wanted:
        db = KB_ROOT / subject / "kb.sqlite"
        if not db.exists():
            continue
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                """
                SELECT c.chunk_id, c.heading_path, c.page_start, c.content
                FROM chunks_fts f
                JOIN chunks c ON c.chunk_id = f.chunk_id
                WHERE chunks_fts MATCH ?
                ORDER BY bm25(chunks_fts)
                LIMIT ?
                """,
                (match, top_k),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        for chunk_id, heading, page, content in rows:
            out.append(Evidence(subject, chunk_id, heading or "", page, content))
    return out[:top_k]


def format_evidence(items: list[Evidence], max_chars: int = 700) -> str:
    if not items:
        return ""
    parts = []
    for i, ev in enumerate(items, 1):
        head = ev.heading_path or SUBJECTS.get(ev.subject, ev.subject)
        page = f" p.{ev.page_start}" if ev.page_start else ""
        body = ev.content.replace("\n", " ")[:max_chars]
        parts.append(f"[证据{i}]（{SUBJECTS.get(ev.subject, ev.subject)}｜{head}{page}）{body}")
    return "\n".join(parts)
