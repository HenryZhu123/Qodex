#!/usr/bin/env python3
"""Export the pooled candidates to a labelling sheet, and convert it back to labels.

Two steps, so a human can fill the sheet in any editor:

  python export_labels.py            -> labeling_sheet.csv
  python export_labels.py --ingest   -> labels.jsonl  (reads the filled sheet)
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

OUT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\retrieval_eval")
SNIPPET = 400


def export() -> int:
    queries = {json.loads(l)["qid"]: json.loads(l)
               for l in (OUT / "queries.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    rows = [json.loads(l) for l in (OUT / "pool.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rows.sort(key=lambda r: (r["qid"], r["rank_bm25"]))

    path = OUT / "labeling_sheet.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["qid", "query", "subject", "rank", "bm25", "heading",
                         "page", "chunk_id", "relevant", "snippet"])
        for row in rows:
            q = queries[row["qid"]]
            writer.writerow([
                row["qid"], q["query"], row["book"], row["rank_bm25"], row["bm25"],
                row["heading_path"], row["page_start"], row["chunk_id"], "", row["snippet"] + "…",
            ])
    print(json.dumps({"sheet": str(path), "rows": len(rows)}, ensure_ascii=False))
    return 0


def ingest() -> int:
    path = OUT / "labeling_sheet.csv"
    labels = []
    touched: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get("relevant") or "").strip()
            if raw not in {"0", "1"}:
                continue
            touched.add(row["qid"])
            labels.append({"qid": row["qid"], "chunk_id": row["chunk_id"],
                           "relevant": raw == "1"})
    (OUT / "labels.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in labels) + "\n", encoding="utf-8")

    total = len({json.loads(l)["qid"] for l in (OUT / "queries.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()})
    print(json.dumps({"labels": len(labels), "queries_labelled": len(touched),
                      "queries_total": total, "complete": len(touched) == total}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest", action="store_true")
    raise SystemExit(ingest() if parser.parse_args().ingest else export())
