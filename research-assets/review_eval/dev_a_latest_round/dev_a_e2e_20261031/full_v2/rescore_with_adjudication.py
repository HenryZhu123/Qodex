#!/usr/bin/env python3
"""Apply the clean-label adjudication and rescore the existing full_v2 output.

Reads (never modifies):
  - taxonomy_v2/dev_a/strict/review_eval_dataset.csv   (v1, unchanged)
  - full_v2/clean_adjudication.csv                     (human-confirmed verdicts)
  - full_v2/results.jsonl                              (318 model outputs, unchanged)

Writes:
  - taxonomy_v2/dev_a/strict/review_eval_dataset_v2.csv
  - taxonomy_v2/dev_a/strict/review_eval_dataset_v2.provenance.json
  - full_v2/rescored/results.jsonl
  - full_v2/rescored/summary.json
  - full_v2/rescored/metrics_comparison.json

No model call is made: the model output per sample is reused verbatim.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
RUN_DIR = SCRIPT_DIR.parent
REVIEW_ROOT = SCRIPT_DIR.parents[2]

sys.path.insert(0, str(REVIEW_ROOT / "scripts"))
from evaluation_metrics import summarize  # noqa: E402

DATASET_V1 = REVIEW_ROOT / "taxonomy_v2" / "dev_a" / "strict" / "review_eval_dataset.csv"
DATASET_V2 = REVIEW_ROOT / "taxonomy_v2" / "dev_a" / "strict" / "review_eval_dataset_v2.csv"
PROVENANCE = REVIEW_ROOT / "taxonomy_v2" / "dev_a" / "strict" / "review_eval_dataset_v2.provenance.json"
ADJUDICATION = SCRIPT_DIR / "clean_adjudication.csv"
RESULTS = SCRIPT_DIR / "results.jsonl"
OUT_DIR = SCRIPT_DIR / "rescored"

EXPECTED_LABEL = {
    "typo": "错别字",
    "punctuation": "标点符号错误",
    "option_structure": "选项错误",
    "type_mismatch": "题目与题型不一致",
    "solvability_failure": "可解性错误",
    "ambiguity": "语义不清",
    "answer_leakage": "答案泄露",
    "factual_logical": "事实/逻辑错误",
}

# sample_id -> (error_type, error_detailed_type, solvability_subtype, solvability_subtype_cn)
RELABEL: dict[str, tuple[str, str, str, str]] = {
    "clean-012": ("typo", "形近字", "", ""),
    "clean-028": ("solvability_failure", "missing_required_condition", "missing_required_condition", "缺少必要条件"),
    "clean-029": ("solvability_failure", "missing_required_condition", "missing_required_condition", "缺少必要条件"),
    "clean-037": ("solvability_failure", "missing_required_condition", "missing_required_condition", "缺少必要条件"),
    "clean-061": ("typo", "字符损坏", "", ""),
    "clean-071": ("typo", "形近字", "", ""),
    "clean-074": ("solvability_failure", "no_valid_answer", "no_valid_answer", "无正确选项"),
    "clean-082": ("typo", "音近字", "", ""),
    "clean-096": ("typo", "术语错字", "", ""),
}

SECONDARY_NOTES = {
    "clean-028": "另有“交换网网络”字符重复（typo），单标签数据集取更严重的缺条件为主类。",
    "clean-061": "根因是上划线被抽成组合符乱码，归 typo/字符损坏；模型报的是可解性错误，重标后计为 wrong-type。",
    "clean-074": "表象为无正确项；根因疑为负号与上标在抽取中丢失。本表按人工确认归入 solvability_failure，并新增子类 no_valid_answer。",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not ADJUDICATION.exists():
        raise SystemExit(f"missing adjudication file: {ADJUDICATION}")

    with DATASET_V1.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    with ADJUDICATION.open(encoding="utf-8-sig", newline="") as handle:
        verdicts = {row["sample_id"]: row for row in csv.DictReader(handle)}

    before_clean = sum(1 for row in rows if row["label"] == "clean")
    before_error = sum(1 for row in rows if row["label"] != "clean")

    confirmed = {sid for sid, row in verdicts.items() if row["my_verdict"].strip() == "真实缺陷"}
    pending = sorted(sid for sid, row in verdicts.items() if row["my_verdict"].strip() == "待定")
    rejected = sorted(sid for sid, row in verdicts.items() if row["my_verdict"].strip() == "误报")

    missing = sorted(confirmed - set(RELABEL))
    if missing:
        raise SystemExit(f"confirmed samples without a relabel rule: {missing}")

    changed: list[dict[str, Any]] = []
    for row in rows:
        sid = row["sample_id"]
        if sid not in RELABEL:
            continue
        if row["label"] != "clean":
            raise SystemExit(f"{sid} was expected to be clean in v1 but is {row['label']!r}")
        error_type, detailed, subtype, subtype_cn = RELABEL[sid]
        row["label"] = "error"
        row["error_type"] = error_type
        row["error_detailed_type"] = detailed
        row["legacy_error_type"] = ""
        row["legacy_error_detailed_type"] = ""
        row["solvability_subtype"] = subtype
        row["solvability_subtype_cn"] = subtype_cn
        changed.append(
            {
                "sample_id": sid,
                "error_type": error_type,
                "error_detailed_type": detailed,
                "model_detected_types": [
                    item.strip()
                    for item in verdicts[sid]["model_detected_type"].split(";")
                    if item.strip()
                ],
                "note": SECONDARY_NOTES.get(sid, verdicts[sid].get("note", "")),
            }
        )

    with DATASET_V2.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    PROVENANCE.write_text(
        json.dumps(
            {
                "purpose": "Dev A strict clean-label adjudication",
                "source_dataset": str(DATASET_V1),
                "source_dataset_sha256": sha256(DATASET_V1),
                "adjudication_file": str(ADJUDICATION),
                "adjudication_sha256": sha256(ADJUDICATION),
                "relabelled": changed,
                "kept_clean_pending": pending,
                "kept_clean_rejected": rejected,
                "new_vocabulary": {
                    "error_detailed_type": ["字符损坏"],
                    "solvability_subtype": ["no_valid_answer"],
                },
                "counts": {
                    "before_clean": before_clean,
                    "before_error": before_error,
                    "after_clean": sum(1 for r in rows if r["label"] == "clean"),
                    "after_error": sum(1 for r in rows if r["label"] != "clean"),
                },
                "note": "v2 only relabels samples that a human confirmed as real defects. Model outputs are unchanged; metrics are recomputed by joining on sample_id.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    dataset_v2 = {row["sample_id"]: row for row in rows}
    results = [
        json.loads(line)
        for line in RESULTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    rescored: list[dict[str, Any]] = []
    for record in results:
        row = dataset_v2[record["sample_id"]]
        is_clean = row["label"] == "clean"
        category = "clean" if is_clean else row["error_type"]
        detected = record.get("detected_error_types") or []
        rescored.append(
            {
                **record,
                "category": category,
                "is_clean": is_clean,
                "target_type_hit": (
                    None if is_clean else EXPECTED_LABEL.get(category) in detected
                ),
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "results.jsonl").open("w", encoding="utf-8") as handle:
        for record in rescored:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    before = summarize(results)
    after = summarize(rescored)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(after, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def flat(metrics: dict[str, Any]) -> dict[str, float | int]:
        out: dict[str, float | int] = {
            "clean": metrics["counts"]["clean"],
            "errors": metrics["counts"]["errors"],
            "false_positives": metrics["counts"]["false_positives"],
            "detected_errors": metrics["counts"]["detected_errors"],
            "unresolved_errors": metrics["counts"]["unresolved_errors"],
            "conservative_recall": metrics["conservative_recall"]["rate"],
            "conditional_recall": metrics["conditional_recall"]["rate"],
            "exact_type_recall": (metrics["exact_type_recall"] or {}).get("rate"),
            "macro_conservative_recall": metrics["macro_conservative_recall"],
            "clean_conservative_fpr": metrics["conservative_fpr"]["rate"],
        }
        for key, value in metrics["calibrated_precision"].items():
            out[f"calibrated_precision_{key}"] = value
        return out

    per_category = {
        name: {
            "before": {
                "total": before["by_category"].get(name, {}).get("total"),
                "recall": before["by_category"].get(name, {})
                .get("conservative", {})
                .get("rate"),
                "exact_type_recall": before["by_category"]
                .get(name, {})
                .get("exact_type_recall", {})
                .get("rate"),
            },
            "after": {
                "total": after["by_category"].get(name, {}).get("total"),
                "recall": after["by_category"].get(name, {})
                .get("conservative", {})
                .get("rate"),
                "exact_type_recall": after["by_category"]
                .get(name, {})
                .get("exact_type_recall", {})
                .get("rate"),
            },
        }
        for name in sorted(after["by_category"])
    }

    (OUT_DIR / "metrics_comparison.json").write_text(
        json.dumps(
            {
                "dataset_v2_sha256": sha256(DATASET_V2),
                "overall": {"before_v1_labels": flat(before), "after_v2_labels": flat(after)},
                "per_category": per_category,
                "wilson": {
                    "conservative_recall": after["conservative_recall"]["wilson_95"],
                    "exact_type_recall": after["exact_type_recall"]["wilson_95"],
                    "clean_fpr": after["conservative_fpr"]["wilson_95"],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(json.dumps(
        {
            "relabelled": len(changed),
            "pending": pending,
            "rejected": rejected,
            "before": flat(before),
            "after": flat(after),
            "dataset_v2_sha256": sha256(DATASET_V2),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
