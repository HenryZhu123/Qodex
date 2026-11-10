#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1 for Blind Test Set v2: allocate the last untouched 408 sources.

Available untouched sources: 216 (720 total minus 320 Dev and 240 Blind v1).
Allocation: 156 error samples + 60 clean samples = 216.

Discipline notes:
- Dev Set A, Dev Set B (formerly "Blind v1") are excluded by source id, so no
  source question is shared across any set.
- The allocation and the mutation subtype quotas below are fixed before any
  measurement on this set. They are NOT derived from the failure modes observed
  on Dev Set B, so that factual_logical keeps a natural mix of corruption types
  (parameter corruption, relation inversion, rule inversion, ordering swap)
  instead of being narrowed to whatever the current pipeline happens to handle.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"D:\Code\hku\LLM\hku_agent")
ROOT = REPO / "research-assets" / "review_eval"
DEV_FULL = ROOT / "dataset" / "review_eval_full.jsonl"
DEV_B_FULL = ROOT / "blind_test_set" / "dataset" / "blind_test_full.jsonl"
REFQ = Path(r"D:\Code\hku\LLM\kb_refq_out\reference_questions.jsonl")
OUT = ROOT / "blind_test_v2" / "phase1"

SUBJECT_CN = {
    "data_structure": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_system": "操作系统",
    "computer_network": "计算机网络",
}
QTYPE_CN = {"single_choice": "单项选择题", "multiple_choice": "多项选择题"}

# error_type: count. factual_logical is capped at 6 because in 408 single-choice
# papers only data-bearing stems can carry a factual mutation without turning the
# item into "unsolvable" (mutating an option of a 下列说法 MCQ either makes two
# correct answers or corrupts a distractor that is false by design). The freed
# quota is given to answer_leakage, which is authorable on any stem.
QUOTA = {
    "typo": 24,
    "punctuation": 18,
    "option_structure": 18,
    "missing_info": 18,
    "ambiguity": 18,
    "unsolvable": 18,
    "answer_leakage": 24,
    "type_mismatch": 12,
    "factual_logical": 6,
}
CLEAN = 60

# Only data-bearing stems can carry a factual mutation without becoming
# "unsolvable", so reserve six concrete sources for factual_logical up front.
PREFERRED_FACTUAL = [
    "refq-408-2021-16",
    "refq-408-2023-12",
    "refq-408-2022-34",
    "refq-408-2022-38",
    "refq-408-2019-39",
    "refq-408-2024-09",
]


def norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def fp(text: str) -> str:
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()[:16]


def build_reference(q: dict) -> str:
    subj = SUBJECT_CN.get(q.get("subject", ""), "计算机专业基础综合")
    year = q.get("year", "")
    title = q.get(
        "exam_title", f"{year}年全国硕士研究生招生考试408计算机学科专业基础综合"
    )
    qt = QTYPE_CN.get(q.get("question_type", "single_choice"), "单项选择题")
    return f"【学科】{subj}\n【试卷标题】{title}\n【题型或其它信息】{qt}"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    used = set()
    for path in (DEV_FULL, DEV_B_FULL):
        for line in path.open(encoding="utf-8"):
            if line.strip():
                sid = json.loads(line).get("source_record_id")
                if sid:
                    used.add(sid)

    pool = [json.loads(l) for l in REFQ.open(encoding="utf-8") if l.strip()]
    usable = [
        q
        for q in pool
        if q["record_id"] not in used
        and q.get("options_complete", True)
        and len(q.get("options", {})) == 4
        and len(q.get("stem", "")) >= 15
    ]
    print(f"untouched usable sources: {len(usable)} (need {sum(QUOTA.values()) + CLEAN})")
    assert len(usable) >= sum(QUOTA.values()) + CLEAN

    # Interleave by subject so every error type spans all four disciplines.
    by_subj: dict[str, list[dict]] = {}
    for q in usable:
        by_subj.setdefault(q.get("subject", "unknown"), []).append(q)
    ordered: list[dict] = []
    idx = 0
    while len(ordered) < len(usable):
        for s in sorted(by_subj):
            if idx < len(by_subj[s]):
                ordered.append(by_subj[s][idx])
        idx += 1

    selection: list[dict] = []
    cursor = 0

    by_id = {q["record_id"]: q for q in ordered}

    def take(n: int, etype: str) -> list[dict]:
        nonlocal cursor
        chunk = ordered[cursor : cursor + n]
        cursor += n
        return chunk

    reserved: dict[str, list[dict]] = {}
    for etype in QUOTA:
        if etype == "factual_logical":
            reserved[etype] = [by_id[i] for i in PREFERRED_FACTUAL if i in by_id]
    reserved_ids = {q["record_id"] for lst in reserved.values() for q in lst}
    ordered = [q for q in ordered if q["record_id"] not in reserved_ids]

    for etype, n in QUOTA.items():
        picked = reserved.get(etype, [])
        if etype == "factual_logical":
            items = picked[:n]
        else:
            items = picked + take(n - len(picked), etype)
        assert len(items) == n, f"{etype}: got {len(items)} != {n}"
        for q in items:
            opts = [f"{k}. {v}" for k, v in q["options"].items()]
            selection.append(
                {
                    "sample_id": f"v2-{etype}-{q['record_id']}",
                    "error_type": etype,
                    "provenance": "new_synthesis",
                    "source_record_id": q["record_id"],
                    "source_year": q.get("year"),
                    "source_subject": q.get("subject"),
                    "fingerprint": fp(q["stem"]),
                    "reference": build_reference(q),
                    "question_text": q["stem"],
                    "options": opts,
                    "full_text": q["stem"].rstrip() + "\n" + "\n".join(opts),
                    "source_answer": q.get("standard_answer"),
                }
            )

    for q in take(CLEAN, "clean"):
        opts = [f"{k}. {v}" for k, v in q["options"].items()]
        selection.append(
            {
                "sample_id": f"v2-clean-{q['record_id']}",
                "error_type": "none",
                "provenance": "new_clean_unseen",
                "source_record_id": q["record_id"],
                "source_year": q.get("year"),
                "source_subject": q.get("subject"),
                "fingerprint": fp(q["stem"]),
                "reference": build_reference(q),
                "question_text": q["stem"],
                "options": opts,
                "full_text": q["stem"].rstrip() + "\n" + "\n".join(opts),
                "source_answer": q.get("standard_answer"),
            }
        )

    with (OUT / "source_selection.jsonl").open("w", encoding="utf-8") as f:
        for r in selection:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    plan = {
        "run_id": "blind_test_v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Untouched held-out set; method frozen before first measurement.",
        "source_accounting": {
            "pool_total": len(pool),
            "used_by_dev_a": len(
                {
                    json.loads(l)["source_record_id"]
                    for l in DEV_FULL.open(encoding="utf-8")
                    if l.strip()
                }
            ),
            "used_by_dev_b": len(
                {
                    json.loads(l)["source_record_id"]
                    for l in DEV_B_FULL.open(encoding="utf-8")
                    if l.strip()
                }
            ),
            "allocated_to_v2": len(selection),
            "remaining_after_v2": len(usable) - len(selection),
        },
        "quota": QUOTA,
        "clean": CLEAN,
        "total": len(selection),
        "freeze_rule": [
            "No prompt, rule, or pipeline change may be made after the first "
            "measurement on this set.",
            "If a change is made anyway, this set is demoted to a development "
            "set and a further untouched set must be built.",
        ],
    }
    (OUT / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    counts: dict[str, int] = {}
    for r in selection:
        counts[r["error_type"]] = counts.get(r["error_type"], 0) + 1
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    print(f"wrote {len(selection)} sources to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
