#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A/B test for the factual/logical review task on the Blind Test Set.

Mode `baseline`: existing multi-turn agentic reviewer (tool calling), timeout 180s.
Mode `v2`:       stateless claim-extraction + textbook verification pipeline.

Both modes are evaluated on all 20 factual_logical error samples AND all 60
clean samples, so recall and false-positive rate are measured on identical
inputs for the same mode.
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

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from agentic_reviewer import run_agentic_review  # noqa: E402
from factual_pipeline_v2 import run_factual_pipeline_v2  # noqa: E402

DATASET_CSV = ROOT_DIR / "blind_test_set" / "dataset" / "blind_test_dataset.csv"
OUT_DIR = ROOT_DIR / "blind_test_set" / "runs" / "factual_ab"
PROMPT_ROOT = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\prompts\reviewer-prompt\qwen38_27b"
)


def build_client(timeout: float):
    import httpx

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


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "v2"], required=True)
    ap.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    ap.add_argument("--model", default="gpu-qwen3.8-27b")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--out", default="")
    ap.add_argument(
        "--subset",
        choices=["all", "factual", "clean"],
        default="all",
        help="restrict evaluation to one subset (default: all)",
    )
    args = ap.parse_args()

    api_key = resolve_api_key()
    if not api_key:
        print("[ERROR] TALKWEB_API_KEY not set.")
        return 1

    rows = list(csv.DictReader(DATASET_CSV.open(encoding="utf-8-sig")))
    factual = [r for r in rows if r["error_type"] == "factual_logical"]
    clean = [r for r in rows if r.get("label") == "clean"]
    if args.subset == "factual":
        targets = factual
    elif args.subset == "clean":
        targets = clean
    else:
        targets = factual + clean
    print(
        f"[{args.mode}] evaluating {len(factual)} factual_logical + {len(clean)} clean "
        f"= {len(targets)} samples (timeout={args.timeout}s)"
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = Path(args.out) if args.out else OUT_DIR / f"{args.mode}_results.jsonl"
    out_fp = out_file.open("w", encoding="utf-8")

    sem = asyncio.Semaphore(args.concurrency)
    records: list[dict] = []
    done = 0

    async with build_client(args.timeout + 30) as client:
        async def one(row: dict) -> None:
            nonlocal done
            async with sem:
                sid = row["sample_id"]
                is_clean = row.get("label") == "clean"
                cat = "clean" if is_clean else row["error_type"]
                text = (row.get("full_text") or "").strip()
                reference = row.get("reference", "")
                subject = row.get("subject", "computer_network")

                t0 = time.perf_counter()
                rec: dict = {
                    "sample_id": sid,
                    "category": cat,
                    "is_clean": is_clean,
                    "subject": subject,
                    "has_error": False,
                    "errors": [],
                    "reason": "",
                    "stage": "",
                    "llm_calls": 0,
                }
                try:
                    if args.mode == "baseline":
                        res = await run_agentic_review(
                            client=client,
                            base_url=args.base_url,
                            api_key=api_key,
                            model=args.model,
                            full_text=text,
                            subject=subject,
                            reference=reference,
                            timeout=args.timeout,
                        )
                        rec.update(
                            has_error=res.has_error,
                            errors=res.errors,
                            reason=res.reason,
                            stage="agentic_tool_call",
                            llm_calls=res.tool_calls_count,
                            error_msg=res.error_msg,
                        )
                    else:
                        res2 = await run_factual_pipeline_v2(
                            client=client,
                            base_url=args.base_url,
                            api_key=api_key,
                            model=args.model,
                            full_text=text,
                            reference=reference,
                            subject=subject,
                            timeout=args.timeout,
                        )
                        rec.update(
                            has_error=res2.has_error,
                            errors=res2.errors,
                            reason=res2.reason,
                            stage=res2.stage,
                            llm_calls=res2.llm_calls,
                            claims=res2.claims,
                        )
                except Exception as exc:  # noqa: BLE001
                    rec["reason"] = f"Exception: {type(exc).__name__}: {exc}"

                rec["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
                records.append(rec)

                done += 1
                tag = "FP" if (is_clean and rec["has_error"]) else (
                    "TN" if is_clean else ("TP" if rec["has_error"] else "FN")
                )
                out_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fp.flush()
                print(
                    f"[{done:2d}/{len(targets)}] {sid:<40} {tag} "
                    f"({rec['stage']}, {rec['latency_ms'] / 1000:.1f}s)",
                    flush=True,
                )

        await asyncio.gather(*(one(r) for r in targets))

    out_fp.close()

    fact = [r for r in records if not r["is_clean"]]
    cln = [r for r in records if r["is_clean"]]
    tp = sum(1 for r in fact if r["has_error"])
    fp = sum(1 for r in cln if r["has_error"])
    recall = tp / len(fact) * 100 if fact else 0.0
    fpr = fp / len(cln) * 100 if cln else 0.0
    precision = tp / (tp + fp) * 100 if (tp + fp) else 0.0
    lat_fact = sum(r["latency_ms"] for r in fact) / len(fact) / 1000 if fact else 0.0
    lat_cln = sum(r["latency_ms"] for r in cln) / len(cln) / 1000 if cln else 0.0

    print("\n" + "=" * 74)
    print(f"FACTUAL A/B RESULT — mode={args.mode} (timeout={args.timeout}s)")
    print("=" * 74)
    print(f"Recall on 20 factual_logical : {tp}/20 = {recall:.1f}%")
    print(f"False positive on 60 clean   : {fp}/60 = {fpr:.1f}%")
    print(f"Component precision          : {precision:.1f}%")
    print(f"Avg latency  (factual)       : {lat_fact:.1f}s")
    print(f"Avg latency  (clean)         : {lat_cln:.1f}s")
    print(f"Results: {out_file}")
    print("=" * 74 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
