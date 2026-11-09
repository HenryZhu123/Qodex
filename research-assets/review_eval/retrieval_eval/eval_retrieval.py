#!/usr/bin/env python3
"""Write the top-2 relevance labels and compute retrieval metrics.

Labels were judged by reading the chunk text: relevant means the chunk carries the
information needed to answer the query, not merely shares the topic.
Negatives are out-of-scope by construction, so every candidate is 0 by definition.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

OUT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\retrieval_eval")

# qid -> relevance of rank 1, rank 2
JUDGED: dict[str, tuple[int, int]] = {
    "os-01": (0, 0), "os-02": (1, 1), "os-03": (1, 1), "os-04": (1, 1), "os-05": (1, 0),
    "os-06": (0, 1), "os-07": (0, 0), "os-08": (0, 0), "os-09": (1, 0), "os-10": (1, 0),
    "os-11": (0, 1), "os-12": (1, 0), "os-13": (1, 0), "os-14": (1, 1), "os-15": (1, 1),
    "os-16": (0, 1), "os-17": (1, 0), "os-18": (1, 1), "os-19": (0, 1), "os-20": (1, 1),
    "co-01": (1, 1), "co-02": (1, 1), "co-03": (0, 1), "co-04": (1, 1), "co-05": (1, 1),
    "co-06": (1, 0), "co-07": (1, 0), "co-08": (0, 0), "co-09": (1, 0), "co-10": (1, 1),
    "co-11": (1, 1), "co-12": (1, 1), "co-13": (1, 1), "co-14": (1, 1), "co-15": (1, 1),
    "co-16": (1, 1), "co-17": (1, 1), "co-18": (1, 1), "co-19": (1, 1), "co-20": (1, 1),
    "ds-01": (1, 0), "ds-02": (0, 0), "ds-03": (0, 0), "ds-04": (0, 1), "ds-05": (1, 1),
    "ds-06": (1, 1), "ds-07": (1, 1), "ds-08": (0, 1), "ds-09": (1, 1), "ds-10": (1, 1),
    "ds-11": (1, 0), "ds-12": (1, 1), "ds-13": (1, 1), "ds-14": (1, 0), "ds-15": (1, 0),
    "ds-16": (0, 0), "ds-17": (1, 0), "ds-18": (1, 0), "ds-19": (1, 1), "ds-20": (1, 1),
    "cn-01": (1, 1), "cn-02": (1, 1), "cn-03": (1, 1), "cn-04": (1, 1), "cn-05": (0, 0),
    "cn-06": (0, 0), "cn-07": (1, 1), "cn-08": (0, 1), "cn-09": (1, 1), "cn-10": (1, 0),
    "cn-11": (1, 0), "cn-12": (1, 1), "cn-13": (0, 0), "cn-14": (1, 1), "cn-15": (1, 0),
    "cn-16": (1, 0), "cn-17": (0, 0), "cn-18": (0, 1), "cn-19": (0, 1), "cn-20": (1, 1),
}


# rank-3 relevance, judged only for the 11 queries that missed at rank 2
JUDGED_R3: dict[str, int] = {
    "os-01": 0, "os-07": 0, "os-08": 0, "co-08": 0, "ds-02": 0, "ds-03": 0,
    "ds-16": 1, "cn-05": 0, "cn-06": 0, "cn-13": 0, "cn-17": 0,
}


def main() -> int:
    queries = {json.loads(l)["qid"]: json.loads(l)
               for l in (OUT / "queries.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    pool = [json.loads(l) for l in (OUT / "pool.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    by_qid: dict[str, list[dict]] = defaultdict(list)
    for row in pool:
        by_qid[row["qid"]].append(row)

    labels: list[dict] = []
    for qid, items in by_qid.items():
        items.sort(key=lambda r: r["rank_bm25"])
        judged = JUDGED.get(qid)
        for item in items:
            rank = item["rank_bm25"]
            if rank > 2:
                if rank != 3 or qid not in JUDGED_R3:
                    continue
                relevant = JUDGED_R3[qid]
            elif judged is None:
                relevant = 0
            else:
                relevant = judged[rank - 1]
            labels.append({"qid": qid, "chunk_id": item["chunk_id"],
                           "rank": rank, "relevant": bool(relevant)})

    (OUT / "labels.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in labels) + "\n", encoding="utf-8")

    pos = [q for q, r in queries.items() if not r["negative"]]
    neg = [q for q, r in queries.items() if r["negative"]]
    rel_by_qid: dict[str, dict[int, bool]] = defaultdict(dict)
    for row in labels:
        rel_by_qid[row["qid"]][row["rank"]] = row["relevant"]

    def hit(qid: str, k: int) -> bool:
        return any(rel_by_qid[qid].get(r) for r in range(1, k + 1))

    per_subject: dict[str, dict] = {}
    for subject in ("operating_system", "computer_organization", "data_structure", "computer_network"):
        qs = [q for q in pos if queries[q]["subject"] == subject]
        per_subject[subject] = {
            "n": len(qs),
            "recall@1": round(sum(hit(q, 1) for q in qs) / len(qs), 4),
            "recall@2": round(sum(hit(q, 2) for q in qs) / len(qs), 4),
            "recall@3": round(sum(hit(q, 3) for q in qs) / len(qs), 4),
            "misses": [q for q in qs if not hit(q, 2)],
        }

    metrics = {
        "model": "bm25 (sqlite fts5, jieba)",
        "top_k_production": 2,
        "positives": {
            "n": len(pos),
            "recall@1": round(sum(hit(q, 1) for q in pos) / len(pos), 4),
            "recall@2": round(sum(hit(q, 2) for q in pos) / len(pos), 4),
            "recall@3": round(sum(hit(q, 3) for q in pos) / len(pos), 4),
            "misses": [q for q in pos if not hit(q, 2)],
        },
        "negatives": {
            "n": len(neg),
            "returned_any": sum(1 for q in neg if by_qid.get(q)),
            "false_positive_rate@2": 1.0 if any(by_qid.get(q) for q in neg) else 0.0,
            "note": "bm25 always returns top-k for any query, so a query with no answer still gets evidence",
        },
        "per_subject": per_subject,
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"labels": len(labels),
                      "recall@1": metrics["positives"]["recall@1"],
                      "recall@2": metrics["positives"]["recall@2"],
                      "misses": len(metrics["positives"]["misses"]),
                      "miss_qids": metrics["positives"]["misses"],
                      "per_subject": {k: v["recall@2"] for k, v in per_subject.items()},
                      "negatives_with_evidence": metrics["negatives"]["returned_any"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
