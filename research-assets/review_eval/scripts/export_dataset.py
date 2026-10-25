#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export the review-evaluation dataset in three artefacts.

  review_eval_dataset.csv    test input only (no answers)
  review_eval_gold.jsonl     gold answers, one record per sample
  review_eval_full.jsonl     merged view for analysis
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
PHASE2M = ROOT / "phase2_manual"
OUT = ROOT / "dataset"

SUBJECT_CN = {
    "data_structure": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_system": "操作系统",
    "computer_network": "计算机网络",
}


def split_question(text: str) -> tuple[str, str]:
    """Split canonical text into (stem, options block).

    Options are the trailing run of lines starting with A./B./C./D.
    """
    lines = text.split("\n")
    cut = len(lines)
    for i, line in enumerate(lines):
        s = line.strip()
        if len(s) >= 2 and s[0] in "ABCD" and s[1] in ".．":
            cut = i
            break
    stem = "\n".join(lines[:cut]).strip()
    opts = "\n".join(l.strip() for l in lines[cut:]).strip()
    return stem, opts


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    src = PHASE2M / "phase2_normalized.jsonl"
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows.sort(key=lambda r: (r["error_type"], r["sample_id"]))

    full, gold, csv_rows = [], [], []
    for r in rows:
        stem, opts = split_question(r["error_text"])
        clean_stem, clean_opts = split_question(r["clean_text"])

        csv_rows.append({
            "sample_id": r["sample_id"],
            "error_type": r["error_type"],
            "error_detailed_type": r["error_detailed_type"],
            "subject": r["source_subject"],
            "subject_cn": SUBJECT_CN.get(r["source_subject"], r["source_subject"]),
            "year": r["source_year"],
            "source_record_id": r["source_record_id"],
            "question_text": stem,
            "options": opts,
            "full_text": r["error_text"],
        })

        gold.append({
            "sample_id": r["sample_id"],
            "error_type": r["error_type"],
            "has_error": True,
            "total_errors": 1,
            "errors": [{
                "error_type": r["error_type"],
                "position": r.get("location") or r["error_detailed_type"],
                "original_text": r["original_text"],
                "anchor_text": r["anchor_text"],
                "correction": r["correction"],
                "description": r["rationale"],
                "suggestion": f"将「{r['original_text']}」修正为「{r['correction']}」"
                              if r["original_text"] else f"在标记位置补回「{r['correction']}」",
            }],
        })

        full.append({
            **{k: r[k] for k in (
                "sample_id", "error_type", "error_detailed_type", "source_record_id",
                "source_year", "source_subject", "source_answer", "clean_text",
                "error_text", "original_text", "correction", "anchor_text", "rationale",
            )},
            "clean_question_text": clean_stem,
            "clean_options": clean_opts,
            "has_error": True,
            "total_errors": 1,
        })

    csv_path = OUT / "review_eval_dataset.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)

    gold_path = OUT / "review_eval_gold.jsonl"
    gold_path.write_text(
        "\n".join(json.dumps(g, ensure_ascii=False) for g in gold) + "\n", encoding="utf-8")

    full_path = OUT / "review_eval_full.jsonl"
    full_path.write_text(
        "\n".join(json.dumps(f, ensure_ascii=False) for f in full) + "\n", encoding="utf-8")

    print("dataset.csv :", csv_path, len(csv_rows), "rows")
    print("gold.jsonl  :", gold_path, len(gold), "records")
    print("full.jsonl  :", full_path, len(full), "records")
    print()
    print("by error_type:", dict(Counter(r["error_type"] for r in csv_rows)))
    print("by subject  :", dict(Counter(r["subject"] for r in csv_rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
