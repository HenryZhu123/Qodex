#!/usr/bin/env python3
"""Correct mechanically-assigned subject labels after manual review.

The original labels were mapped from the 408 question number, which is wrong for
a number of items (a SCAN scheduling question filed under computer networks, a
bus question filed under operating systems, and so on). Each entry below was
checked by reading the question stem.

Only the 【学科】 field inside `reference` changes; labels, errors and anchors are
untouched.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent")
EVAL = ROOT / "research-assets" / "review_eval"

CSV_TARGETS = [
    EVAL / "taxonomy_v2/dev_a/strict/review_eval_dataset_v2.csv",
    EVAL / "taxonomy_v2/dev_a/strict/review_eval_dataset.csv",
    EVAL / "taxonomy_v2/dev_b/strict/blind_test_dataset.csv",
]

# sample_id -> (new subject, reason)
FIXES: dict[str, tuple[str, str]] = {
    "rev-factual_logical-refq-408-2009-29": ("操作系统", "SCAN 磁盘调度属操作系统"),
    "rev-factual_logical-refq-408-2017-31": ("操作系统", "软链接与 inode 共享属操作系统"),
    "rev-factual_logical-refq-408-2020-19": ("计算机组成原理", "QPI 总线属计组"),
    "rev-factual_logical-refq-408-2024-20": ("计算机组成原理", "总线突发传送属计组"),
    "rev-factual_logical-refq-408-2025-20": ("计算机组成原理", "总线频率与宽度属计组"),
    "rev-factual_logical-refq-408-2026-20": ("计算机组成原理", "数据通路与 CPI 属计组"),
    "blind-factual_logical-refq-408-2014-16": ("计算机组成原理", "统一 Cache 属计组"),
    "blind-factual_logical-refq-408-2014-17": ("计算机组成原理", "指令字与寻址属计组"),
    "blind-factual_logical-refq-408-2014-18": ("计算机组成原理", "微程序控制器属计组"),
    "blind-factual_logical-refq-408-2014-19": ("计算机组成原理", "总线时钟与传输率属计组"),
    "blind-factual_logical-refq-408-2014-20": ("计算机组成原理", "总线事务突发传送属计组"),
    "blind-factual_logical-refq-408-2014-26": ("操作系统", "进程状态与时间片属操作系统"),
}

PATTERN = re.compile(r"【学科】([^\n]+)")


def main() -> int:
    audit: list[dict] = []
    for path in CSV_TARGETS:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
        changed = 0
        for row in rows:
            fix = FIXES.get(row.get("sample_id", ""))
            if not fix or "reference" not in row:
                continue
            new_subject, reason = fix
            match = PATTERN.search(row["reference"])
            if not match:
                continue
            old_subject = match.group(1)
            if old_subject == new_subject:
                continue
            row["reference"] = PATTERN.sub(f"【学科】{new_subject}", row["reference"], count=1)
            changed += 1
            audit.append({
                "file": str(path.relative_to(ROOT)),
                "sample_id": row["sample_id"],
                "old_subject": old_subject,
                "new_subject": new_subject,
                "reason": reason,
            })
        if changed:
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        print(f"{path.name}: {changed} rows updated")

    audit_path = EVAL / "subject_label_audit.json"
    audit_path.write_text(
        json.dumps({
            "reviewed": "40 factual_logical items in Dev A + Dev B",
            "method": "manual reading of the question stem; the model's own subject choice was used as a cross-check",
            "unaudited": "the remaining items keep their original mechanical labels",
            "changes": audit,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"changes": len(audit), "audit": str(audit_path.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
