#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ablation: review the same questions with and without knowledge-base evidence.

Two runs share identical prompts, model, seed and samples. The only difference
is whether retrieved textbook evidence is appended to the payload.

The knowledge-base variant passes evidence inside `reference`, which the task
prompts explicitly allow ("reference: 参考信息，仅用于辅助理解题意").
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
KB_PROMPT_ROOT = ROOT / "prompts" / "kb_aware"
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


def load_prompt(mode: str, task: str, root: Path | None = None) -> str:
    base = root or PROMPT_ROOT
    json_file = "JSON约束_with_think.txt" if mode == "explicit" else "JSON约束_without_think.txt"
    task_text = (base / mode / "tasks" / f"{task}.txt").read_text(encoding="utf-8").strip()
    out_text = (base / mode / json_file).read_text(encoding="utf-8").strip()
    return f"{task_text}\n\n{out_text}"


def parse_json_response(text: str) -> dict | None:
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


def score(parsed: dict | None, error_type: str, gold: dict) -> tuple[bool, bool, bool]:
    """Return (has_error, type_hit, span_hit)."""
    if not parsed:
        return False, False, False
    has_error = bool(parsed.get("has_error"))
    errs = parsed.get("errors") or []
    label = ERROR_TYPE_LABEL[error_type]
    type_hit = any((e.get("error_type") or "").strip() == label for e in errs)
    anchor = gold["errors"][0].get("anchor_text") or ""
    span_hit = False
    if anchor:
        for e in errs:
            a = (e.get("anchor_text") or "").strip()
            if a and (a in anchor or anchor in a):
                span_hit = True
                break
    return has_error, type_hit, span_hit


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    ap.add_argument("--model", default="gpu-qwen3.8-27b")
    ap.add_argument("--out", default=str(ROOT / "runs" / "ablation"))
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
        if per_type[r["error_type"]] < args.limit:
            per_type[r["error_type"]] += 1
            picked.append(r)

    prompts = {t: load_prompt(mode, task) for t, (mode, task) in TASK_MAP.items()}
    kb_prompts = {
        t: load_prompt(mode, task, KB_PROMPT_ROOT) for t, (mode, task) in TASK_MAP.items()
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(args.concurrency)
    results = []

    async with httpx.AsyncClient() as client:
        async def worker(row: dict) -> None:
            async with sem:
                t = row["error_type"]
                sp = prompts[t]
                # condition A: no knowledge base
                parsed_a, err_a = await call(client, args.base_url, api_key, args.model, sp, {
                    "reference": "",
                    "detection_content": row["full_text"],
                })
                # condition B: with retrieved textbook evidence
                hits = kb_retrieval.search(row["full_text"], top_k=3)
                evidence = kb_retrieval.format_evidence(hits)
                reference = (
                    "以下是与该题相关的教材片段，仅作为学科常识参考：\n" + evidence
                    if evidence else ""
                )
                parsed_b, err_b = await call(client, args.base_url, api_key, args.model,
                                             kb_prompts[t], {
                    "reference": reference,
                    "detection_content": row["full_text"],
                })
                g = gold[row["sample_id"]]
                a = score(parsed_a, t, g)
                b = score(parsed_b, t, g)
                results.append({
                    "sample_id": row["sample_id"],
                    "error_type": t,
                    "evidence_count": len(hits),
                    "without_kb": {"has_error": a[0], "type_hit": a[1], "span_hit": a[2], "error": err_a},
                    "with_kb": {"has_error": b[0], "type_hit": b[1], "span_hit": b[2], "error": err_b},
                })

        await asyncio.gather(*(worker(r) for r in picked))

    path = out_dir / "ablation_results.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")

    print(f"{'error_type':<18}{'n':>4}{'noKB检出':>10}{'KB检出':>9}{'Δ':>7}"
          f"{'noKB定位':>10}{'KB定位':>9}{'Δ':>7}")
    print("-" * 76)
    tot = defaultdict(lambda: {"n": 0})
    for r in results:
        s = tot[r["error_type"]]
        s["n"] += 1
        s["a_det"] = s.get("a_det", 0) + int(r["without_kb"]["type_hit"])
        s["b_det"] = s.get("b_det", 0) + int(r["with_kb"]["type_hit"])
        s["a_span"] = s.get("a_span", 0) + int(r["without_kb"]["span_hit"])
        s["b_span"] = s.get("b_span", 0) + int(r["with_kb"]["span_hit"])

    for t in TASK_MAP:
        s = tot[t]
        n = max(s["n"], 1)
        ad, bd = s["a_det"] / n, s["b_det"] / n
        as_, bs = s["a_span"] / n, s["b_span"] / n
        print(f"{t:<18}{s['n']:>4}{ad:>9.0%}{bd:>9.0%}{bd-ad:>+7.0%}"
              f"{as_:>10.0%}{bs:>9.0%}{bs-as_:>+7.0%}")

    alln = len(results)
    ad = sum(s["a_det"] for s in tot.values()) / alln
    bd = sum(s["b_det"] for s in tot.values()) / alln
    print("-" * 76)
    print(f"{'TOTAL':<18}{alln:>4}{ad:>9.0%}{bd:>9.0%}{bd-ad:>+7.0%}")
    print()
    print("results:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
