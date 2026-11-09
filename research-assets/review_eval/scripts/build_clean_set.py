#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect clean (unmodified) questions for the false-positive baseline.

The 220 erroneous samples already consume 220 source questions. A clean-set
sample must not reuse any of them, otherwise a model that "recognises the
question" would look correct for the wrong reason.

Sources, in priority order:
  1. remaining 2009-2026 exam choice questions not yet used;
  2. 重排版 paper questions with complete options.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\Code\hku\LLM\hku_agent")
REFQ_CANDIDATES = [
    REPO / "research-assets" / "reference_questions_408.jsonl",
    Path(r"D:\Code\hku\LLM\kb_refq_out\reference_questions.jsonl"),
]
PHASE2M = REPO / "research-assets" / "review_eval" / "phase2_manual"
OUT = REPO / "research-assets" / "review_eval" / "dataset" / "clean_candidates.jsonl"

SUBJECT_ORDER = ["data_structure", "computer_organization", "operating_system", "computer_network"]


def question_text(rec: dict) -> str:
    opts = rec.get("options") or {}
    parts = [rec["stem"].strip()]
    for letter in "ABCD":
        if opts.get(letter):
            parts.append(f"{letter}. {opts[letter]}")
    return "\n".join(parts)


def main() -> int:
    src = next((p for p in REFQ_CANDIDATES if p.exists()), None)
    if src is None:
        print("reference questions not found")
        return 2

    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]

    used = set()
    for f in PHASE2M.glob("*_manifest.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                used.add(json.loads(line)["source_record_id"])

    # A clean sample keeps the option-complete, answer-complete questions only.
    pool = [
        r for r in rows
        if r["record_id"] not in used
        and r.get("options_complete")
        and r.get("answer_available")
        and len(r.get("stem", "")) >= 20
    ]
    # Stable order by record id so the selection is reproducible.
    pool.sort(key=lambda r: r["record_id"])

    by_subject: dict[str, list[dict]] = {s: [] for s in SUBJECT_ORDER}
    for r in pool:
        by_subject.setdefault(r["subject"], []).append(r)

    TARGET = 100
    picked: list[dict] = []
    # Round-robin across subjects for balance.
    idx = {s: 0 for s in by_subject}
    while len(picked) < TARGET and any(idx[s] < len(by_subject[s]) for s in by_subject):
        for s in SUBJECT_ORDER:
            if len(picked) >= TARGET:
                break
            if idx[s] < len(by_subject[s]):
                picked.append(by_subject[s][idx[s]])
                idx[s] += 1

    out = []
    for i, r in enumerate(picked, 1):
        out.append({
            "sample_id": f"clean-{i:03d}-{r['record_id']}",
            "record_id": r["record_id"],
            "subject": r["subject"],
            "year": r["year"],
            "question_no": r["question_no"],
            "standard_answer": r["standard_answer"],
            "full_text": question_text(r),
            "has_error": False,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n",
                   encoding="utf-8")

    print("unused pool   :", len(pool))
    print("selected clean:", len(out))
    print("by subject    :", dict(Counter(o["subject"] for o in out)))
    print("by year span  :", min(o["year"] for o in out), "-", max(o["year"] for o in out))
    print("written       :", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
