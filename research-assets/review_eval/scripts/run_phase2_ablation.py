#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2 Ablation Experiment: Factual/Logical Review.

Compares three conditions:
  1. no_kb       - Original logic_check without KB
  2. blind_kb    - Static blind KB retrieval injected into reference
  3. agentic_kb  - Autonomous Tool Calling (solve-verify + condition suspicion + on-demand search_kb)

Evaluates:
  - Recall on 20 factual_logical error questions
  - False Positive Rate (FPR) on 20 clean questions
  - Tool Trigger Rate and Average Latency
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
sys.path.insert(0, str(SCRIPTS_DIR))
from agentic_reviewer import run_agentic_review  # noqa: E402
from router_and_retriever import (  # noqa: E402
    format_evidence_block,
    parse_json_from_text,
    targeted_retrieve,
)

ROOT = SCRIPTS_DIR.parent
DATASET_CSV = ROOT / "dataset" / "review_eval_dataset.csv"
OUT_DIR = ROOT / "runs" / "phase2_ablation"
PROMPT_ROOT = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\prompts\reviewer-prompt\qwen38_27b"
)


def load_stock_logic_prompt() -> str:
    task = (PROMPT_ROOT / "explicit" / "tasks" / "logic_check.txt").read_text(encoding="utf-8").strip()
    out = (PROMPT_ROOT / "explicit" / "JSON约束_with_think.txt").read_text(encoding="utf-8").strip()
    return f"{task}\n\n{out}"


def load_blind_kb_prompt() -> str:
    kb_task = (ROOT / "prompts" / "kb_aware" / "explicit" / "tasks" / "logic_check.txt").read_text(encoding="utf-8").strip()
    out = (ROOT / "prompts" / "kb_aware" / "explicit" / "JSON约束_with_think.txt").read_text(encoding="utf-8").strip()
    return f"{kb_task}\n\n{out}"


async def call_single_prompt(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    payload: dict,
    timeout: float = 90.0,
) -> tuple[dict | None, float]:
    t0 = time.perf_counter()
    user_content = "[INPUT_PAYLOAD]\n" + json.dumps(payload, ensure_ascii=False)
    try:
        r = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.0,
                "seed": 42,
                "response_format": {"type": "json_object"},
                "enable_thinking": False,
            },
            timeout=timeout,
        )
        lat = (time.perf_counter() - t0) * 1000.0
        if r.status_code != 200:
            return None, lat
        data = parse_json_from_text(r.json()["choices"][0]["message"]["content"])
        return data, lat
    except Exception:
        return None, (time.perf_counter() - t0) * 1000.0


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    parser.add_argument("--model", default="gpu-qwen3.8-27b")
    parser.add_argument("--error-limit", type=int, default=5)
    parser.add_argument("--clean-limit", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=3)
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
    fact_rows = [r for r in rows if r.get("error_type") == "factual_logical"][: args.error_limit]
    clean_rows = [r for r in rows if r.get("label") == "clean"][: args.clean_limit]

    test_samples = fact_rows + clean_rows
    print(f"Loaded {len(fact_rows)} factual_logical error questions + {len(clean_rows)} clean questions.", flush=True)

    stock_prompt = load_stock_logic_prompt()
    blind_prompt = load_blind_kb_prompt()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "phase2_ablation_results.jsonl"
    out_fp = out_file.open("w", encoding="utf-8")

    sem = asyncio.Semaphore(args.concurrency)
    records = []
    counter = 0

    async with httpx.AsyncClient(timeout=120) as client:
        async def run_sample(row: dict) -> dict:
            nonlocal counter
            async with sem:
                sample_id = row.get("sample_id", "")
                is_error = (row.get("label") != "clean")
                full_text = row.get("full_text", "")
                subj = row.get("subject", "computer_network")

                # Condition 1: no_kb
                payload_no_kb = {"reference": "", "detection_content": full_text}
                p_no, lat_no = await call_single_prompt(client, args.base_url, api_key, args.model, stock_prompt, payload_no_kb)
                has_err_no = bool(p_no and p_no.get("has_error", False))

                # Condition 2: blind_kb
                evs_blind, _ = targeted_retrieve(subj, [full_text[:50]], top_k=2)
                ev_str = format_evidence_block(evs_blind)
                payload_blind = {"reference": ev_str, "detection_content": full_text}
                p_blind, lat_blind = await call_single_prompt(client, args.base_url, api_key, args.model, blind_prompt, payload_blind)
                has_err_blind = bool(p_blind and p_blind.get("has_error", False))

                # Condition 3: agentic_kb
                p_agentic = await run_agentic_review(
                    client=client,
                    base_url=args.base_url,
                    api_key=api_key,
                    model=args.model,
                    full_text=full_text,
                    subject=subj,
                )
                has_err_agentic = p_agentic.has_error

                res = {
                    "sample_id": sample_id,
                    "is_error": is_error,
                    "subject": subj,
                    "no_kb": {"has_error": has_err_no, "latency_ms": round(lat_no, 1)},
                    "blind_kb": {"has_error": has_err_blind, "latency_ms": round(lat_blind, 1)},
                    "agentic_kb": {
                        "has_error": has_err_agentic,
                        "latency_ms": round(p_agentic.total_latency_ms, 1),
                        "tool_calls": p_agentic.tool_calls_count,
                        "tool_queries": p_agentic.tool_queries,
                        "reason": p_agentic.reason,
                    },
                }
                counter += 1
                out_fp.write(json.dumps(res, ensure_ascii=False) + "\n")
                out_fp.flush()
                tc_info = f"tools={p_agentic.tool_calls_count}" if p_agentic.tool_calls_count > 0 else "no-tool"
                print(f"[{counter}/{len(test_samples)}] {sample_id} ({'ERR' if is_error else 'CLN'}) -> no_kb:{has_err_no} blind:{has_err_blind} agentic:{has_err_agentic} ({tc_info})", flush=True)
                return res

        tasks = [asyncio.create_task(run_sample(r)) for r in test_samples]
        records = await asyncio.gather(*tasks)

    out_fp.close()

    # Compute Metrics
    # Error samples (is_error=True)
    err_recs = [r for r in records if r["is_error"]]
    clean_recs = [r for r in records if not r["is_error"]]

    n_err = len(err_recs)
    n_clean = len(clean_recs)

    def stats(cond_name: str):
        tp = sum(1 for r in err_recs if r[cond_name]["has_error"])
        fn = n_err - tp
        fp = sum(1 for r in clean_recs if r[cond_name]["has_error"])
        tn = n_clean - fp
        recall = tp / n_err if n_err else 0
        fpr = fp / n_clean if n_clean else 0
        precision = tp / (tp + fp) if (tp + fp) else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
        avg_lat = sum(r[cond_name]["latency_ms"] for r in records) / len(records)
        return {
            "TP": tp, "FN": fn, "FP": fp, "TN": tn,
            "Recall": f"{recall * 100:.1f}%",
            "FPR": f"{fpr * 100:.1f}%",
            "Precision": f"{precision * 100:.1f}%",
            "F1": f"{f1:.3f}",
            "AvgLat": f"{avg_lat:.0f}ms",
        }

    s_no = stats("no_kb")
    s_blind = stats("blind_kb")
    s_agentic = stats("agentic_kb")

    # Agentic tool call stats
    tot_tool_calls = sum(r["agentic_kb"]["tool_calls"] for r in records)
    triggered_samples = sum(1 for r in records if r["agentic_kb"]["tool_calls"] > 0)
    trigger_rate = triggered_samples / len(records) * 100

    print("\n" + "=" * 90)
    print("PHASE 2 ABLATION EXPERIMENTAL RESULTS")
    print("=" * 90)
    print(f"{'Condition':<14} | {'Recall (TP/20)':<16} | {'FPR (FP/20)':<14} | {'Precision':<12} | {'F1':<8} | {'Avg Latency':<12}")
    print("-" * 90)
    print(f"{'1. no_kb':<14} | {s_no['Recall']} ({s_no['TP']}/{n_err}){'':<5} | {s_no['FPR']} ({s_no['FP']}/{n_clean}){'':<4} | {s_no['Precision']:<12} | {s_no['F1']:<8} | {s_no['AvgLat']:<12}")
    print(f"{'2. blind_kb':<14} | {s_blind['Recall']} ({s_blind['TP']}/{n_err}){'':<5} | {s_blind['FPR']} ({s_blind['FP']}/{n_clean}){'':<4} | {s_blind['Precision']:<12} | {s_blind['F1']:<8} | {s_blind['AvgLat']:<12}")
    print(f"{'3. agentic_kb':<14} | {s_agentic['Recall']} ({s_agentic['TP']}/{n_err}){'':<5} | {s_agentic['FPR']} ({s_agentic['FP']}/{n_clean}){'':<4} | {s_agentic['Precision']:<12} | {s_agentic['F1']:<8} | {s_agentic['AvgLat']:<12}")
    print("=" * 90)
    print(f"Agentic Tool Trigger Stats: {triggered_samples}/{len(records)} samples ({trigger_rate:.1f}%) triggered search_kb (Total {tot_tool_calls} queries).")
    print(f"Detailed logs saved at: {out_file}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
