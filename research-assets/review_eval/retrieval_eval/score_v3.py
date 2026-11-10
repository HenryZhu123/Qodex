"""Score the v3 hand labels against the current index.

Unlike the earlier runs, this does not infer relevance from rank: every candidate
was read and judged against the query, so a hit means the returned chunk actually
contains the answer.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = json.loads((HERE / "labels_v3.json").read_text(encoding="utf-8"))

by_subject: dict[str, list[tuple[str, list[int]]]] = defaultdict(list)
for qid, flags in LABELS.items():
    subject = "negative" if qid.startswith("neg") else qid.split("-")[0]
    by_subject[subject].append((qid, flags))


def recall_at(flags_list: list[list[int]], k: int) -> float:
    hits = sum(1 for flags in flags_list if any(flags[:k]))
    return hits / max(1, len(flags_list))


positives = [flags for qid, flags in LABELS.items() if not qid.startswith("neg")]
negatives = [flags for qid, flags in LABELS.items() if qid.startswith("neg")]

metrics = {
    "caliber": "strict: every candidate read and judged against the query",
    "queries": len(LABELS),
    "positives": len(positives),
    "negatives": len(negatives),
    "recall@1": round(recall_at(positives, 1), 4),
    "recall@2": round(recall_at(positives, 2), 4),
    "negative_hits@2": sum(1 for flags in negatives if any(flags)),
    "per_subject": {
        subject: {
            "n": len(items),
            "recall@1": round(recall_at([f for _, f in items], 1), 4),
            "recall@2": round(recall_at([f for _, f in items], 2), 4),
        }
        for subject, items in sorted(by_subject.items())
        if subject != "negative"
    },
    "misses@2": [qid for qid, flags in LABELS.items() if not qid.startswith("neg") and not any(flags)],
}

(HERE / "metrics_v3.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(metrics, ensure_ascii=False, indent=2))
