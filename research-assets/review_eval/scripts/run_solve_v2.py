#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluate the solve-verify v2 prompt (with condition-suspicion rules).

Runs three conditions and reports BOTH recall and false-positive rate:

  stock      - the original task prompt for that error type
  solve_v1   - solve-then-verify without suspicion rules
  solve_v2   - solve-then-verify WITH condition-suspicion rules

Targets the two types that cannot be found by reading alone.
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
V1 = ROOT / "prompts" / "solve_verify" / "task.txt"
V2 = ROOT / "prompts" / "solve_verify_v2" / "task.txt"
DATASET = ROOT / "dataset"

TARGETS = {
    "factual_logical": ("explicit", "logic_check"),
    "missing_info": ("disabled", "missing_check"),
}
LABEL = {"factual_logical": "事实/逻辑错误", "missing_info": "信息缺失"}


def load_stock(mode: str, task: str) -> str:
    jf = "JSON约束_with_think.txt" if mode == "explicit" else "JSON约束_without_think.txt"
    t = (PROMPT_ROOT / mode / "tasks" / f"{task}.txt").read_text(encoding="utf-8").strip()
    o = (PROMPT_ROOT / mode / jf).read_text(encoding="utf-8").strip()
    return f"{t}\n\n{o}"


def load_solver(path: Path) -> str:
    t = path.read_text(encoding="utf-8").strip()
    o = (PROMPT_ROOT / "explicit" / "JSON约束_with_think.txt").read_text(encoding="utf-8").strip()
    return f"{t}\n\n{o}"


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


async def call(client, base_url, api_key, model, system_prompt, payload):
    user = "[INPUT_PAYLOAD]\n" + json.dumps(payload, ensure_ascii=False)
    try:
        r = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "seed": 42,
                "response_format": {"type": "json_object"},
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=300,
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return parse_json_response(r.json()["choices"][0]["message"]["content"]), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}"


def hit(parsed, error_type):
    if not parsed:
        return False
    errs = parsed.get("errors") or []
    return any((e.get("error_type") or "").strip() == LABEL[error_type] for e in errs)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10, help="error samples per type")
    ap.add_argument("--clean-limit", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    ap.add_argument("--model", default="gpu-qwen3.8-27b")
    ap.add_argument("--out", default=str(ROOT / "runs" / "solve_v2"))
    args = ap.parse_args()

    key = os.environ.get("TALKWEB_API_KEY", "")
    if not key:
        print("TALKWEB_API_KEY not set")
        return 2

    rows = list(csv.DictReader((DATASET / "review_eval_dataset.csv").open(encoding="utf-8-sig")))
    per = defaultdict(int)
    err_rows = []
    for r in rows:
        t = r["error_type"]
        if t in TARGETS and per[t] < args.limit:
            per[t] += 1
            err_rows.append(r)
    clean_rows = [r for r in rows if r["label"] == "clean"][: args.clean_limit]

    stock = {t: load_stock(*TARGETS[t]) for t in TARGETS}
    v1, v2 = load_solver(V1), load_solver(V2)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.concurrency)
    results = []

    async with httpx.AsyncClient() as client:
        async def err_worker(row):
            async with sem:
                t = row["error_type"]
                payload = {"reference": "", "detection_content": row["full_text"]}
                p_stock, _ = await call(client, args.base_url, key, args.model, stock[t], payload)
                p_v1, _ = await call(client, args.base_url, key, args.model, v1, payload)
                hits = kb_retrieval.search(row["full_text"], top_k=3)
                ev = kb_retrieval.format_evidence(hits)
                p_v2, _ = await call(client, args.base_url, key, args.model, v2, {
                    "reference": "以下是该题相关的教材片段，作为判断条件取值的依据：\n" + ev if ev else "",
                    "detection_content": row["full_text"],
                })
                results.append({
                    "sample_id": row["sample_id"], "error_type": t, "kind": "error",
                    "stock": hit(p_stock, t), "solve_v1": hit(p_v1, t), "solve_v2": hit(p_v2, t),
                })

        async def clean_worker(row):
            async with sem:
                payload = {"reference": "", "detection_content": row["full_text"]}
                # A clean question is checked by both tasks; any report is a false positive.
                p_stock, _ = await call(client, args.base_url, key, args.model,
                                        stock["factual_logical"], payload)
                p_stock_m, _ = await call(client, args.base_url, key, args.model,
                                          stock["missing_info"], payload)
                hits = kb_retrieval.search(row["full_text"], top_k=3)
                ev = kb_retrieval.format_evidence(hits)
                p_v2, _ = await call(client, args.base_url, key, args.model, v2, {
                    "reference": "以下是该题相关的教材片段，作为判断条件取值的依据：\n" + ev if ev else "",
                    "detection_content": row["full_text"],
                })
                stock_fp = bool(p_stock and p_stock.get("has_error")) or bool(
                    p_stock_m and p_stock_m.get("has_error"))
                results.append({
                    "sample_id": row["sample_id"], "error_type": "none", "kind": "clean",
                    "stock": stock_fp,
                    "solve_v2": bool(p_v2 and p_v2.get("has_error")),
                })

        await asyncio.gather(*(err_worker(r) for r in err_rows),
                             *(clean_worker(r) for r in clean_rows))

    (out_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")

    # ---- report ----
    print("== 检出率 (错误题) ==")
    print(f"{'error_type':<18}{'n':>3}{'stock':>8}{'solve_v1':>10}{'solve_v2':>10}")
    print("-" * 50)
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in results:
        if r["kind"] != "error":
            continue
        for c in ("stock", "solve_v1", "solve_v2"):
            agg[r["error_type"]][c][0] += int(r[c])
            if r[c] is not None:
                agg[r["error_type"]][c][1] += 1
    for t in TARGETS:
        n = agg[t]["stock"][1] or 1
        print(f"{t:<18}{n:>3}{agg[t]['stock'][0]/n:>7.0%}"
              f"{agg[t]['solve_v1'][0]/n:>10.0%}{agg[t]['solve_v2'][0]/n:>10.0%}")

    print()
    print("== 误报率 (干净题) ==")
    clean = [r for r in results if r["kind"] == "clean"]
    n = max(len(clean), 1)
    s_fp = sum(int(r["stock"]) for r in clean)
    v_fp = sum(int(r.get("solve_v2", False)) for r in clean)
    print(f"n={len(clean)}  stock={s_fp}/{len(clean)} ({s_fp/n:.0%})"
          f"  solve_v2={v_fp}/{len(clean)} ({v_fp/n:.0%})")
    print()
    print("results:", out_dir / "results.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
