"""Compare single-library retrieval (model picks the subject) with auto routing.

Ground truth: the chunk ids already labelled relevant for each query. A hit means
one of those chunk ids appears in the top-k returned by that strategy.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src")
from exam_checker.integrations.knowledge_base import KnowledgeBaseRetriever  # noqa: E402

OUT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\retrieval_eval")


def main() -> int:
    queries = [json.loads(l) for l in (OUT / "queries.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    labels = [json.loads(l) for l in (OUT / "labels.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    relevant: dict[str, set[str]] = {}
    for row in labels:
        if row["relevant"]:
            relevant.setdefault(row["qid"], set()).add(row["chunk_id"])

    kb = KnowledgeBaseRetriever(mode="single")
    rows = []
    for q in queries:
        if q["negative"]:
            continue
        gold = relevant.get(q["qid"], set())
        single, _ = kb.search(q["subject"], q["query"], top_k=3)
        auto, _ = kb.search("auto", q["query"], top_k=3)
        rows.append({
            "qid": q["qid"],
            "subject": q["subject"],
            "single_ids": [i.chunk_id for i in single],
            "auto_ids": [i.chunk_id for i in auto],
            "auto_subjects": [i.subject for i in auto],
            "gold": sorted(gold),
        })

    def rate(strategy: str, k: int) -> float:
        hits = sum(1 for r in rows if set(r[f"{strategy}_ids"][:k]) & set(r["gold"]))
        return round(hits / len(rows), 4)

    changed = [
        r for r in rows
        if (set(r["single_ids"][:2]) & set(r["gold"])) != (set(r["auto_ids"][:2]) & set(r["gold"]))
    ]
    subject_switched = [
        r for r in rows if r["auto_subjects"] and r["auto_subjects"][0] != r["subject"]
    ]
    print(json.dumps({
        "n_positives": len(rows),
        "single_recall@1": rate("single", 1),
        "auto_recall@1": rate("auto", 1),
        "single_recall@2": rate("single", 2),
        "auto_recall@2": rate("auto", 2),
        "single_recall@3": rate("single", 3),
        "auto_recall@3": rate("auto", 3),
        "queries_where_auto_changes_hit@2": len(changed),
        "changed_qids": [r["qid"] for r in changed],
        "auto_top1_from_other_subject": len(subject_switched),
        "switched_qids": [r["qid"] for r in subject_switched],
        "gold_empty": sum(1 for r in rows if not r["gold"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
