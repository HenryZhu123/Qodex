#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 Factual/Logical Retest: Evaluates P2 on the exact same 8 factual_logical samples + 10 clean samples.

Workflow:
1. Fast-path: check_factual_guards (0ms)
2. Agentic Tool Call path: run_agentic_review with 408 Knowledge Base
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path

import httpx

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from agentic_reviewer import run_agentic_review  # noqa: E402
from router_and_retriever import parse_json_from_text  # noqa: E402

REPO_SRC = Path(r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src")
sys.path.insert(0, str(REPO_SRC))
from exam_checker.parsing.factual_guard import check_factual_guards  # noqa: E402

DATASET_CSV = ROOT_DIR / "dataset" / "review_eval_dataset.csv"
OUT_DIR = ROOT_DIR / "runs" / "p2_retest"

TARGET_FACTUAL_IDS = [
    "rev-factual_logical-refq-408-2011-32",
    "rev-factual_logical-refq-408-2009-29",
    "rev-factual_logical-refq-408-2010-39",
    "rev-factual_logical-refq-408-2010-27",
    "rev-factual_logical-refq-408-2014-36",
    "rev-factual_logical-refq-408-2016-14",
    "rev-factual_logical-refq-408-2014-37",
    "rev-factual_logical-refq-408-2016-25",
]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    parser.add_argument("--model", default="gpu-qwen3.8-27b")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    api_key = os.environ.get("TALKWEB_API_KEY", "")
    if not api_key:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                api_key, _ = winreg.QueryValueEx(key, "TALKWEB_API_KEY")
        except Exception:
            pass

    if not api_key:
        print("[ERROR] TALKWEB_API_KEY not set.")
        return 1

    rows = list(csv.DictReader(DATASET_CSV.open(encoding="utf-8-sig")))
    fact_rows = [r for r in rows if r["sample_id"] in TARGET_FACTUAL_IDS]
    clean_rows = [r for r in rows if r.get("label") == "clean"][:10]
    test_samples = fact_rows + clean_rows

    print(f"Loaded {len(fact_rows)} factual_logical samples + {len(clean_rows)} clean samples for P2 re-test.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "p2_retest_results.jsonl"
    out_fp = out_file.open("w", encoding="utf-8")

    sem = asyncio.Semaphore(args.concurrency)
    done_counter = 0
    records = []

    async with httpx.AsyncClient(timeout=120) as client:
        async def process_one(row: dict) -> dict:
            nonlocal done_counter
            async with sem:
                sample_id = row["sample_id"]
                is_clean = (row.get("label") == "clean")
                cat = "clean" if is_clean else "factual_logical"
                full_text = row["full_text"]
                subject = row.get("subject", "computer_network")

                t0 = time.perf_counter()
                has_err = False
                detected_errors = []
                reason = ""
                used_guard = False
                tool_calls_count = 0
                latency_ms = 0.0

                # 1. Check deterministic factual guards
                guard_res = check_factual_guards(full_text)
                if guard_res and guard_res.has_error:
                    has_err = True
                    detected_errors = [e.model_dump() for e in guard_res.errors]
                    reason = f"[Guard] {guard_res.reason}"
                    used_guard = True
                    latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)

                # 2. If not caught by guard, execute Agentic Tool Calling with 408 KB
                if not has_err:
                    try:
                        res = await run_agentic_review(
                            client=client,
                            base_url=args.base_url,
                            api_key=api_key,
                            model=args.model,
                            full_text=full_text,
                            subject=subject,
                            timeout=120.0,
                        )
                        has_err = res.has_error
                        detected_errors = res.errors
                        reason = f"[Agentic-KB] {res.reason}"
                        tool_calls_count = res.tool_calls_count
                        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                    except Exception as exc:
                        reason = f"Timeout/Exception: {exc}"
                        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)

                rec = {
                    "sample_id": sample_id,
                    "category": cat,
                    "is_clean": is_clean,
                    "has_error": has_err,
                    "used_guard": used_guard,
                    "tool_calls": tool_calls_count,
                    "reason": reason,
                    "errors": detected_errors,
                    "latency_ms": latency_ms,
                }

                done_counter += 1
                out_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fp.flush()
                records.append(rec)

                tag = "FP" if (is_clean and has_err) else ("TN" if is_clean else ("TP" if has_err else "FN"))
                tc_info = "guard" if used_guard else (f"tools={tool_calls_count}" if tool_calls_count > 0 else "no-tool")
                print(f"[{done_counter:2d}/{len(test_samples)}] {sample_id:<36} | {cat:<16} -> {tag} ({tc_info})", flush=True)
                return rec

        tasks = [asyncio.create_task(process_one(r)) for r in test_samples]
        await asyncio.gather(*tasks)

    out_fp.close()

    # Compare before vs after
    fact_recs = [r for r in records if not r["is_clean"]]
    clean_recs = [r for r in records if r["is_clean"]]

    tp = sum(1 for r in fact_recs if r["has_error"])
    fn = len(fact_recs) - tp
    fp = sum(1 for r in clean_recs if r["has_error"])
    tn = len(clean_recs) - fp

    recall = tp / len(fact_recs) * 100 if fact_recs else 0.0
    fpr = fp / len(clean_recs) * 100 if clean_recs else 0.0

    print("\n" + "=" * 80)
    print("P2 FACTUAL/LOGICAL RETEST SUMMARY")
    print("=" * 80)
    print(f"factual_logical Recall (Before: 0.0% [0/8]) -> AFTER: {recall:.1f}% ({tp}/{len(fact_recs)})")
    print(f"clean False Positive Rate (FPR)              -> AFTER: {fpr:.1f}% ({fp}/{len(clean_recs)})")
    print(f"Guard Triggered: {sum(1 for r in fact_recs if r['used_guard'])}/{len(fact_recs)} samples")
    print("=" * 80)
    print(f"Detailed logs written to: {out_file}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
