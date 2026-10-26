#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge erroneous samples and clean questions into one evaluation dataset.

Outputs:
  review_eval_dataset.csv   all rows, test input only (no answers)
  review_eval_gold.jsonl    gold answers; clean rows carry has_error=false
  review_eval_full.jsonl    merged view for analysis
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
DATASET = ROOT / "dataset"
PHASE2M = ROOT / "phase2_manual"

SUBJECT_CN = {
    "data_structure": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_system": "操作系统",
    "computer_network": "计算机网络",
}


def split_question(text: str) -> tuple[str, str]:
    lines = text.split("\n")
    cut = len(lines)
    for i, line in enumerate(lines):
        s = line.strip()
        if len(s) >= 2 and s[0] in "ABCD" and s[1] in ".．":
            cut = i
            break
    return "\n".join(lines[:cut]).strip(), "\n".join(l.strip() for l in lines[cut:]).strip()


def load_errors() -> list[dict]:
    rows = [json.loads(l) for l in (PHASE2M / "phase2_normalized.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        stem, opts = split_question(r["error_text"])
        out.append({
            "sample_id": r["sample_id"],
            "label": "error",
            "error_type": r["error_type"],
            "error_detailed_type": r["error_detailed_type"],
            "subject": r["source_subject"],
            "subject_cn": SUBJECT_CN.get(r["source_subject"], r["source_subject"]),
            "year": r["source_year"],
            "source_record_id": r["source_record_id"],
            "question_text": stem,
            "options": opts,
            "full_text": r["error_text"],
            "gold": {
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
                    "suggestion": (
                        f"将「{r['original_text']}」修正为「{r['correction']}」"
                        if r["original_text"] else f"在标记位置补回「{r['correction']}」"
                    ),
                }],
            },
        })
    return out


def load_clean() -> list[dict]:
    src = DATASET / "clean_set.jsonl"
    if not src.exists():
        return []
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        stem, opts = split_question(r["full_text"])
        out.append({
            "sample_id": r["sample_id"],
            "label": "clean",
            "error_type": "none",
            "error_detailed_type": "",
            "subject": r["subject"],
            "subject_cn": SUBJECT_CN.get(r["subject"], r["subject"]),
            "year": r["year"],
            "source_record_id": r["record_id"],
            "question_text": stem,
            "options": opts,
            "full_text": r["full_text"],
            "gold": {
                "sample_id": r["sample_id"],
                "error_type": "none",
                "has_error": False,
                "total_errors": 0,
                "errors": [],
            },
        })
    return out


def main() -> int:
    errors = load_errors()
    clean = load_clean()
    all_rows = errors + clean
    all_rows.sort(key=lambda r: (r["label"], r["error_type"], r["sample_id"]))

    fields = ["sample_id", "label", "error_type", "error_detailed_type", "subject",
              "subject_cn", "year", "source_record_id", "question_text", "options", "full_text"]

    csv_path = DATASET / "review_eval_dataset.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    (DATASET / "review_eval_gold.jsonl").write_text(
        "\n".join(json.dumps(r["gold"], ensure_ascii=False) for r in all_rows) + "\n",
        encoding="utf-8")

    (DATASET / "review_eval_full.jsonl").write_text(
        "\n".join(json.dumps({k: v for k, v in r.items() if k != "gold"}, ensure_ascii=False)
                  for r in all_rows) + "\n",
        encoding="utf-8")

    print(f"total rows : {len(all_rows)}")
    print(f"  error    : {len(errors)}")
    print(f"  clean    : {len(clean)}")
    print("by subject :", dict(Counter(r["subject"] for r in all_rows)))
    print("by label   :", dict(Counter(r["label"] for r in all_rows)))
    print()
    print("dataset:", csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
