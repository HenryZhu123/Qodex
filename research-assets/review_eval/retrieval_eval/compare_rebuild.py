"""Compare the shipped indexes with the rebuilt ones, including a retrieval proxy.

Chunk ids change when boundaries move, so labels cannot be compared directly.
The proxy asks a weaker but honest question: for each positive query, does the
rebuilt index still return a passage that contains the text the old index
returned at rank 1?
"""

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src")

import jieba  # noqa: E402

OLD = Path(r"D:\Code\hku\LLM\kb_review\books")
NEW = Path(r"D:\Code\hku\LLM\kb_rebuild")
EVAL = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\retrieval_eval")

PAIRS = {
    "data_structure": ("data_structure/kb.sqlite", "data_structure/kb_new.sqlite"),
    "computer_organization": ("computer_organization/kb.sqlite", "computer_organization/kb_new.sqlite"),
    "operating_system": ("operating_system/kb.sqlite", "operating_system/kb_new.sqlite"),
    "computer_network": ("computer_network/kb.sqlite", "computer_network/kb_new.sqlite"),
}


def build_match(query: str) -> str:
    tokens = [t.strip() for t in jieba.cut(query) if len(t.strip()) >= 2]
    tokens += re.findall(r"[A-Za-z][A-Za-z0-9+#\-]{1,}", query)
    seen, uniq = set(), []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            uniq.append(token)
    return " OR ".join(f'"{t}"' for t in uniq[:16])


def top_k(db: Path, query: str, k: int = 2) -> list[str]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT c.content FROM chunks_fts f JOIN chunks c ON c.chunk_id = f.chunk_id
            WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) ASC LIMIT ?
            """,
            (build_match(query), k),
        ).fetchall()
        return [r[0] for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "ahq", EVAL / "audit_heading_quality.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.DBS = {k: [v[0]] for k, v in PAIRS.items()}
    old_audit = module.audit(OLD)
    module.DBS = {k: [v[1]] for k, v in PAIRS.items()}
    new_audit = module.audit(NEW)

    summary = {}
    for subject in PAIRS:
        o, n = old_audit[subject], new_audit[subject]
        summary[subject] = {
            "chunks_old": o["chunks"],
            "chunks_new": n["chunks"],
            "indexed_old": o["indexed"],
            "indexed_new": n["indexed"],
            "bad_heading_old": o.get("chunks_with_bad_segment", 0),
            "bad_heading_new": n.get("chunks_with_bad_segment", 0),
            "path_in_body_old": o.get("content_has_path_separator", 0),
            "path_in_body_new": n.get("content_has_path_separator", 0),
        }

    queries = [json.loads(l) for l in (EVAL / "queries.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    same = 0
    checked = 0
    for query in queries:
        if query["negative"] or query["subject"] not in PAIRS:
            continue
        old_db = OLD / PAIRS[query["subject"]][0]
        new_db = NEW / PAIRS[query["subject"]][1]
        old_hits = top_k(old_db, query["query"])
        if not old_hits:
            continue
        checked += 1
        needle = old_hits[0][:80].strip()
        new_hits = top_k(new_db, query["query"])
        if any(needle and needle in hit for hit in new_hits):
            same += 1

    print(json.dumps({
        "indexes": summary,
        "retrieval_proxy": {
            "queries_checked": checked,
            "same_top_passage_kept": same,
            "rate": round(same / checked, 4) if checked else None,
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
