#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backfill structured reference metadata into Dev Set and Blind Test Set.

Follows the exam-checker-agent design:
【学科】<学科中文>
【试卷标题】<试卷标题>
【题型或其它信息】<题型中文>
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
REFQ_PATH = Path(r"D:\Code\hku\LLM\kb_refq_out\reference_questions.jsonl")

SUBJECT_CN = {
    "data_structure": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_system": "操作系统",
    "computer_network": "计算机网络",
}

QUESTION_TYPE_CN = {
    "single_choice": "单项选择题",
    "multiple_choice": "多项选择题",
    "comprehensive": "综合应用题",
}


def load_refq_map() -> dict[str, dict]:
    return {
        q["record_id"]: q
        for q in (json.loads(l) for l in REFQ_PATH.open(encoding="utf-8") if l.strip())
    }


def build_reference(q: dict) -> str:
    subj_code = q.get("subject", "computer_network")
    subj_cn = SUBJECT_CN.get(subj_code, "计算机专业基础综合")

    year = q.get("year", "2026")
    exam_title = q.get(
        "exam_title",
        f"{year}年全国硕士研究生招生考试408计算机学科专业基础综合",
    )

    qtype_code = q.get("question_type", "single_choice")
    qtype_cn = QUESTION_TYPE_CN.get(qtype_code, "单项选择题")

    return f"【学科】{subj_cn}\n【试卷标题】{exam_title}\n【题型或其它信息】{qtype_cn}"


def backfill_dataset(dataset_dir: Path, refq_map: dict[str, dict], is_blind: bool = False):
    full_path = dataset_dir / ("blind_test_full.jsonl" if is_blind else "review_eval_full.jsonl")
    csv_path = dataset_dir / ("blind_test_dataset.csv" if is_blind else "review_eval_dataset.csv")

    records = [json.loads(l) for l in full_path.open(encoding="utf-8") if l.strip()]
    updated_records = []

    for r in records:
        s_id = r.get("source_record_id")
        q = refq_map.get(s_id, {})
        ref_str = build_reference(q)
        r["reference"] = ref_str
        r["subject_cn"] = SUBJECT_CN.get(r.get("subject") or q.get("subject"), "计算机专业基础")
        updated_records.append(r)

    # 1. Write updated full JSONL
    with full_path.open("w", encoding="utf-8") as f:
        for r in updated_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 2. Write updated CSV
    fieldnames = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")).fieldnames or [])
    if "reference" not in fieldnames:
        # Insert reference right after source_record_id or at beginning
        fieldnames.append("reference")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in updated_records:
            row_dict = dict(r)
            writer.writerow(row_dict)

    print(f"Backfilled reference for {len(updated_records)} records in {dataset_dir}")


def main() -> int:
    refq_map = load_refq_map()
    print(f"Loaded {len(refq_map)} reference questions.")

    # 1. Dev Set
    dev_dir = ROOT / "dataset"
    backfill_dataset(dev_dir, refq_map, is_blind=False)

    # 2. Blind Test Set
    blind_dir = ROOT / "blind_test_set" / "dataset"
    backfill_dataset(blind_dir, refq_map, is_blind=True)

    print("\nAll reference structures successfully backfilled!")
    return 0


if __name__ == "__main__":
    main()
