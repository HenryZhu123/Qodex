#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test and evaluate autonomous router & targeted retriever (Phase 1).

Measures:
1. Decision distribution (NEED_KB vs SKIP) across different error categories:
   - Surface errors: typo, punctuation, option_structure
   - Factual & logical errors: factual_logical, unsolvable
   - Clean baseline questions
2. Router latency vs Retrieval latency
3. Top-k Evidence hit rate and heading path accuracy
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from router_and_retriever import call_router, format_evidence_block  # noqa: E402

ROOT = SCRIPTS.parent
DATASET_CSV = ROOT / "dataset" / "review_eval_dataset.csv"
OUT_DIR = ROOT / "runs" / "phase1_router"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    parser.add_argument("--model", default="gpu-qwen3.8-27b")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args()

    api_key = os.environ.get("TALKWEB_API_KEY", "")
    if not api_key:
        # Try getting from user environment on Windows
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                api_key, _ = winreg.QueryValueEx(key, "TALKWEB_API_KEY")
        except Exception:
            pass

    if not api_key:
        print("[ERROR] TALKWEB_API_KEY is not set.")
        return 1

    rows = list(csv.DictReader(DATASET_CSV.open(encoding="utf-8-sig")))

    # Select balanced sample:
    # 1. Surface errors: 5 typo, 5 punctuation, 5 option_structure (total 15)
    # 2. Fact/Logic errors: 10 factual_logical, 5 unsolvable (total 15)
    # 3. Clean samples: 10 clean (total 10)
    # Total = 40 samples
    target_counts = {
        "typo": 5,
        "punctuation": 5,
        "option_structure": 5,
        "factual_logical": 10,
        "unsolvable": 5,
        "clean": 10,
    }

    selected_rows = []
    curr_counts = defaultdict(int)
    for r in rows:
        cat = "clean" if r.get("label") == "clean" else r.get("error_type")
        if cat in target_counts and curr_counts[cat] < target_counts[cat]:
            curr_counts[cat] += 1
            selected_rows.append(r)

    print(f"Loaded {len(selected_rows)} samples across categories: {dict(curr_counts)}")

    out_path = Path(args.out)
    out_path.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(args.concurrency)
    results = []

    async with httpx.AsyncClient() as client:
        async def process_one(row: dict) -> dict:
            async with sem:
                sample_id = row.get("sample_id", "")
                cat = "clean" if row.get("label") == "clean" else row.get("error_type")
                full_text = row.get("full_text", "")
                sub_hint = row.get("subject", "")

                decision = await call_router(
                    client=client,
                    base_url=args.base_url,
                    api_key=api_key,
                    model=args.model,
                    full_text=full_text,
                    subject_hint=sub_hint,
                )

                rec = {
                    "sample_id": sample_id,
                    "category": cat,
                    "subject": sub_hint,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "detected_subject": decision.subject,
                    "search_queries": decision.search_queries,
                    "router_latency_ms": round(decision.latency_ms, 1),
                    "retrieval_latency_ms": round(decision.retrieval_latency_ms, 1),
                    "evidence_count": len(decision.evidence),
                    "evidence_headings": [ev.heading_path for ev in decision.evidence],
                    "evidence_preview": [ev.content[:100] for ev in decision.evidence],
                }
                return rec

        tasks = [asyncio.create_task(process_one(r)) for r in selected_rows]
        results = await asyncio.gather(*tasks)

    # Save details
    out_file = out_path / "router_eval_results.jsonl"
    with out_file.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Aggregate stats
    stats_by_cat = defaultdict(lambda: {"total": 0, "need_kb": 0, "skip": 0, "router_lat": [], "retrieval_lat": []})
    for r in results:
        c = r["category"]
        stats_by_cat[c]["total"] += 1
        if r["decision"] == "NEED_KB":
            stats_by_cat[c]["need_kb"] += 1
        else:
            stats_by_cat[c]["skip"] += 1
        stats_by_cat[c]["router_lat"].append(r["router_latency_ms"])
        if r["retrieval_latency_ms"] > 0:
            stats_by_cat[c]["retrieval_lat"].append(r["retrieval_latency_ms"])

    print("\n" + "=" * 80)
    print("PHASE 1 ROUTER EVALUATION SUMMARY")
    print("=" * 80)
    print(f"{'Category':<18} | {'Total':<6} | {'NEED_KB':<8} | {'SKIP':<6} | {'KB Rate':<8} | {'Avg Rtr ms':<10} | {'Avg Ret ms':<10}")
    print("-" * 80)

    total_need = 0
    total_skip = 0
    all_rtr_lats = []
    all_ret_lats = []

    for cat in sorted(stats_by_cat.keys()):
        st = stats_by_cat[cat]
        tot = st["total"]
        n_kb = st["need_kb"]
        n_sk = st["skip"]
        total_need += n_kb
        total_skip += n_sk
        rate = f"{n_kb / tot * 100:.1f}%"
        avg_rtr = sum(st["router_lat"]) / len(st["router_lat"]) if st["router_lat"] else 0
        avg_ret = sum(st["retrieval_lat"]) / len(st["retrieval_lat"]) if st["retrieval_lat"] else 0
        all_rtr_lats.extend(st["router_lat"])
        all_ret_lats.extend(st["retrieval_lat"])
        print(f"{cat:<18} | {tot:<6} | {n_kb:<8} | {n_sk:<6} | {rate:<8} | {avg_rtr:<10.1f} | {avg_ret:<10.1f}")

    print("-" * 80)
    overall_kb_rate = f"{total_need / len(results) * 100:.1f}%"
    overall_avg_rtr = sum(all_rtr_lats) / len(all_rtr_lats) if all_rtr_lats else 0
    overall_avg_ret = sum(all_ret_lats) / len(all_ret_lats) if all_ret_lats else 0
    print(f"{'OVERALL':<18} | {len(results):<6} | {total_need:<8} | {total_skip:<6} | {overall_kb_rate:<8} | {overall_avg_rtr:<10.1f} | {overall_avg_ret:<10.1f}")
    print("=" * 80)

    # Show a few examples of queries and evidence
    print("\nSAMPLE ROUTED QUERIES & EVIDENCE (factual_logical & unsolvable):")
    for r in results:
        if r["category"] in ("factual_logical", "unsolvable") and r["decision"] == "NEED_KB":
            print(f"- [{r['sample_id']}] ({r['category']}) -> Queries: {r['search_queries']}")
            print(f"  Headings: {r['evidence_headings']}")
            print(f"  Reason: {r['reason']}")
            break

    print(f"\nDetailed evaluation written to: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
