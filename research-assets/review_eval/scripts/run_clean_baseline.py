#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measure the false-positive rate on clean (unmodified) questions.

Every task prompt is run against each clean question. A report of any error is
a false positive. The per-task breakdown shows which detectors over-trigger.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import httpx

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
PROMPT_ROOT = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\prompts\reviewer-prompt\qwen38_27b"
)
DATASET = ROOT / "dataset"

TASK_MAP = {
    "typo": ("disabled", "typo_check"),
    "punctuation": ("explicit", "punctuation_check"),
    "option_structure": ("disabled", "options_check"),
    "type_mismatch": ("disabled", "mismatch_check"),
    "missing_info": ("disabled", "missing_check"),
    "ambiguity": ("disabled", "ambiguity_check"),
    "unsolvable": ("explicit", "unsolvability_check"),
    "answer_leakage": ("explicit", "answer_leak_check"),
    "factual_logical": ("explicit", "logic_check"),
}


def load_prompt(mode: str, task: str) -> str:
    json_file = "JSON约束_with_think.txt" if mode == "explicit" else "JSON约束_without_think.txt"
    task_text = (PROMPT_ROOT / mode / "tasks" / f"{task}.txt").read_text(encoding="utf-8").strip()
    out_text = (PROMPT_ROOT / mode / json_file).read_text(encoding="utf-8").strip()
    return f"{task_text}\n\n{out_text}"


def parse_json_response(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


async def call(client: httpx.AsyncClient, base_url: str, api_key: str, model: str,
               system_prompt: str, payload: dict) -> tuple[dict | None, str]:
    user_prompt = "[INPUT_PAYLOAD]\n" + json.dumps(payload, ensure_ascii=False)
    try:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0,
                "seed": 42,
                "response_format": {"type": "json_object"},
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=180,
        )
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
        return parse_json_response(resp.json()["choices"][0]["message"]["content"]), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = all clean questions")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    ap.add_argument("--model", default="gpu-qwen3.8-27b")
    ap.add_argument("--out", default=str(ROOT / "runs" / "clean_baseline"))
    args = ap.parse_args()

    api_key = os.environ.get("TALKWEB_API_KEY", "")
    if not api_key:
        print("TALKWEB_API_KEY not set")
        return 2

    rows = [r for r in csv.DictReader(
        (DATASET / "review_eval_dataset.csv").open(encoding="utf-8-sig")) if r["label"] == "clean"]
    if args.limit:
        rows = rows[: args.limit]
    rows = rows[:60]  # 60 questions x 9 tasks keeps the run bounded

    prompts = {t: load_prompt(*TASK_MAP[t]) for t in TASK_MAP}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(args.concurrency)
    results = []

    async with httpx.AsyncClient() as client:
        async def worker(row: dict) -> None:
            async with sem:
                hits = []
                for t, sp in prompts.items():
                    parsed, err = await call(client, args.base_url, api_key, args.model, sp,
                                             {"reference": "", "detection_content": row["full_text"]})
                    if parsed and parsed.get("has_error"):
                        hits.append({"task": t,
                                     "errors": [e.get("error_type") for e in (parsed.get("errors") or [])]})
                    results.append({
                        "sample_id": row["sample_id"],
                        "task": t,
                        "has_error": bool(parsed.get("has_error")) if parsed else None,
                        "parsed": parsed,
                        "error": err,
                    })

        await asyncio.gather(*(worker(r) for r in rows))

    (out_dir / "raw_responses.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")

    stats = defaultdict(lambda: {"n": 0, "fp": 0, "fail": 0})
    for r in results:
        s = stats[r["task"]]
        s["n"] += 1
        if r["has_error"] is None:
            s["fail"] += 1
        elif r["has_error"]:
            s["fp"] += 1

    print(f"{'task':<20}{'n':>4}{'误报':>7}{'误报率':>8}{'调用失败':>9}")
    print("-" * 50)
    total_n = total_fp = 0
    for t in TASK_MAP:
        s = stats[t]
        n = max(s["n"], 1)
        print(f"{t:<20}{s['n']:>4}{s['fp']:>7}{s['fp']/n:>8.0%}{s['fail']:>9}")
        total_n += s["n"]
        total_fp += s["fp"]
    print("-" * 50)
    print(f"{'OVERALL':<20}{total_n:>4}{total_fp:>7}{total_fp/max(total_n,1):>8.0%}")

    # any-error-at-all rate (a question flagged by at least one task)
    flagged = defaultdict(bool)
    for r in results:
        if r["has_error"]:
            flagged[r["sample_id"]] = True
    print(f"\nquestions flagged by >=1 task: {sum(flagged.values())}/{len(rows)}"
          f" ({sum(flagged.values())/max(len(rows),1):.0%})")
    print("raw:", out_dir / "raw_responses.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
