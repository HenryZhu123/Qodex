#!/usr/bin/env python3
"""Audit mutation quality without changing a frozen dataset.

Strict eligibility requires reversible mutations, source-level isolation, and
strong labels. Solvability samples labeled ``missing_required_condition``
additionally need two adjudicated witness worlds that satisfy the mutated stem
but lead to different answers.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def leakage_level(record: dict[str, Any]) -> str:
    text = record.get("original_text", "")
    answer = re.escape(str(record.get("source_answer") or "").strip()[:1])
    if answer and re.search(
        rf"(?:正确选项|正确答案|答案|请选择选项|除选项)\s*(?:为|：)?\s*{answer}",
        text,
    ):
        return "L2_direct"
    if re.search(r"排除|中间结果|正确结论", text):
        return "L1_partial"
    return "L0_hint"


def _missing_info_has_witnesses(record: dict[str, Any]) -> bool:
    validation = record.get("validation") or {}
    witnesses = validation.get("necessity_witnesses") or record.get("necessity_witnesses") or []
    if len(witnesses) < 2:
        return False
    answers = {str(witness.get("answer", "")).strip() for witness in witnesses}
    return len(answers - {""}) >= 2


def audit(
    records: list[dict[str, Any]],
    other_sets: list[tuple[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    strict_eligible = 0
    leakage_levels: Counter[str] = Counter()

    for record in records:
        sample_id = str(record.get("sample_id", ""))
        clean = str(record.get("clean_text", ""))
        error = str(record.get("error_text", ""))
        original = str(record.get("original_text", ""))
        correction = str(record.get("correction", ""))
        category = record.get("error_type")
        eligible = True

        if category != "none":
            if not original or error.count(original) != 1:
                issues.append({"sample_id": sample_id, "code": "ANCHOR_NOT_UNIQUE"})
                eligible = False
            elif error.replace(original, correction, 1) != clean:
                issues.append({"sample_id": sample_id, "code": "ROUND_TRIP_FAILED"})
                eligible = False

        if category == "answer_leakage":
            level = leakage_level(record)
            leakage_levels[level] += 1
            if level != "L2_direct":
                code = "WEAK_LEAKAGE_LABEL" if level == "L0_hint" else "PARTIAL_LEAKAGE_NEEDS_ADJUDICATION"
                issues.append({"sample_id": sample_id, "code": code})
                eligible = False

        subtype = record.get("solvability_subtype") or record.get("error_detailed_type")
        needs_witnesses = category == "missing_info" or (
            category == "solvability_failure" and subtype == "missing_required_condition"
        )
        if needs_witnesses and not _missing_info_has_witnesses(record):
            issues.append({"sample_id": sample_id, "code": "MISSING_NECESSITY_WITNESSES"})
            eligible = False

        if eligible:
            strict_eligible += 1

    own_sources = {
        str(record.get("source_record_id"))
        for record in records
        if record.get("source_record_id")
    }
    overlaps: dict[str, list[str]] = {}
    for name, other_records in other_sets:
        other_sources = {
            str(record.get("source_record_id"))
            for record in other_records
            if record.get("source_record_id")
        }
        overlap = sorted(own_sources & other_sources)
        if overlap:
            overlaps[name] = overlap
            for source_id in overlap:
                issues.append({"sample_id": source_id, "code": f"SOURCE_OVERLAP:{name}"})

    issue_counts = Counter(issue["code"] for issue in issues)
    by_category = Counter(str(record.get("error_type", "unknown")) for record in records)
    return {
        "records": len(records),
        "strict_eligible": strict_eligible,
        "strict_eligible_rate": round(strict_eligible / len(records), 6) if records else 0.0,
        "by_category": dict(sorted(by_category.items())),
        "leakage_levels": dict(sorted(leakage_levels.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "source_overlaps": {name: len(values) for name, values in overlaps.items()},
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--compare",
        type=Path,
        action="append",
        default=[],
        help="Another manifest whose source_record_id values must not overlap",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    records = load_jsonl(args.manifest)
    others = [(path.stem, load_jsonl(path)) for path in args.compare]
    report = audit(records, others)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 1 if args.strict and report["strict_eligible"] != report["records"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
