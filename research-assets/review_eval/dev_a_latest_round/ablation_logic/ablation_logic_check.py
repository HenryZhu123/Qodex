#!/usr/bin/env python3
"""Ablation: does the multi-source KB help logic_check?

Arms (only the knowledge base differs):
  A0  KB off
  A1  single source (kb.sqlite, 7th edition only)
  A2  multi source (7th + 8th delta, conflict groups expanded with labels)

Sample: every factual_logical (logic_check) item from Dev A and Dev B
(20 + 20 = 40 positives) plus 60 clean items drawn with a fixed seed.

Only the logic_check specialist runs; JEV routing is bypassed.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent")
SERVICE_SRC = ROOT / "pi-coding-agent" / "services" / "exam-checker" / "src"
sys.path.insert(0, str(SERVICE_SRC))

from exam_checker.config import Settings  # noqa: E402
from exam_checker.domain.models import CheckerPayload  # noqa: E402
from exam_checker.integrations.knowledge_base import KnowledgeBaseRetriever  # noqa: E402
from exam_checker.integrations.specialist_reviewer import (  # noqa: E402
    OpenAICompatibleSpecialistReviewer,
)
from exam_checker.prompts.repositories import ReviewPromptRepository  # noqa: E402

DEV_A = ROOT / "research-assets/review_eval/taxonomy_v2/dev_a/strict/review_eval_dataset_v2.csv"
DEV_B = ROOT / "research-assets/review_eval/taxonomy_v2/dev_b/strict/blind_test_dataset.csv"
OUT_DIR = ROOT / "research-assets/review_eval/dev_a_latest_round/ablation_logic"
SAMPLE_CSV = OUT_DIR / "logic_sample_100.csv"
TARGET_LOGIC = "factual_logical"
CLEAN_COUNT = 60
SEED = 42


def load_rows(path: Path, source: str) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["_source"] = source
    return rows


def build_sample() -> list[dict]:
    rows = load_rows(DEV_A, "dev_a") + load_rows(DEV_B, "dev_b")
    logic = [row for row in rows if row.get("label") != "clean" and row.get("error_type") == TARGET_LOGIC]
    clean = [row for row in rows if row.get("label") == "clean"]
    rng = random.Random(SEED)
    picked_clean = rng.sample(clean, min(CLEAN_COUNT, len(clean)))
    sample = [
        {
            "sample_id": row["sample_id"],
            "source": row["_source"],
            "label": row["label"],
            "error_type": row.get("error_type", ""),
            "full_text": row["full_text"],
            "reference": row.get("reference", ""),
        }
        for row in logic + picked_clean
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with SAMPLE_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["sample_id", "source", "label", "error_type", "full_text", "reference"]
        )
        writer.writeheader()
        writer.writerows(sample)
    return sample


async def run_arm(arm: str, mode: str, sample: list[dict], settings: Settings) -> dict:
    prompts = ReviewPromptRepository(settings.review_prompt_root)
    reviewer = OpenAICompatibleSpecialistReviewer(
        settings.review_llm_base_url,
        settings.review_llm_api_key,
        settings.review_llm_model,
        prompts,
        timeout_seconds=settings.review_llm_timeout_seconds,
        max_concurrency=settings.review_llm_max_concurrency,
        max_attempts=settings.review_llm_max_attempts,
        knowledge_base=KnowledgeBaseRetriever(settings.knowledge_base_dir, mode=mode),
        reasoning_effort=settings.review_reasoning_effort,
        max_tokens=settings.review_max_tokens,
    )
    out_path = OUT_DIR / f"arm_{arm}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(4)
    results: list[dict] = []

    async def one(row: dict) -> None:
        payload = CheckerPayload(
            reference=row["reference"], detection_content=row["full_text"]
        )
        async with semaphore:
            started = datetime.now()
            try:
                result, latency, attempts = await reviewer.review("logic_check", payload)
                record = {
                    "sample_id": row["sample_id"],
                    "source": row["source"],
                    "label": row["label"],
                    "has_error": bool(result.has_error),
                    "error_types": [error.error_type for error in result.errors],
                    "kb_queries": getattr(result, "kb_queries", []),
                    "latency_ms": latency,
                    "attempts": attempts,
                    "error_code": None,
                }
            except Exception as exc:  # noqa: BLE001
                record = {
                    "sample_id": row["sample_id"],
                    "source": row["source"],
                    "label": row["label"],
                    "has_error": None,
                    "error_types": [],
                    "kb_queries": [],
                    "latency_ms": 0,
                    "attempts": 0,
                    "error_code": getattr(exc, "error_code", type(exc).__name__),
                }
            record["arm"] = arm
            results.append(record)

    await asyncio.gather(*(one(row) for row in sample))
    await reviewer.close()
    with out_path.open("w", encoding="utf-8") as handle:
        for record in results:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    tp = sum(1 for r in results if r["label"] != "clean" and r["has_error"] is True)
    fn = sum(1 for r in results if r["label"] != "clean" and r["has_error"] is False)
    fp = sum(1 for r in results if r["label"] == "clean" and r["has_error"] is True)
    tn = sum(1 for r in results if r["label"] == "clean" and r["has_error"] is False)
    failed = sum(1 for r in results if r["has_error"] is None)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    summary = {
        "arm": arm,
        "kb_mode": mode,
        "samples": len(results),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "failed": failed,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "fpr": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "avg_latency_ms": round(sum(r["latency_ms"] for r in results) / len(results)),
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default="A0,A1,A2")
    args = parser.parse_args()

    sample = build_sample()
    logic = sum(1 for row in sample if row["label"] != "clean")
    print(f"sample={len(sample)} logic={logic} clean={len(sample) - logic}", flush=True)

    settings = Settings.from_env()
    modes = {"A0": "off", "A1": "single", "A2": "multi"}
    summaries = []
    for arm in [item.strip() for item in args.arms.split(",") if item.strip()]:
        summaries.append(await run_arm(arm, modes[arm], sample, settings))

    (OUT_DIR / "ablation_summary.json").write_text(
        json.dumps(
            {
                "sample_csv": str(SAMPLE_CSV),
                "sample": len(sample),
                "logic": logic,
                "clean": len(sample) - logic,
                "model": settings.review_llm_model,
                "settings": {
                    "max_tokens": settings.review_max_tokens,
                    "reasoning_effort": settings.review_reasoning_effort,
                },
                "arms": summaries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
