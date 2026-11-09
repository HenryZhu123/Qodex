"""Check two reported defects: stub chunks ranking first, and headings leaking into body text."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

KB = Path(r"D:\Code\hku\LLM\kb_review\books")
EVAL = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\retrieval_eval")

DBS = [
    KB / "data_structure/kb.sqlite",
    KB / "computer_organization/kb.sqlite",
    KB / "operating_system/kb.sqlite",
    KB / "computer_network/kb.sqlite",
    KB / "computer_network/kb_8th.sqlite",
]


def main() -> int:
    total = 0
    short_60 = short_150 = 0
    starts_with_heading = heading_in_body = 0
    examples: list[dict] = []

    for db in DBS:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT chunk_id, heading_path, content, char_count FROM chunks"
        ).fetchall()
        conn.close()
        for chunk_id, heading, content, char_count in rows:
            total += 1
            text = (content or "").strip()
            n = char_count or len(text)
            if n < 60:
                short_60 += 1
            if n < 150:
                short_150 += 1
            head = (heading or "").strip()
            last = head.split(">")[-1].strip()
            if head and text.startswith(last) and last:
                starts_with_heading += 1
                if len(examples) < 5:
                    examples.append({
                        "chunk_id": chunk_id, "kind": "content starts with heading",
                        "heading": head, "content": text[:90],
                    })
            if " > " in text or "＞" in text:
                heading_in_body += 1

    # How often is the rank-1 hit a stub?
    pool = [json.loads(l) for l in (EVAL / "pool.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    sizes: dict[str, int] = {}
    for db in DBS:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for chunk_id, n in conn.execute("SELECT chunk_id, char_count FROM chunks"):
            sizes[chunk_id] = n or 0
        conn.close()

    top1 = [p for p in pool if p["rank_bm25"] == 1]
    top1_short = [p for p in top1 if sizes.get(p["chunk_id"], 0) < 150]
    top1_very_short = [p for p in top1 if sizes.get(p["chunk_id"], 0) < 60]

    print(json.dumps({
        "chunks_total": total,
        "under_60_chars": short_60,
        "under_150_chars": short_150,
        "content_starts_with_heading": starts_with_heading,
        "content_contains_path_separator": heading_in_body,
        "eval_queries": len({p["qid"] for p in pool}),
        "rank1_hits": len(top1),
        "rank1_under_150_chars": len(top1_short),
        "rank1_under_60_chars": len(top1_very_short),
        "rank1_short_examples": [
            {"qid": p["qid"], "chars": sizes.get(p["chunk_id"], 0), "heading": p["heading_path"][:40]}
            for p in top1_very_short[:8]
        ],
        "leak_examples": examples,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
