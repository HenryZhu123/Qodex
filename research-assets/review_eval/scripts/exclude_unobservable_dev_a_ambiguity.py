#!/usr/bin/env python3
"""Exclude Dev-A mutations whose error depends on knowing deleted source text."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEV_A = ROOT / "research-assets" / "review_eval" / "taxonomy_v2" / "dev_a"
STRICT = DEV_A / "strict"

EXCLUDED = {
    "rev-ambiguity-refq-408-2017-10": (
        "Deleting '可能的' leaves a uniquely answerable question; the removed token "
        "cannot be inferred from the mutated text."
    ),
    "rev-ambiguity-refq-408-2018-12": (
        "Deleting '主要' does not create two valid interpretations or multiple answers; "
        "the removed token cannot be inferred from the mutated text."
    ),
}


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> None:
    dataset_path = DEV_A / "review_eval_dataset.csv"
    with dataset_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        dataset_rows = list(reader)
    if "strict_eval_eligible" not in fieldnames:
        raise ValueError("Dev-A dataset is missing strict_eval_eligible")

    found = set()
    for row in dataset_rows:
        sample_id = row.get("sample_id", "")
        if sample_id in EXCLUDED:
            row["strict_eval_eligible"] = "False"
            found.add(sample_id)
    if found != set(EXCLUDED):
        raise ValueError(f"Missing excluded samples: {sorted(set(EXCLUDED) - found)}")

    with dataset_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(dataset_rows)

    full_rows = read_jsonl(DEV_A / "review_eval_full.jsonl")
    gold_rows = read_jsonl(DEV_A / "review_eval_gold.jsonl")
    for rows in (full_rows, gold_rows):
        for row in rows:
            if row.get("sample_id") in EXCLUDED:
                row["strict_eval_eligible"] = False

    write_jsonl(DEV_A / "review_eval_full.jsonl", full_rows)
    write_jsonl(DEV_A / "review_eval_gold.jsonl", gold_rows)

    strict_ids = {
        row["sample_id"]
        for row in dataset_rows
        if row.get("strict_eval_eligible", "").lower() == "true"
    }
    strict_dataset = [row for row in dataset_rows if row["sample_id"] in strict_ids]
    STRICT.mkdir(parents=True, exist_ok=True)
    with (STRICT / "review_eval_dataset.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(strict_dataset)
    write_jsonl(
        STRICT / "review_eval_full.jsonl",
        [row for row in full_rows if row.get("sample_id") in strict_ids],
    )
    write_jsonl(
        STRICT / "review_eval_gold.jsonl",
        [row for row in gold_rows if row.get("sample_id") in strict_ids],
    )

    audit = {
        "excluded_from_strict": EXCLUDED,
        "strict_sample_count": len(strict_dataset),
        "non_strict_sample_count": len(dataset_rows),
    }
    (DEV_A / "strict_exclusion_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
