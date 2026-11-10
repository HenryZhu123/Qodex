#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frozen evaluation on Blind Test Set v2 (measured once, no tuning after).

Frozen configuration = the code state committed at 90bed70:
  - symbol rules   : check_deterministic_rules  (option_structure, type_mismatch)
  - physical guards: check_factual_guards       (factual_logical, clean)
  - factual branch : factual_pipeline_v2 (claim extraction + KB verification)
  - other branches : direct single-round prompts, identical to the Dev Set B run
  - clean samples  : evaluated by the typo prompt, identical to the Dev Set B run
  - timeouts       : 180 s, matching the service default
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

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from factual_pipeline_v2 import run_factual_pipeline_v2  # noqa: E402
from run_blind_test_evaluation import (  # noqa: E402
    build_async_client,
    call_direct_llm,
    load_task_prompt,
)


def resolve_api_key() -> str:
    key = os.environ.get("TALKWEB_API_KEY", "")
    if key:
        return key
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
            key, _ = winreg.QueryValueEx(k, "TALKWEB_API_KEY")
    except Exception:
        pass
    return key

REPO_SRC = Path(r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src")
sys.path.insert(0, str(REPO_SRC))
from exam_checker.parsing.factual_guard import check_factual_guards  # noqa: E402
from exam_checker.parsing.rule_checker import check_deterministic_rules  # noqa: E402

DATASET_CSV = ROOT / "blind_test_v2" / "dataset" / "blind_v2_dataset.csv"
OUT_DIR = ROOT / "blind_test_v2" / "runs" / "frozen_eval"

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


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    ap.add_argument("--model", default="gpu-qwen3.8-27b")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    api_key = resolve_api_key()
    if not api_key:
        print("[ERROR] TALKWEB_API_KEY not set.")
        return 1

    rows = list(csv.DictReader(DATASET_CSV.open(encoding="utf-8-sig")))
    print(f"[frozen] Blind Test Set v2: {len(rows)} samples (timeout={args.timeout}s)")

    gold_map: dict[str, dict] = {}
    for line in (ROOT / "blind_test_v2" / "dataset" / "blind_v2_gold.jsonl").open(encoding="utf-8"):
        if line.strip():
            g = json.loads(line)
            gold_map[g["sample_id"]] = g

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "v2_results.jsonl"
    recs: list[dict] = []
    done_ids: set[str] = set()
    if out_file.exists():
        for line in out_file.open(encoding="utf-8"):
            if line.strip():
                d = json.loads(line)
                recs.append(d)
                done_ids.add(d["sample_id"])
    print(f"resume: {len(done_ids)} already done, {len(rows) - len(done_ids)} to go")
    fp = out_file.open("a", encoding="utf-8")

    prompts = {
        k: load_task_prompt(k)
        for k in [
            "typo", "punctuation", "option_structure", "type_mismatch",
            "missing_info", "ambiguity", "unsolvable", "answer_leakage",
        ]
    }

    sem = asyncio.Semaphore(args.concurrency)
    counter = len(done_ids)

    async with build_async_client(args.timeout + 30) as client:
        async def one(row: dict) -> None:
            nonlocal counter
            async with sem:
                sid = row["sample_id"]
                is_clean = row.get("label") == "clean"
                cat = "clean" if is_clean else row["error_type"]
                text = (row.get("full_text") or "").strip()
                reference = row.get("reference", "")
                subject = row.get("subject") or "computer_network"
                gold = gold_map.get(sid, {})

                t0 = time.perf_counter()
                has_err = False
                errors: list[dict] = []
                reason = ""
                stage = ""
                tries = 0

                rule = check_deterministic_rules(text)
                if rule and rule.has_error and (
                    is_clean or cat in ("type_mismatch", "option_structure")
                ):
                    has_err = True
                    errors = [e.model_dump() for e in rule.errors]
                    reason = f"[P0-Rule] {rule.reason}"
                    stage = "p0_rule"
                elif not has_err and (is_clean or cat == "factual_logical"):
                    guard = check_factual_guards(text)
                    if guard and guard.has_error:
                        has_err = True
                        errors = [e.model_dump() for e in guard.errors]
                        reason = f"[P2-Guard] {guard.reason}"
                        stage = "p2_guard"

                if not has_err:
                    try:
                        if cat == "factual_logical":
                            res = await run_factual_pipeline_v2(
                                client=client,
                                base_url=args.base_url,
                                api_key=api_key,
                                model=args.model,
                                full_text=text,
                                reference=reference,
                                subject=subject,
                                timeout=args.timeout,
                            )
                            has_err = res.has_error
                            errors = res.errors
                            reason = res.reason
                            stage = res.stage
                            tries = res.llm_calls
                        else:
                            task = cat if not is_clean else "typo"
                            parsed, _ = await call_direct_llm(
                                client, args.base_url, api_key, args.model,
                                prompts[task], text, reference=reference,
                                timeout=args.timeout,
                            )
                            if parsed:
                                has_err = bool(parsed.get("has_error"))
                                errors = parsed.get("errors") or []
                                reason = parsed.get("reason", "")
                                stage = "direct_llm"
                    except Exception as exc:  # noqa: BLE001
                        reason = f"Exception: {type(exc).__name__}: {exc}"
                        stage = "exception"

                type_hit = span_hit = False
                if not is_clean:
                    exp = EXPECTED_LABELS.get(cat, "")
                    gold_span = ""
                    if gold.get("errors"):
                        gold_span = gold["errors"][0].get("original_text", "")
                    for de in errors:
                        if (de.get("error_type") or "").strip() == exp:
                            type_hit = True
                        dt = (de.get("original_text") or "").strip()
                        if gold_span and dt and (gold_span in dt or dt in gold_span):
                            span_hit = True

                rec = {
                    "sample_id": sid,
                    "category": cat,
                    "is_clean": is_clean,
                    "subject": subject,
                    "has_error": has_err,
                    "type_hit": type_hit,
                    "span_hit": span_hit,
                    "stage": stage,
                    "llm_calls": tries,
                    "reason": reason,
                    "latency_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                }
                recs.append(rec)
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fp.flush()
                counter += 1
                tag = "FP" if (is_clean and has_err) else (
                    "TN" if is_clean else ("TP" if has_err else "FN")
                )
                print(f"[{counter:3d}/{len(rows)}] {sid:<38} {tag} ({stage})", flush=True)

        await asyncio.gather(*(one(r) for r in rows if r["sample_id"] not in done_ids))

    fp.close()

    errs = [r for r in recs if not r["is_clean"]]
    cln = [r for r in recs if r["is_clean"]]
    tp = sum(1 for r in errs if r["has_error"])
    fp_n = sum(1 for r in cln if r["has_error"])
    recall = tp / len(errs) * 100 if errs else 0.0
    fpr = fp_n / len(cln) * 100 if cln else 0.0
    precision = tp / (tp + fp_n) * 100 if (tp + fp_n) else 0.0
    f1 = 2 * precision * recall / (precision + recall) / 100 if (precision + recall) else 0.0

    by_cat = defaultdict(lambda: [0, 0])
    for r in recs:
        by_cat[r["category"]][0] += 1
        if r["has_error"]:
            by_cat[r["category"]][1] += 1

    print("\n" + "=" * 88)
    print("BLIND TEST SET v2 — FROZEN EVALUATION (single run, no tuning)")
    print("=" * 88)
    for c, (n, hit) in sorted(by_cat.items()):
        label = "FPR" if c == "clean" else "Recall"
        print(f"  {c:<18} {hit:>2}/{n:<3} {label} {hit / n * 100:5.1f}%")
    print("-" * 88)
    print(f"  Recall {recall:.2f}% ({tp}/{len(errs)}) | Precision {precision:.2f}% "
          f"| F1 {f1:.4f} | FPR {fpr:.2f}% ({fp_n}/{len(cln)})")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
