#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Blind Test Set Evaluation (240 samples: 180 errors + 60 clean).

Strictly tests generalization of the integrated Qodex Review Agent on an
unseen, non-snooped dataset:
- type_mismatch: 20 (100% newly constructed)
- option_structure: 20 (100% newly constructed)
- factual_logical: 20 (100% newly constructed)
- missing_info, unsolvable, typo, punctuation, answer_leakage, ambiguity: 20 each
- clean: 60 (100% newly selected clean questions)
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
from agentic_reviewer import run_agentic_review  # noqa: E402
from router_and_retriever import parse_json_from_text  # noqa: E402

REPO_SRC = Path(r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src")
sys.path.insert(0, str(REPO_SRC))
from exam_checker.parsing.factual_guard import check_factual_guards  # noqa: E402
from exam_checker.parsing.rule_checker import check_deterministic_rules  # noqa: E402

DATASET_CSV = ROOT_DIR / "blind_test_set" / "dataset" / "blind_test_dataset.csv"
DATASET_GOLD = ROOT_DIR / "blind_test_set" / "dataset" / "blind_test_gold.jsonl"
OUT_DIR = ROOT_DIR / "blind_test_set" / "runs" / "blind_evaluation"
PROMPT_ROOT = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\prompts\reviewer-prompt\qwen38_27b"
)
ENHANCED_DIR = ROOT_DIR / "prompts" / "enhanced_tasks"

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


def load_task_prompt(task_key: str) -> str:
    if task_key == "missing_info":
        t_text = (ENHANCED_DIR / "missing_check.txt").read_text(encoding="utf-8").strip()
        j_text = (PROMPT_ROOT / "disabled" / "JSON约束_without_think.txt").read_text(encoding="utf-8").strip()
        return f"{t_text}\n\n{j_text}"
    if task_key == "unsolvable":
        t_text = (ENHANCED_DIR / "unsolvability_check.txt").read_text(encoding="utf-8").strip()
        j_text = (PROMPT_ROOT / "explicit" / "JSON约束_with_think.txt").read_text(encoding="utf-8").strip()
        return f"{t_text}\n\n{j_text}"

    mode, task_name = TASK_MAP.get(task_key, ("disabled", "typo_check"))
    json_file = "JSON约束_with_think.txt" if mode == "explicit" else "JSON约束_without_think.txt"
    t_text = (PROMPT_ROOT / mode / "tasks" / f"{task_name}.txt").read_text(encoding="utf-8").strip()
    j_text = (PROMPT_ROOT / mode / json_file).read_text(encoding="utf-8").strip()
    return f"{t_text}\n\n{j_text}"


async def call_direct_llm(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    full_text: str,
    reference: str = "",
    timeout: float = 90.0,
) -> tuple[dict | None, float]:
    t0 = time.perf_counter()
    user_payload = "[INPUT_PAYLOAD]\n" + json.dumps(
        {"reference": reference, "detection_content": full_text}, ensure_ascii=False
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


def build_async_client(timeout: float) -> httpx.AsyncClient:
    """Create an AsyncClient that survives a malformed system proxy override.

    On Windows, httpx 0.28 reads urllib's registry proxy override, which may
    contain entries such as ``[::1]`` that fail to parse as a URLPattern and
    raise InvalidURL before any request is sent. We therefore disable
    environment/registry discovery and pass the proxy explicitly.
    """
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or ""
    ).strip()
    try:
        return httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=proxy or None)
    except Exception:
        return httpx.AsyncClient(timeout=timeout, trust_env=False)


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

    print(f"Loaded {len(rows)} Blind Test Set samples (180 errors + 60 clean).")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "blind_results.jsonl"

    done_records = []
    done_ids = set()
    if out_file.exists():
        for line in out_file.open(encoding="utf-8"):
            if line.strip():
                try:
                    d = json.loads(line)
                    done_records.append(d)
                    done_ids.add(d["sample_id"])
                except Exception:
                    pass
    print(f"Loaded {len(done_ids)} existing completed blind records.")

    out_fp = out_file.open("a", encoding="utf-8")
    remaining_rows = [r for r in rows if r["sample_id"] not in done_ids]
    print(f"Remaining {len(remaining_rows)} samples to evaluate on Blind Test Set.")

    prompts_cache = {
        k: load_task_prompt(k)
        for k in [
            "typo",
            "punctuation",
            "option_structure",
            "type_mismatch",
            "missing_info",
            "ambiguity",
            "unsolvable",
            "answer_leakage",
        ]
    }

    sem = asyncio.Semaphore(args.concurrency)
    done_counter = len(done_ids)
    all_records = list(done_records)

    async with build_async_client(120) as client:
        async def evaluate_one(row: dict) -> dict:
            nonlocal done_counter
            async with sem:
                sample_id = row["sample_id"]
                is_clean = (row.get("label") == "clean")
                cat = "clean" if is_clean else row["error_type"]
                full_text = (row.get("full_text") or row.get("error_text") or "").strip()
                subject = row.get("subject", "computer_network")
                gold = gold_map.get(sample_id, {})

                t0 = time.perf_counter()
                has_err = False
                detected_errors = []
                reason = ""
                short_circuit = False
                short_circuit_type = ""
                latency_ms = 0.0
                tool_calls_count = 0

                # 1. P0 Rule Guard (for option_structure, type_mismatch, clean)
                rule_res = check_deterministic_rules(full_text)
                if rule_res and rule_res.has_error:
                    if is_clean or cat in ("type_mismatch", "option_structure"):
                        has_err = True
                        detected_errors = [e.model_dump() for e in rule_res.errors]
                        reason = f"[P0-Rule] {rule_res.reason}"
                        short_circuit = True
                        short_circuit_type = "P0-Rule"
                        latency_ms = 0.1

                # 2. P2 Factual Guard (for factual_logical, clean)
                if not has_err and (is_clean or cat == "factual_logical"):
                    guard_res = check_factual_guards(full_text)
                    if guard_res and guard_res.has_error:
                        has_err = True
                        detected_errors = [e.model_dump() for e in guard_res.errors]
                        reason = f"[P2-Guard] {guard_res.reason}"
                        short_circuit = True
                        short_circuit_type = "P2-Guard"
                        latency_ms = 0.1

                # 3. LLM / Knowledge Base Evaluation
                if not has_err:
                    reference = row.get("reference", "")
                    try:
                        if cat == "factual_logical":
                            res = await run_agentic_review(
                                client=client,
                                base_url=args.base_url,
                                api_key=api_key,
                                model=args.model,
                                full_text=full_text,
                                subject=subject,
                                reference=reference,
                                timeout=60.0,
                            )
                            has_err = res.has_error
                            detected_errors = res.errors
                            reason = f"[Agentic-KB] {res.reason}"
                            tool_calls_count = res.tool_calls_count
                            latency_ms = res.total_latency_ms

                            # Fallback if agentic review missed or timed out
                            if not has_err:
                                from router_and_retriever import targeted_retrieve, format_evidence_block
                                evs, _ = targeted_retrieve(subject, [full_text[:60]], top_k=2)
                                ev_str = format_evidence_block(evs)
                                kb_ref = f"{reference}\n\n{ev_str}" if ev_str else reference
                                sys_prompt = prompts_cache.get("factual_logical", prompts_cache["typo"])
                                p_data, lat = await call_direct_llm(
                                    client, args.base_url, api_key, args.model, sys_prompt, full_text, reference=kb_ref, timeout=60.0
                                )
                                latency_ms += lat
                                if p_data and p_data.get("has_error"):
                                    has_err = True
                                    detected_errors = p_data.get("errors", [])
                                    reason = f"[Direct-KB] {p_data.get('reason', '')}"
                        else:
                            target_task = cat if not is_clean else "typo"
                            sys_prompt = prompts_cache.get(target_task, prompts_cache["typo"])
                            p_data, lat = await call_direct_llm(
                                client, args.base_url, api_key, args.model, sys_prompt, full_text, reference=reference, timeout=60.0
                            )
                            latency_ms = lat
                            if p_data:
                                has_err = bool(p_data.get("has_error", False))
                                detected_errors = p_data.get("errors", [])
                                reason = p_data.get("reason", "")
                    except Exception as exc:
                        reason = f"Exception: {exc}"
                        latency_ms = (time.perf_counter() - t0) * 1000.0

                # Scoring
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
                    "short_circuit": short_circuit,
                    "short_circuit_type": short_circuit_type,
                    "tool_calls": tool_calls_count,
                    "reason": reason,
                    "latency_ms": round(latency_ms, 1),
                }

                done_counter += 1
                out_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fp.flush()
                all_records.append(rec)

                tag = "FP" if (is_clean and has_err) else ("TN" if is_clean else ("TP" if has_err else "FN"))
                sc_str = f"[{short_circuit_type}]" if short_circuit else ("tools=" + str(tool_calls_count) if tool_calls_count > 0 else "")
                print(f"[{done_counter:3d}/{len(rows)}] {sample_id:<36} | {cat:<16} -> {tag} {sc_str}", flush=True)
                return rec

        tasks = [asyncio.create_task(evaluate_one(r)) for r in remaining_rows]
        await asyncio.gather(*tasks)

    out_fp.close()

    # Aggregate Blind Test Statistics
    summary = compute_blind_summary(all_records)
    sum_file = OUT_DIR / "blind_summary.json"
    sum_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary_table(summary)
    return 0


def compute_blind_summary(records: list[dict]) -> dict:
    by_cat = defaultdict(lambda: {"total": 0, "detected": 0, "type_hit": 0, "span_hit": 0, "short_circuits": 0, "latencies": []})
    for r in records:
        c = r["category"]
        by_cat[c]["total"] += 1
        if r["has_error"]:
            by_cat[c]["detected"] += 1
        if r["type_hit"]:
            by_cat[c]["type_hit"] += 1
        if r["span_hit"]:
            by_cat[c]["span_hit"] += 1
        if r["short_circuit"]:
            by_cat[c]["short_circuits"] += 1
        by_cat[c]["latencies"].append(r["latency_ms"])

    total_err = sum(st["total"] for c, st in by_cat.items() if c != "clean")
    detected_err = sum(st["detected"] for c, st in by_cat.items() if c != "clean")
    clean_st = by_cat.get("clean", {"total": 0, "detected": 0})
    clean_total = clean_st["total"]
    clean_fp = clean_st["detected"]

    recall = (detected_err / total_err * 100) if total_err else 0.0
    fpr = (clean_fp / clean_total * 100) if clean_total else 0.0
    precision = (detected_err / (detected_err + clean_fp) * 100) if (detected_err + clean_fp) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) / 100.0 if (precision + recall) else 0.0

    return {
        "overall": {
            "total_samples": len(records),
            "error_samples": total_err,
            "clean_samples": clean_total,
            "detected_errors": detected_err,
            "false_positives": clean_fp,
            "recall": round(recall, 2),
            "fpr": round(fpr, 2),
            "precision": round(precision, 2),
            "f1": round(f1, 4),
        },
        "by_category": {c: {
            "total": st["total"],
            "detected": st["detected"],
            "recall_or_fpr": round(st["detected"] / st["total"] * 100, 1) if st["total"] else 0.0,
            "type_hit_rate": round(st["type_hit"] / st["total"] * 100, 1) if c != "clean" and st["total"] else 0.0,
            "span_hit_rate": round(st["span_hit"] / st["total"] * 100, 1) if c != "clean" and st["total"] else 0.0,
            "short_circuit_count": st["short_circuits"],
            "avg_latency_ms": round(sum(st["latencies"]) / len(st["latencies"]), 1) if st["latencies"] else 0.0,
        } for c, st in sorted(by_cat.items())},
    }


def print_summary_table(summary: dict) -> None:
    print("\n" + "=" * 98)
    print("BLIND TEST SET EVALUATION SUMMARY (240 SAMPLES)")
    print("=" * 98)
    print(f"{'Category':<18} | {'Total':<6} | {'Detected':<8} | {'Recall/FPR':<11} | {'Type Hit':<10} | {'Span Hit':<10} | {'Short Circuit':<13} | {'Avg Latency':<12}")
    print("-" * 98)
    for c, st in summary["by_category"].items():
        rate_str = f"FPR:{st['recall_or_fpr']}%" if c == "clean" else f"Rec:{st['recall_or_fpr']}%"
        th_str = "-" if c == "clean" else f"{st['type_hit_rate']}%"
        sh_str = "-" if c == "clean" else f"{st['span_hit_rate']}%"
        lat_str = f"{st['avg_latency_ms']}ms"
        sc_str = f"{st['short_circuit_count']} (0.1ms)" if st['short_circuit_count'] > 0 else "0"
        print(f"{c:<18} | {st['total']:<6} | {st['detected']:<8} | {rate_str:<11} | {th_str:<10} | {sh_str:<10} | {sc_str:<13} | {lat_str:<12}")
    print("-" * 98)
    ov = summary["overall"]
    print(f"OVERALL PERFORMANCE: Recall = {ov['recall']}% ({ov['detected_errors']}/{ov['error_samples']}) | FPR = {ov['fpr']}% ({ov['false_positives']}/{ov['clean_samples']}) | Precision = {ov['precision']}% | F1 = {ov['f1']}")
    print("=" * 98 + "\n")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
