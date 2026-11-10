#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small-scale check: does solve-then-verify beat direct inspection?

Targets the two error types that cannot be found by reading alone:
  factual_logical  (a condition value was altered)
  missing_info     (a necessary condition was removed)

Three conditions per sample:
  direct   - stock task prompt (read and inspect)
  solve    - solve-then-verify prompt, no evidence
  solve+kb - solve-then-verify prompt with textbook evidence
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import httpx

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import kb_retrieval  # noqa: E402

ROOT = SCRIPTS.parent
PROMPT_ROOT = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\prompts\reviewer-prompt\qwen38_27b"
)
SOLVE_PROMPT = ROOT / "prompts" / "solve_verify" / "task.txt"
DATASET = ROOT / "dataset"

TARGETS = {
    "factual_logical": ("explicit", "logic_check"),
    "missing_info": ("disabled", "missing_check"),
}

ERROR_TYPE_LABEL = {
    "factual_logical": "事实/逻辑错误",
    "missing_info": "信息缺失",
}


def load_stock(mode: str, task: str) -> str:
    json_file = "JSON约束_with_think.txt" if mode == "explicit" else "JSON约束_without_think.txt"
    task_text = (PROMPT_ROOT / mode / "tasks" / f"{task}.txt").read_text(encoding="utf-8").strip()
    out_text = (PROMPT_ROOT / mode / json_file).read_text(encoding="utf-8").strip()
    return f"{task_text}\n\n{out_text}"


def load_solve() -> str:
    task_text = SOLVE_PROMPT.read_text(encoding="utf-8").strip()
    out_text = (PROMPT_ROOT / "explicit" / "JSON约束_with_think.txt").read_text(encoding="utf-8").strip()
    return f"{task_text}\n\n{out_text}"


def parse_json_response(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
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
            timeout=300,
        )
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
        return parse_json_response(resp.json()["choices"][0]["message"]["content"]), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def evaluate(parsed: dict | None, error_type: str, gold: dict) -> tuple[bool, bool]:
    """Return (type_hit, span_hit)."""
    if not parsed:
        return False, False
    errs = parsed.get("errors") or []
    label = ERROR_TYPE_LABEL[error_type]
    type_hit = any((e.get("error_type") or "").strip() == label for e in errs)
    anchor = (gold["errors"][0].get("anchor_text") or "").strip()
    span_hit = False
    if anchor:
        for e in errs:
            a = (e.get("anchor_text") or "").strip()
            if a and (a in anchor or anchor in a):
                span_hit = True
                break
    return type_hit, span_hit


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    ap.add_argument("--model", default="gpu-qwen3.8-27b")
    ap.add_argument("--out", default=str(ROOT / "runs" / "solve_verify"))
    args = ap.parse_args()

    api_key = os.environ.get("TALKWEB_API_KEY", "")
    if not api_key:
        print("TALKWEB_API_KEY not set")
        return 2

    rows = list(csv.DictReader((DATASET / "review_eval_dataset.csv").open(encoding="utf-8-sig")))
    gold = {g["sample_id"]: g
            for g in (json.loads(line) for line in
                      (DATASET / "review_eval_gold.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip())}

    per_type = defaultdict(int)
    picked = []
    for r in rows:
        t = r["error_type"]
        if t in TARGETS and per_type[t] < args.limit:
            per_type[t] += 1
            picked.append(r)

    stock = {t: load_stock(*TARGETS[t]) for t in TARGETS}
    solve_prompt = load_solve()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(args.concurrency)
    results = []

    async with httpx.AsyncClient() as client:
        async def worker(row: dict) -> None:
            async with sem:
                t = row["error_type"]
                g = gold[row["sample_id"]]
                base_payload = {"reference": "", "detection_content": row["full_text"]}

                p_direct, e_direct = await call(client, args.base_url, api_key, args.model,
                                                stock[t], base_payload)
                p_solve, e_solve = await call(client, args.base_url, api_key, args.model,
                                              solve_prompt, base_payload)

                hits = kb_retrieval.search(row["full_text"], top_k=3)
                evidence = kb_retrieval.format_evidence(hits)
                p_solve_kb, e_solve_kb = await call(
                    client, args.base_url, api_key, args.model, solve_prompt,
                    {
                        "reference": "以下是与该题相关的教材片段，作为判断条件取值的依据：\n" + evidence
                        if evidence else "",
                        "detection_content": row["full_text"],
                    },
                )

                results.append({
                    "sample_id": row["sample_id"],
                    "error_type": t,
                    "evidence_count": len(hits),
                    "direct": {"type_hit": evaluate(p_direct, t, g)[0],
                               "span_hit": evaluate(p_direct, t, g)[1], "error": e_direct},
                    "solve": {"type_hit": evaluate(p_solve, t, g)[0],
                              "span_hit": evaluate(p_solve, t, g)[1], "error": e_solve},
                    "solve_kb": {"type_hit": evaluate(p_solve_kb, t, g)[0],
                                 "span_hit": evaluate(p_solve_kb, t, g)[1], "error": e_solve_kb},
                    "solve_think": (p_solve or {}).get("think", "")[:1500],
                })

        await asyncio.gather(*(worker(r) for r in picked))

    path = out_dir / "results.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n",
                    encoding="utf-8")

    agg = defaultdict(lambda: defaultdict(lambda: {"n": 0, "type": 0, "span": 0}))
    for r in results:
        for cond in ("direct", "solve", "solve_kb"):
            a = agg[r["error_type"]][cond]
            a["n"] += 1
            a["type"] += int(r[cond]["type_hit"])
            a["span"] += int(r[cond]["span_hit"])

    print(f"{'error_type':<18}{'cond':<10}{'n':>3}{'检出':>8}{'定位':>8}")
    print("-" * 48)
    for t in TARGETS:
        for cond in ("direct", "solve", "solve_kb"):
            a = agg[t][cond]
            n = max(a["n"], 1)
            print(f"{t:<18}{cond:<10}{a['n']:>3}{a['type']/n:>7.0%}{a['span']/n:>8.0%}")
        print()

    print("results:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
