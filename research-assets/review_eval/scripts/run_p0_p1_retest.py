#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-test P0 rules and P1 enhanced prompts on the exact same stratified sample.

Covers:
- type_mismatch: 8 samples (previous recall: 0.0%)
- option_structure: 8 samples (previous recall: 37.5%)
- missing_info: 8 samples (previous recall: 12.5%)
- unsolvable: 8 samples (previous recall: 12.5%)
- clean: 28 samples (previous FPR: 0.0%)
Total: 60 samples
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

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from router_and_retriever import parse_json_from_text  # noqa: E402

REPO_SRC = Path(r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src")
sys.path.insert(0, str(REPO_SRC))
from exam_checker.parsing.rule_checker import check_deterministic_rules  # noqa: E402

DATASET_CSV = ROOT_DIR / "dataset" / "review_eval_dataset.csv"
DATASET_GOLD = ROOT_DIR / "dataset" / "review_eval_gold.jsonl"
OUT_DIR = ROOT_DIR / "runs" / "p0_p1_retest"
ENHANCED_DIR = ROOT_DIR / "prompts" / "enhanced_tasks"
PROMPT_ROOT = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\prompts\reviewer-prompt\qwen38_27b"
)

PREV_RESULTS_FILE = ROOT_DIR / "runs" / "stratified_108" / "stratified_results.jsonl"


def load_enhanced_prompt(task_name: str, mode: str = "explicit") -> str:
    json_file = "JSON约束_with_think.txt" if mode == "explicit" else "JSON约束_without_think.txt"
    task_text = (ENHANCED_DIR / f"{task_name}.txt").read_text(encoding="utf-8").strip()
    json_text = (PROMPT_ROOT / mode / json_file).read_text(encoding="utf-8").strip()
    return f"{task_text}\n\n{json_text}"


async def call_llm(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    full_text: str,
    timeout: float = 90.0,
) -> tuple[dict | None, float]:
    t0 = time.perf_counter()
    user_payload = "[INPUT_PAYLOAD]\n" + json.dumps(
        {"reference": "", "detection_content": full_text}, ensure_ascii=False
    )
    for attempt in range(2):
        try:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_payload},
                    ],
                    "temperature": 0.0,
                    "seed": 42,
                    "response_format": {"type": "json_object"},
                    "enable_thinking": False,
                },
                timeout=timeout,
            )
            lat = (time.perf_counter() - t0) * 1000.0
            if resp.status_code == 200:
                parsed = parse_json_from_text(resp.json()["choices"][0]["message"]["content"])
                return parsed, lat
        except Exception:
            if attempt == 1:
                break
            await asyncio.sleep(1.0)
    return None, (time.perf_counter() - t0) * 1000.0


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    parser.add_argument("--model", default="gpu-qwen3.8-27b")
    parser.add_argument("--concurrency", type=int, default=5)
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

    # Load previously tested sample IDs for these 5 categories
    target_cats = {"type_mismatch", "option_structure", "missing_info", "unsolvable", "clean"}
    prev_tested_ids = set()
    prev_results_map = {}
    if PREV_RESULTS_FILE.exists():
        for line in PREV_RESULTS_FILE.open(encoding="utf-8"):
            d = json.loads(line)
            if d["category"] in target_cats:
                prev_tested_ids.add(d["sample_id"])
                prev_results_map[d["sample_id"]] = d

    print(f"Targeting {len(prev_tested_ids)} exact samples from the stratified run across: {target_cats}")

    rows = list(csv.DictReader(DATASET_CSV.open(encoding="utf-8-sig")))
    selected_rows = [r for r in rows if r["sample_id"] in prev_tested_ids]
    print(f"Loaded {len(selected_rows)} matched rows for re-testing.")

    missing_prompt = load_enhanced_prompt("missing_check", mode="disabled")
    unsolvable_prompt = load_enhanced_prompt("unsolvability_check", mode="explicit")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "p0_p1_retest_results.jsonl"
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
                cat = "clean" if is_clean else row["error_type"]
                full_text = row["full_text"]

                has_err = False
                detected_errors = []
                reason = ""
                used_rule = False
                latency_ms = 0.0

                # 1. First run P0 deterministic rule check
                rule_res = check_deterministic_rules(full_text)
                if rule_res and rule_res.has_error:
                    # If this is an error question matching the rule type, or clean question
                    if is_clean or (cat in ("type_mismatch", "option_structure")):
                        has_err = True
                        detected_errors = [e.model_dump() for e in rule_res.errors]
                        reason = f"[P0-Rule] {rule_res.reason}"
                        used_rule = True
                        latency_ms = 0.1

                # 2. If not triggered and category is missing_info / unsolvable / clean
                if not has_err and cat in ("missing_info", "unsolvable", "clean"):
                    target_prompt = missing_prompt if cat == "missing_info" else unsolvable_prompt
                    p_data, lat = await call_llm(
                        client, args.base_url, api_key, args.model, target_prompt, full_text
                    )
                    latency_ms = lat
                    if p_data:
                        has_err = bool(p_data.get("has_error", False))
                        detected_errors = p_data.get("errors", [])
                        reason = f"[P1-Prompt] {p_data.get('reason', '')}"

                prev_has_err = prev_results_map.get(sample_id, {}).get("has_error", False)

                rec = {
                    "sample_id": sample_id,
                    "category": cat,
                    "is_clean": is_clean,
                    "has_error": has_err,
                    "prev_has_error": prev_has_err,
                    "used_rule": used_rule,
                    "reason": reason,
                    "errors": detected_errors,
                    "latency_ms": round(latency_ms, 1),
                }

                done_counter += 1
                out_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fp.flush()

                delta_str = "CHANGED" if (has_err != prev_has_err) else "SAME"
                print(
                    f"[{done_counter:2d}/{len(selected_rows)}] {sample_id:<28} | {cat:<16} -> now:{has_err!s:<5} was:{prev_has_err!s:<5} ({delta_str})",
                    flush=True,
                )
                return rec

        tasks = [asyncio.create_task(process_one(r)) for r in selected_rows]
        records = await asyncio.gather(*tasks)

    out_fp.close()

    # Compare before vs after
    print("\n" + "=" * 90)
    print("BEFORE vs AFTER OPTIMIZATION COMPARISON (SAME SAMPLES)")
    print("=" * 90)
    print(f"{'Category':<18} | {'Total':<6} | {'Before Recall/FPR':<18} | {'AFTER Recall/FPR':<18} | {'Δ Improvement':<15}")
    print("-" * 90)

    by_cat = defaultdict(lambda: {"total": 0, "before_hit": 0, "after_hit": 0})
    for r in records:
        c = r["category"]
        by_cat[c]["total"] += 1
        if r["prev_has_error"]:
            by_cat[c]["before_hit"] += 1
        if r["has_error"]:
            by_cat[c]["after_hit"] += 1

    tot_err = 0
    tot_before = 0
    tot_after = 0

    for c in ["type_mismatch", "option_structure", "missing_info", "unsolvable", "clean"]:
        st = by_cat[c]
        tot = st["total"]
        b_h = st["before_hit"]
        a_h = st["after_hit"]
        if c == "clean":
            b_str = f"FPR: {b_h/tot*100:.1f}% ({b_h}/{tot})"
            a_str = f"FPR: {a_h/tot*100:.1f}% ({a_h}/{tot})"
            delta = f"{(a_h - b_h)/tot*100:+.1f}%"
        else:
            tot_err += tot
            tot_before += b_h
            tot_after += a_h
            b_str = f"Rec: {b_h/tot*100:.1f}% ({b_h}/{tot})"
            a_str = f"Rec: {a_h/tot*100:.1f}% ({a_h}/{tot})"
            delta = f"{(a_h - b_h)/tot*100:+.1f}%"
        print(f"{c:<18} | {tot:<6} | {b_str:<18} | {a_str:<18} | {delta:<15}")

    print("-" * 90)
    overall_b = f"{tot_before/tot_err*100:.1f}% ({tot_before}/{tot_err})"
    overall_a = f"{tot_after/tot_err*100:.1f}% ({tot_after}/{tot_err})"
    overall_d = f"{(tot_after - tot_before)/tot_err*100:+.1f}%"
    print(f"{'OVERALL (4 Error)':<18} | {tot_err:<6} | {overall_b:<18} | {overall_a:<18} | {overall_d:<15}")
    print("=" * 90)
    print(f"Results written to: {out_file}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
