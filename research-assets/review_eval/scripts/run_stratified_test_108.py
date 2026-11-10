#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stratified Evaluation on 108 samples (>=100 questions, ~34% of 320 dataset).

Covers all 9 error types + clean questions with stratified sampling:
- typo: 16
- punctuation: 8
- option_structure: 8
- type_mismatch: 8
- missing_info: 8
- ambiguity: 8
- unsolvable: 8
- answer_leakage: 8
- factual_logical: 8 (Agentic Tool Calling with 408 Knowledge Base)
- clean: 28 (False positive evaluation; 10 tested with KB Agentic Reviewer)
Total = 108 questions
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
sys.path.insert(0, str(SCRIPTS_DIR))
from agentic_reviewer import run_agentic_review  # noqa: E402
from router_and_retriever import parse_json_from_text  # noqa: E402

ROOT = SCRIPTS_DIR.parent
DATASET = ROOT / "dataset"
DATASET_CSV = DATASET / "review_eval_dataset.csv"
DATASET_GOLD = DATASET / "review_eval_gold.jsonl"
OUT_DIR = ROOT / "runs" / "stratified_108"
PROMPT_ROOT = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\prompts\reviewer-prompt\qwen38_27b"
)

TASK_MAP = {
    "typo": ("disabled", "typo_check"),
    "punctuation": ("explicit", "punctuation_check"),
    "option_structure": ("disabled", "options_check"),
    "type_mismatch": ("disabled", "mismatch_check"),
    "missing_info": ("disabled", "missing_check"),
    "ambiguity": ("disabled", "ambiguity_check"),
    "unsolvable": ("explicit", "unsolvability_check"),
    "answer_leakage": ("explicit", "answer_leak_check"),
    "factual_logical": ("agentic", "logic_check"),
}

EXPECTED_LABELS = {
    "typo": "错别字",
    "punctuation": "标点符号错误",
    "option_structure": "选项错误",
    "type_mismatch": "题目与题型不一致",
    "missing_info": "信息缺失",
    "ambiguity": "语义不清",
    "unsolvable": "题目无解",
    "answer_leakage": "答案泄露",
    "factual_logical": "事实/逻辑错误",
}

QUOTAS = {
    "typo": 16,
    "punctuation": 8,
    "option_structure": 8,
    "type_mismatch": 8,
    "missing_info": 8,
    "ambiguity": 8,
    "unsolvable": 8,
    "answer_leakage": 8,
    "factual_logical": 8,
    "clean": 28,
}


def load_task_prompt(mode: str, task: str) -> str:
    json_file = "JSON约束_with_think.txt" if mode == "explicit" else "JSON约束_without_think.txt"
    t_text = (PROMPT_ROOT / mode / "tasks" / f"{task}.txt").read_text(encoding="utf-8").strip()
    j_text = (PROMPT_ROOT / mode / json_file).read_text(encoding="utf-8").strip()
    return f"{t_text}\n\n{j_text}"


async def call_direct_review(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    full_text: str,
    timeout: float = 90.0,
) -> tuple[dict | None, float]:
    t0 = time.perf_counter()
    user_payload = "[INPUT_PAYLOAD]\n" + json.dumps({"reference": "", "detection_content": full_text}, ensure_ascii=False)
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
    parser.add_argument("--concurrency", type=int, default=6)
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
    gold_map = {}
    for line in DATASET_GOLD.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            gold_map[d["sample_id"]] = d

    # Stratified selection
    stratified_rows: list[dict] = []
    counts: dict[str, int] = defaultdict(int)

    for r in rows:
        cat = "clean" if r.get("label") == "clean" else r.get("error_type")
        if counts[cat] < QUOTAS.get(cat, 0):
            counts[cat] += 1
            stratified_rows.append(r)

    print(f"Selected {len(stratified_rows)} stratified samples across categories:")
    for cat, n in sorted(counts.items()):
        print(f"  {cat:<18}: {n}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "stratified_results.jsonl"
    existing_records = []
    done_ids = set()
    if out_file.exists():
        for line in out_file.open(encoding="utf-8"):
            if line.strip():
                try:
                    d = json.loads(line)
                    existing_records.append(d)
                    done_ids.add(d["sample_id"])
                except Exception:
                    pass
    print(f"Loaded {len(done_ids)} existing completed records.")

    out_fp = out_file.open("a", encoding="utf-8")

    loaded_prompts = {}
    for et, (m, t) in TASK_MAP.items():
        if m != "agentic":
            loaded_prompts[et] = load_task_prompt(m, t)

    sem = asyncio.Semaphore(args.concurrency)
    done_counter = len(done_ids)
    records = list(existing_records)

    remaining_rows = [r for r in stratified_rows if r["sample_id"] not in done_ids]
    print(f"Remaining {len(remaining_rows)} samples to process.")

    async with httpx.AsyncClient(timeout=120) as client:
        async def process_one(row: dict) -> dict | None:
            nonlocal done_counter
            async with sem:
                sample_id = row["sample_id"]
                is_clean = (row.get("label") == "clean")
                cat = "clean" if is_clean else row["error_type"]
                full_text = row["full_text"]
                subject = row.get("subject", "computer_network")
                gold = gold_map.get(sample_id, {})

                has_err = False
                detected_errors = []
                reason = ""
                tool_calls_count = 0
                tool_queries = []
                latency_ms = 0.0

                try:
                    if cat == "factual_logical" or (is_clean and done_counter % 2 == 0):
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
                        reason = res.reason
                        tool_calls_count = res.tool_calls_count
                        tool_queries = res.tool_queries
                        latency_ms = res.total_latency_ms
                    else:
                        target_task = cat if not is_clean else "typo"
                        sys_prompt = loaded_prompts.get(target_task, loaded_prompts["typo"])
                        p_data, lat = await call_direct_review(
                            client, args.base_url, api_key, args.model, sys_prompt, full_text, timeout=120.0
                        )
                        latency_ms = lat
                        if p_data:
                            has_err = bool(p_data.get("has_error", False))
                            detected_errors = p_data.get("errors", [])
                            reason = p_data.get("reason", "")
                except Exception as exc:
                    reason = f"Timeout/Exception: {exc}"

                type_hit = False
                span_hit = False
                if not is_clean:
                    exp_label = EXPECTED_LABELS.get(cat, "")
                    gold_errs = gold.get("errors", [])
                    gold_span = gold_errs[0].get("original_text", "") if gold_errs else ""

                    for de in detected_errors:
                        if de.get("error_type", "").strip() == exp_label:
                            type_hit = True
                        dt_span = de.get("original_text", "").strip()
                        if gold_span and dt_span and (gold_span in dt_span or dt_span in gold_span):
                            span_hit = True

                rec = {
                    "sample_id": sample_id,
                    "category": cat,
                    "is_clean": is_clean,
                    "subject": subject,
                    "has_error": has_err,
                    "type_hit": type_hit,
                    "span_hit": span_hit,
                    "reason": reason,
                    "detected_errors_count": len(detected_errors),
                    "tool_calls": tool_calls_count,
                    "tool_queries": tool_queries,
                    "latency_ms": round(latency_ms, 1),
                }

                done_counter += 1
                out_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fp.flush()
                records.append(rec)

                status_tag = "FP" if (is_clean and has_err) else ("TN" if is_clean else ("TP" if has_err else "FN"))
                tc_info = f"tools={tool_calls_count}" if tool_calls_count > 0 else ""
                print(f"[{done_counter:3d}/{len(stratified_rows)}] {sample_id:<28} | {cat:<16} -> {status_tag} {tc_info}", flush=True)
                return rec

        tasks = [asyncio.create_task(process_one(r)) for r in remaining_rows]
        await asyncio.gather(*tasks)

    out_fp.close()

    # Aggregate Statistics
    print("\n" + "=" * 90)
    print("STRATIFIED EVALUATION RESULTS (108 SAMPLES)")
    print("=" * 90)
    print(f"{'Category':<18} | {'Total':<6} | {'Detected':<8} | {'Recall/FPR':<10} | {'Type Hit':<10} | {'Span Hit':<10} | {'Avg Latency':<12}")
    print("-" * 90)

    by_cat = defaultdict(lambda: {"n": 0, "detected": 0, "type_hit": 0, "span_hit": 0, "latencies": [], "tools": 0})
    for r in records:
        c = r["category"]
        by_cat[c]["n"] += 1
        if r["has_error"]:
            by_cat[c]["detected"] += 1
        if r["type_hit"]:
            by_cat[c]["type_hit"] += 1
        if r["span_hit"]:
            by_cat[c]["span_hit"] += 1
        by_cat[c]["latencies"].append(r["latency_ms"])
        by_cat[c]["tools"] += r["tool_calls"]

    total_err_n = 0
    total_err_det = 0
    clean_n = 0
    clean_fp = 0

    for c in sorted(by_cat.keys()):
        st = by_cat[c]
        n = st["n"]
        det = st["detected"]
        avg_lat = sum(st["latencies"]) / n if n else 0
        if c == "clean":
            clean_n = n
            clean_fp = det
            rate_str = f"FPR:{det / n * 100:.1f}%"
            th_str = "-"
            sh_str = "-"
        else:
            total_err_n += n
            total_err_det += det
            rate_str = f"Rec:{det / n * 100:.1f}%"
            th_str = f"{st['type_hit'] / n * 100:.1f}%"
            sh_str = f"{st['span_hit'] / n * 100:.1f}%"

        print(f"{c:<18} | {n:<6} | {det:<8} | {rate_str:<10} | {th_str:<10} | {sh_str:<10} | {avg_lat:<12.0f}ms")

    print("-" * 90)
    overall_recall = f"{total_err_det / total_err_n * 100:.1f}%" if total_err_n else "0%"
    overall_fpr = f"{clean_fp / clean_n * 100:.1f}%" if clean_n else "0%"
    print(f"Overall Error Recall: {overall_recall} ({total_err_det}/{total_err_n}) | Clean False Positive Rate: {overall_fpr} ({clean_fp}/{clean_n})")
    print(f"Results saved to: {out_file}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
