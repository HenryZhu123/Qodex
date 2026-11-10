#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the review agent against the evaluation dataset and score it.

Uses the repository's reviewer prompts (per task) plus the JSON constraint file,
calls an OpenAI-compatible endpoint, and records raw responses per sample.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import time
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
PROMPT_ROOT = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\prompts\reviewer-prompt\qwen38_27b"
)
DATASET = ROOT / "dataset"

# error_type -> (prompt dir, task id)
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

# The model answers with the Chinese label from EXPECTED_ERROR_TYPES.
ERROR_TYPE_LABEL = {
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


def load_prompt(mode: str, task: str) -> str:
    json_file = "JSON约束_with_think.txt" if mode == "explicit" else "JSON约束_without_think.txt"
    task_text = (PROMPT_ROOT / mode / "tasks" / f"{task}.txt").read_text(encoding="utf-8").strip()
    out_text = (PROMPT_ROOT / mode / json_file).read_text(encoding="utf-8").strip()
    return f"{task_text}\n\n{out_text}"


def parse_json_response(text: str) -> dict | None:
    """Extract the first JSON object from a model response."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


async def review_one(client: httpx.AsyncClient, base_url: str, api_key: str, model: str,
                     system_prompt: str, payload: dict) -> tuple[dict | None, str, int]:
    # Match exam-checker's specialist reviewer exactly: the payload is prefixed
    # with an [INPUT_PAYLOAD] marker, JSON mode is on, thinking is disabled.
    user_prompt = "[INPUT_PAYLOAD]\n" + json.dumps(payload, ensure_ascii=False)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    started = time.perf_counter()
    try:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0,
                "seed": 42,
                "response_format": {"type": "json_object"},
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=180,
        )
        elapsed = round((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}", elapsed
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return parse_json_response(content), content, elapsed
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}", round((time.perf_counter() - started) * 1000)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=18, help="samples per error type")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    ap.add_argument("--model", default="qwen3.8-27b")
    ap.add_argument("--out", default=str(ROOT / "runs" / "smoke"))
    args = ap.parse_args()

    api_key = os.environ.get("TALKWEB_API_KEY", "")
    if not api_key:
        print("TALKWEB_API_KEY not set")
        return 2

    rows = list(csv.DictReader((DATASET / "review_eval_dataset.csv").open(encoding="utf-8-sig")))
    gold = {g["sample_id"]: g
            for g in (json.loads(l) for l in (DATASET / "review_eval_gold.jsonl")
                      .read_text(encoding="utf-8").splitlines() if l.strip())}

    picked = []
    per_type = defaultdict(int)
    for r in rows:
        t = r["error_type"]
        if per_type[t] < args.limit:
            per_type[t] += 1
            picked.append(r)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    prompts = {t: load_prompt(mode, task) for t, (mode, task) in TASK_MAP.items()}

    sem = asyncio.Semaphore(args.concurrency)
    results = []

    async with httpx.AsyncClient() as client:
        async def worker(row: dict) -> None:
            async with sem:
                payload = {
                    "reference": "",
                    "detection_content": row["full_text"],
                }
                parsed, raw, ms = await review_one(
                    client, args.base_url, api_key, args.model,
                    prompts[row["error_type"]], payload,
                )
                results.append({
                    "sample_id": row["sample_id"],
                    "error_type": row["error_type"],
                    "latency_ms": ms,
                    "parsed": parsed,
                    "raw": raw[:4000],
                })

        await asyncio.gather(*(worker(r) for r in picked))

    raw_path = out_dir / "raw_responses.jsonl"
    raw_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")

    # scoring
    stats = defaultdict(lambda: {"n": 0, "fail": 0, "has_error": 0, "type_hit": 0, "span_hit": 0})
    details = []
    for r in results:
        s = stats[r["error_type"]]
        s["n"] += 1
        if r["parsed"] is None:
            s["fail"] += 1
            details.append({**r, "verdict": "parse_fail"})
            continue
        has_error = bool(r["parsed"].get("has_error"))
        if has_error:
            s["has_error"] += 1
        g = gold[r["sample_id"]]["errors"][0]
        errs = r["parsed"].get("errors") or []
        expected_label = ERROR_TYPE_LABEL[r["error_type"]]
        type_hit = any(
            (e.get("error_type") or "").strip() == expected_label for e in errs
        ) if errs else False
        span_hit = any(
            (g["anchor_text"] and g["anchor_text"] in (e.get("anchor_text") or ""))
            or (e.get("anchor_text") and e.get("anchor_text") in g["anchor_text"])
            for e in errs
        ) if errs and g["anchor_text"] else False
        if type_hit:
            s["type_hit"] += 1
        if span_hit:
            s["span_hit"] += 1
        details.append({**r, "verdict": "ok", "has_error": has_error,
                        "type_hit": type_hit, "span_hit": span_hit})

    (out_dir / "details.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in details) + "\n", encoding="utf-8")

    print(f"{'error_type':<18}{'n':>4}{'parse_fail':>11}{'has_error':>11}{'type_hit':>10}{'span_hit':>10}")
    print("-" * 66)
    for t in TASK_MAP:
        s = stats[t]
        n = max(s["n"], 1)
        print(f"{t:<18}{s['n']:>4}{s['fail']:>11}"
              f"{s['has_error']:>6} ({s['has_error']/n:>3.0%})"
              f"{s['type_hit']:>5} ({s['type_hit']/n:>3.0%})"
              f"{s['span_hit']:>5} ({s['span_hit']/n:>3.0%})")
    print()
    print("raw   :", raw_path)
    print("detail:", out_dir / "details.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
