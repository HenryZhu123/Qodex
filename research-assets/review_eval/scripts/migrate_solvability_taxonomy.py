"""Migrate the three review datasets to the unified solvability taxonomy.

The script never overwrites source datasets.  It writes versioned copies under
``review_eval/taxonomy_v2`` and records every changed or adjudicated row.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOLVABILITY_TYPES = {"missing_info", "unsolvable", "solvability_failure"}
SUBTYPE_CN = {
    "missing_required_condition": "缺少必要条件",
    "underspecified_task": "设问或对象未指明",
    "no_valid_answer": "无有效答案",
    "multiple_valid_answers": "多个有效答案",
    "contradictory_conditions": "条件矛盾",
    "indeterminate_answer": "答案无法唯一确定",
}

DATASETS = {
    "dev_a": (
        ROOT / "dataset",
        "review_eval_dataset.csv",
        "review_eval_full.jsonl",
        "review_eval_gold.jsonl",
    ),
    "dev_b": (
        ROOT / "blind_test_set" / "dataset",
        "blind_test_dataset.csv",
        "blind_test_full.jsonl",
        "blind_test_gold.jsonl",
    ),
    "blind_v2": (
        ROOT / "blind_test_v2" / "dataset",
        "blind_v2_dataset.csv",
        "blind_v2_full.jsonl",
        "blind_v2_gold.jsonl",
    ),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def infer_subtype(row: dict[str, Any], adjudication: dict[str, Any] | None = None) -> str:
    legacy_type = str(row.get("legacy_error_type") or row.get("error_type") or "")
    text = " ".join(
        str(row.get(key) or "")
        for key in ("error_detailed_type", "rationale", "error_text", "full_text")
    )
    if adjudication:
        text += " " + str(adjudication.get("你的判断理由") or "")
        corrected = str(adjudication.get("正确类别") or "")
        if corrected == "missing_info":
            return "missing_required_condition"
        if corrected == "unsolvable" and re.search(r"问题|设问|询问|对象", text):
            return "underspecified_task"
    if legacy_type == "missing_info":
        return "missing_required_condition"
    if re.search(r"删除|缺少.*(?:参数|条件|取值|位宽|频率|数量)|占位符替代", text):
        return "missing_required_condition"
    if re.search(r"发散|不存在", text):
        return "no_valid_answer"
    if re.search(r"矛盾|冲突|不能同时", text):
        return "contradictory_conditions"
    if re.search(r"多个|多解|不唯一|至少.{0,4}(两|2)|两个.*正确", text):
        return "multiple_valid_answers"
    if re.search(r"无一|没有.*正确|均不正确|无正确|0\s*个", text):
        return "no_valid_answer"
    if re.search(r"问题|设问|询问|对象|未指明|占位", text):
        return "underspecified_task"
    return "indeterminate_answer"


def normalize_decision(record: dict[str, Any]) -> tuple[str, bool]:
    decision = str(record.get("你的决定") or "").strip()
    inferred = False
    if not decision and record.get("正确类别") and record.get("你的判断理由"):
        decision = "keep"
        inferred = True
    return decision, inferred


def migrate_row(
    row: dict[str, Any],
    adjudication: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(row)
    legacy_type = str(result.get("error_type") or "")
    if legacy_type in SOLVABILITY_TYPES:
        subtype = infer_subtype(result, adjudication)
        result["legacy_error_type"] = legacy_type
        result["legacy_error_detailed_type"] = result.get("error_detailed_type", "")
        result["error_type"] = "solvability_failure"
        if "error_type_cn" in result:
            result["error_type_cn"] = "可解性错误"
        result["error_detailed_type"] = subtype
        result["solvability_subtype"] = subtype
        result["solvability_subtype_cn"] = SUBTYPE_CN[subtype]

    if adjudication:
        decision, inferred = normalize_decision(adjudication)
        level = str(adjudication.get("leakage_level") or "").strip()
        result["human_decision"] = decision
        result["human_decision_inferred"] = inferred
        result["human_corrected_legacy_type"] = adjudication.get("正确类别") or ""
        result["human_reason"] = adjudication.get("你的判断理由") or ""
        result["leakage_level"] = level
        result["strict_eval_eligible"] = decision == "keep" and level not in {"L0", "L1"}
    elif "strict_eval_eligible" not in result:
        result["strict_eval_eligible"] = True
    return result


def migrate_gold(row: dict[str, Any], migrated_full: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if str(result.get("error_type") or "") in SOLVABILITY_TYPES:
        result["legacy_error_type"] = result["error_type"]
        result["error_type"] = "solvability_failure"
        result["solvability_subtype"] = migrated_full["solvability_subtype"]
        for error in result.get("errors", []):
            if str(error.get("error_type") or "") in SOLVABILITY_TYPES:
                error["legacy_error_type"] = error["error_type"]
                error["error_type"] = "可解性错误"
                error["error_subtype"] = migrated_full["solvability_subtype"]
    for key in (
        "human_decision",
        "human_decision_inferred",
        "human_corrected_legacy_type",
        "human_reason",
        "leakage_level",
        "strict_eval_eligible",
    ):
        if key in migrated_full:
            result[key] = migrated_full[key]
    return result


def migrate_dataset(name: str, output_root: Path, manual: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_dir, csv_name, full_name, gold_name = DATASETS[name]
    csv_rows = read_csv(source_dir / csv_name)
    full_rows = read_jsonl(source_dir / full_name)
    gold_rows = read_jsonl(source_dir / gold_name)
    adjudications = manual if name == "blind_v2" else {}

    migrated_full = [migrate_row(row, adjudications.get(str(row.get("sample_id")))) for row in full_rows]
    full_by_id = {str(row["sample_id"]): row for row in migrated_full}
    migrated_csv = [
        migrate_row(row, adjudications.get(str(row.get("sample_id")))) for row in csv_rows
    ]
    migrated_gold = [migrate_gold(row, full_by_id[str(row["sample_id"])]) for row in gold_rows]

    if name == "blind_v2":
        removed = {
            sample_id
            for sample_id, record in adjudications.items()
            if normalize_decision(record)[0] == "remove"
        }
        migrated_full = [row for row in migrated_full if str(row["sample_id"]) not in removed]
        migrated_csv = [row for row in migrated_csv if str(row["sample_id"]) not in removed]
        migrated_gold = [row for row in migrated_gold if str(row["sample_id"]) not in removed]

    destination = output_root / name
    write_csv(destination / csv_name, migrated_csv)
    write_jsonl(destination / full_name, migrated_full)
    write_jsonl(destination / gold_name, migrated_gold)

    strict_full = [row for row in migrated_full if bool(row.get("strict_eval_eligible", True))]
    strict_ids = {str(row["sample_id"]) for row in strict_full}
    strict_csv = [row for row in migrated_csv if str(row["sample_id"]) in strict_ids]
    strict_gold = [row for row in migrated_gold if str(row["sample_id"]) in strict_ids]
    write_csv(destination / "strict" / csv_name, strict_csv)
    write_jsonl(destination / "strict" / full_name, strict_full)
    write_jsonl(destination / "strict" / gold_name, strict_gold)

    manifest = []
    for before, after in zip(full_rows, [migrate_row(row, adjudications.get(str(row.get("sample_id")))) for row in full_rows], strict=False):
        sample_id = str(before["sample_id"])
        if before.get("error_type") in SOLVABILITY_TYPES or sample_id in adjudications:
            manifest.append(
                {
                    "sample_id": sample_id,
                    "legacy_error_type": before.get("error_type"),
                    "new_error_type": after.get("error_type"),
                    "solvability_subtype": after.get("solvability_subtype", ""),
                    "human_decision": after.get("human_decision", ""),
                    "human_decision_inferred": after.get("human_decision_inferred", False),
                    "strict_eval_eligible": after.get("strict_eval_eligible", True),
                    "included_in_adjudicated": sample_id not in {
                        sid for sid, rec in adjudications.items() if normalize_decision(rec)[0] == "remove"
                    },
                }
            )
    write_jsonl(destination / "migration_manifest.jsonl", manifest)

    summary = {
        "dataset": name,
        "source_directory": str(source_dir),
        "source_rows": len(full_rows),
        "adjudicated_rows": len(migrated_full),
        "strict_rows": len(strict_full),
        "removed_by_human": len(full_rows) - len(migrated_full),
        "excluded_from_strict": len(migrated_full) - len(strict_full),
        "strict_policy": (
            "human_adjudication_plus_leakage_strength"
            if name == "blind_v2"
            else "taxonomy_migration_only_no_human_quality_exclusion"
        ),
        "manual_decision_counts": dict(
            Counter(normalize_decision(record)[0] or "blank" for record in adjudications.values())
        ),
        "inferred_keep_count": sum(
            1 for record in adjudications.values() if normalize_decision(record) == ("keep", True)
        ),
        "legacy_type_counts": dict(Counter(str(row.get("error_type")) for row in full_rows)),
        "new_type_counts": dict(Counter(str(row.get("error_type")) for row in migrated_full)),
        "solvability_subtype_counts": dict(
            Counter(str(row["solvability_subtype"]) for row in migrated_full if row.get("solvability_subtype"))
        ),
    }
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "taxonomy_v2")
    parser.add_argument(
        "--manual",
        type=Path,
        default=ROOT / "blind_test_v2" / "dataset" / "manual_adjudication.json",
    )
    args = parser.parse_args()
    manual_rows = json.loads(args.manual.read_text(encoding="utf-8"))
    manual = {str(row["sample_id"]): row for row in manual_rows}
    summaries = [migrate_dataset(name, args.output, manual) for name in DATASETS]
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
