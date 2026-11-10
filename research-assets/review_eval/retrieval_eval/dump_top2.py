#!/usr/bin/env python3
"""Dump the top-2 candidates per query with enough context for judging relevance."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

OUT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\retrieval_eval")
KB = Path(r"D:\Code\hku\LLM\kb_review\books")
LIMIT = 300


def main() -> int:
    queries = [json.loads(l) for l in (OUT / "queries.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    pool = [json.loads(l) for l in (OUT / "pool.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    top2: dict[str, list[dict]] = {}
    for row in pool:
        if row["rank_bm25"] <= 2:
            top2.setdefault(row["qid"], []).append(row)

    conns: dict[str, sqlite3.Connection] = {}
    lines: list[str] = []
    for q in queries:
        items = sorted(top2.get(q["qid"], []), key=lambda r: r["rank_bm25"])
        lines.append(f"=== {q['qid']} | {q['subject']} | neg={q['negative']}")
        lines.append(f"Q: {q['query']}")
        if not items:
            lines.append("(no hits)")
        for item in items:
            db = KB / item["book"] / "kb.sqlite"
            conn = conns.setdefault(str(db), sqlite3.connect(db))
            row = conn.execute("SELECT content FROM chunks WHERE chunk_id = ?", (item["chunk_id"],)).fetchone()
            body = (row[0] if row else "").replace("\n", " ")
            lines.append(f"[{item['rank_bm25']}] {item['chunk_id']} | {item['heading_path'][:60]} | p{item['page_start']}")
            lines.append(f"C: {body[:LIMIT]}")
        lines.append("")
    for conn in conns.values():
        conn.close()

    path = OUT / "top2_review.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"file": str(path), "lines": len(lines),
                      "queries": len(queries),
                      "candidates": sum(len(v) for v in top2.values())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
