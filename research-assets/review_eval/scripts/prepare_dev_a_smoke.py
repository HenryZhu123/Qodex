#!/usr/bin/env python3
"""Prepare the deterministic 24-row Dev-A end-to-end smoke set."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
REVIEW_ROOT = ROOT / "research-assets" / "review_eval"
SERVICE_ROOT = ROOT / "pi-coding-agent" / "services" / "exam-checker"
RUN_DIR = REVIEW_ROOT / "dev_a_latest_round" / "dev_a_e2e_20261031"
SOURCE = REVIEW_ROOT / "taxonomy_v2" / "dev_a" / "strict" / "review_eval_dataset.csv"
OUTPUT = RUN_DIR / "smoke_dataset.csv"

ERROR_TYPES = (
    "ambiguity",
    "answer_leakage",
    "factual_logical",
    "option_structure",
    "punctuation",
    "solvability_failure",
    "type_mismatch",
    "typo",
)
SUBJECTS = ("data_structure", "computer_organization", "operating_system", "computer_network")
PREFERRED_SMOKE_IDS: dict[str, tuple[str, ...]] = {
    "ambiguity": (
        "rev-ambiguity-refq-408-2025-05",
        "rev-ambiguity-refq-408-2023-38",
    ),
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def choose_distinct_subjects(rows: list[dict[str, str]], count: int) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: (item.get("subject", ""), item["sample_id"])):
        grouped[row.get("subject", "")].append(row)
    chosen: list[dict[str, str]] = []
    for subject in SUBJECTS:
        if grouped.get(subject) and len(chosen) < count:
            chosen.append(grouped[subject].pop(0))
    if len(chosen) < count:
        remaining = sorted(
            [row for values in grouped.values() for row in values],
            key=lambda item: item["sample_id"],
        )
        chosen.extend(remaining[: count - len(chosen)])
    return chosen


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return result.stdout.strip()


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    selected: list[dict[str, str]] = []
    for error_type in ERROR_TYPES:
        candidates = [row for row in rows if row.get("error_type") == error_type]
        preferred_ids = PREFERRED_SMOKE_IDS.get(error_type, ())
        if preferred_ids:
            by_id = {row["sample_id"]: row for row in candidates}
            picked = [by_id[sample_id] for sample_id in preferred_ids if sample_id in by_id]
        else:
            picked = choose_distinct_subjects(candidates, 2)
        if len(picked) != 2:
            raise ValueError(f"unable to select two rows for {error_type}")
        selected.extend(picked)
    for subject in SUBJECTS:
        candidates = sorted(
            [row for row in rows if row.get("label") == "clean" and row.get("subject") == subject],
            key=lambda item: item["sample_id"],
        )
        if len(candidates) < 2:
            raise ValueError(f"unable to select two clean rows for {subject}")
        selected.extend(candidates[:2])

    ids = [row["sample_id"] for row in selected]
    if len(selected) != 24 or len(ids) != len(set(ids)):
        raise ValueError("smoke selection must contain 24 unique samples")
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)

    prompt_roots = [
        SERVICE_ROOT / "prompts" / "reviewer-prompt" / "qwen38_27b",
        SERVICE_ROOT / "prompts" / "jev-prompt",
    ]
    prompt_hashes: dict[str, str] = {}
    for prompt_root in prompt_roots:
        for path in sorted(prompt_root.rglob("*")):
            if path.is_file():
                prompt_hashes[str(path.relative_to(SERVICE_ROOT))] = sha256_file(path)

    manifest: dict[str, Any] = {
        "run_id": RUN_DIR.name,
        "source_dataset": str(SOURCE),
        "source_dataset_sha256": sha256_file(SOURCE),
        "smoke_dataset": str(OUTPUT),
        "smoke_dataset_sha256": sha256_file(OUTPUT),
        "git_commit": git_output("rev-parse", "HEAD"),
        "git_dirty_paths": git_output("status", "--short").splitlines(),
        "selection": {
            "samples": len(selected),
            "by_category": dict(Counter("clean" if row["label"] == "clean" else row["error_type"] for row in selected)),
            "by_subject": dict(Counter(row.get("subject", "") for row in selected)),
            "sample_ids": ids,
        },
        "configuration": {
            "runner": "scripts/run_end_to_end_evaluation.py",
            "review_base_url": "https://llm.talkweb.com.cn/v1",
            "review_model": "gpu-qwen3.8-27b",
            "jev_endpoint": "https://aihubmix.com/v1/systemone",
            "jev_requested_model": "jev-1.14",
            "runner_concurrency": 1,
            "reviewer_max_concurrency": 2,
            "secrets_recorded": False,
        },
        "prompt_sha256": prompt_hashes,
        "blind_test_accessed": True,
        "blind_test_access_note": (
            "A broad read-only rg on 2026-10-31 accidentally returned one Blind-v2 "
            "expansion record. No blind evaluation was run and no blind file was modified."
        ),
    }
    (RUN_DIR / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest["selection"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
