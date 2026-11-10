#!/usr/bin/env python3
"""Measure how the model picks the knowledge-base subject with no routing prompt.

The prompt carries no subject guidance; the only hint is the `subject` field
description in the tool schema. For each logic item we record the subjects the
model asked for and compare with the subject label stored on the dataset row.

Run cost: one agentic review per item (usually 1-2 tool rounds).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(r"D:\Code\hku\LLM\hku_agent")
sys.path.insert(0, str(ROOT / "pi-coding-agent/services/exam-checker/src"))

from exam_checker.integrations.knowledge_base import KnowledgeBaseRetriever  # noqa: E402
from exam_checker.integrations.specialist_reviewer import (  # noqa: E402
    OpenAICompatibleSpecialistReviewer,
)
from exam_checker.domain.models import CheckerPayload  # noqa: E402
from exam_checker.prompts.repositories import ReviewPromptRepository  # noqa: E402

SERVICE = ROOT / "pi-coding-agent" / "services" / "exam-checker"
OUT = ROOT / "research-assets" / "review_eval" / "dev_a_latest_round" / "subject_routing"
DEV_A = ROOT / "research-assets/review_eval/taxonomy_v2/dev_a/strict/review_eval_dataset_v2.csv"
DEV_B = ROOT / "research-assets/review_eval/taxonomy_v2/dev_b/strict/blind_test_dataset.csv"

SUBJECT_OF_LABEL = {
    "计算机网络": "computer_network",
    "操作系统": "operating_system",
    "计算机组成原理": "computer_organization",
    "数据结构": "data_structure",
}


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (SERVICE / ".env.local").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def load_samples(limit: int) -> list[dict]:
    rows: list[dict] = []
    for path, source in ((DEV_A, "dev_a"), (DEV_B, "dev_b")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("label") == "clean":
                    continue
                if row.get("error_type") != "factual_logical":
                    continue
                text = row.get("reference") or ""
                subject = ""
                for cn, en in SUBJECT_OF_LABEL.items():
                    if cn in text:
                        subject = en
                        break
                rows.append({
                    "sample_id": row["sample_id"],
                    "source": source,
                    "expected_subject": subject,
                    "subject_label": next((cn for cn in SUBJECT_OF_LABEL if cn in text), ""),
                    "reference": text,
                    "full_text": row["full_text"],
                })
    return rows[:limit] if limit else rows


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--model", default="qwen/qwen-2.5-72b-instruct")
    parser.add_argument("--api-key-var", default="EXAM_CHECKER_JEV_API_KEY")
    args = parser.parse_args()

    env = load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    samples = load_samples(args.limit)
    print(json.dumps({"samples": len(samples),
                      "with_subject_label": sum(1 for s in samples if s["expected_subject"])},
                     ensure_ascii=False), flush=True)

    kb = KnowledgeBaseRetriever(mode="single")
    reviewer = OpenAICompatibleSpecialistReviewer(
        base_url=args.base_url,
        api_key=env[args.api_key_var],
        model=args.model,
        prompts=ReviewPromptRepository(SERVICE / "prompts" / "reviewer-prompt" / "qwen38_27b"),
        timeout_seconds=args.timeout,
        max_concurrency=args.concurrency,
        max_attempts=2,
        knowledge_base=kb,
        max_tokens=int(env.get("EXAM_CHECKER_REVIEW_MAX_TOKENS", "2048")),
        agentic_logic_prompt_path=ROOT / "research-assets/review_eval/prompts/agentic_logic_check/task.txt",
    )

    results: list[dict] = []
    semaphore = asyncio.Semaphore(args.concurrency)

    async def one(sample: dict) -> None:
        payload = CheckerPayload(reference=sample["reference"], detection_content=sample["full_text"])
        async with semaphore:
            try:
                result, latency_ms, attempts = await reviewer.review("logic_check", payload)
                queries = [q for q in result.kb_queries]
                subjects = []
                for q in queries:
                    if q.startswith("["):
                        subjects.append(q[1:q.find("]")])
                results.append({
                    **sample,
                    "detected": bool(result.has_error),
                    "kb_queries": queries,
                    "asked_subjects": subjects,
                    "latency_ms": latency_ms,
                    "attempts": attempts,
                    "error": None,
                })
            except Exception as exc:  # noqa: BLE001
                results.append({**sample, "detected": None, "kb_queries": [],
                                "asked_subjects": [], "latency_ms": 0, "attempts": 0,
                                "error": type(exc).__name__})
            print(".", end="", flush=True)

    await asyncio.gather(*(one(s) for s in samples))
    print(flush=True)
    await reviewer.aclose() if hasattr(reviewer, "aclose") else None

    with (OUT / "results.jsonl").open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    labelled = [r for r in results if r["expected_subject"] and r["asked_subjects"]]
    agree = sum(1 for r in labelled if r["asked_subjects"][0] == r["expected_subject"])
    any_agree = sum(1 for r in labelled if r["expected_subject"] in r["asked_subjects"])
    summary = {
        "n": len(results),
        "failed": sum(1 for r in results if r["error"]),
        "queried_kb": sum(1 for r in results if r["kb_queries"]),
        "detected": sum(1 for r in results if r["detected"]),
        "with_subject_label": len(labelled),
        "first_subject_agree": agree,
        "first_subject_agree_rate": round(agree / len(labelled), 4) if labelled else 0.0,
        "any_subject_agree": any_agree,
        "asked_subject_counts": dict(Counter(s for r in results for s in r["asked_subjects"])),
        "mismatch_examples": [
            {"sample_id": r["sample_id"], "expected": r["expected_subject"],
             "asked": r["asked_subjects"]}
            for r in labelled if r["asked_subjects"][0] != r["expected_subject"]
        ][:10],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
