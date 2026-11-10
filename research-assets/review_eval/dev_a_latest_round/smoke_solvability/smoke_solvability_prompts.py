#!/usr/bin/env python3
"""Prompt smoke test for the missing/unsolvable merge.

Arms differ only in the system prompt; model, payload and decoding are identical.

  split     legacy two-task layout (missing_check + unsolvability_check)
  short     current merged prompt (3.1 KB)
  long      merged prompt with every detailed rule restored (6.7 KB)
  short_v2  current merged prompt + an executable missing-condition program

Sample: Dev A + Dev B  legacy missing_info (40) and unsolvable (40),
plus 20 clean items as a false-positive control.

Note on `split` + clean: production runs both tasks on an unknown question, so a
clean item counts as a false positive when either legacy prompt reports.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(r"D:\Code\hku\LLM\hku_agent")
SERVICE = ROOT / "pi-coding-agent" / "services" / "exam-checker"
PROMPTS = SERVICE / "prompts" / "reviewer-prompt" / "qwen38_27b"
OUT = ROOT / "research-assets" / "review_eval" / "dev_a_latest_round" / "smoke_solvability"

DEV_A = ROOT / "research-assets/review_eval/taxonomy_v2/dev_a/strict/review_eval_dataset_v2.csv"
DEV_B = ROOT / "research-assets/review_eval/taxonomy_v2/dev_b/strict/blind_test_dataset.csv"
CONSTRAINT = PROMPTS / "explicit" / "JSON约束_with_think.txt"

SOLVABILITY_V2 = ROOT / "research-assets/review_eval/prompts/solvability"
LABEL = "可解性错误"

ARMS = {
    "split": {"missing_info": "信息缺失", "unsolvable": "题目无解"},
    "short": {"*": LABEL},
    "long": {"*": LABEL},
    "short_v2": {"*": LABEL},
}
PROMPT_FILES = {
    "split": {
        "missing_info": PROMPTS / "disabled/tasks/missing_check.txt",
        "unsolvable": PROMPTS / "explicit/tasks/unsolvability_check.txt",
    },
    "short": {"*": PROMPTS / "explicit/tasks/solvability_check.txt"},
    "long": {"*": SOLVABILITY_V2 / "solvability_merged_v2.txt"},
    "short_v2": {"*": SOLVABILITY_V2 / "solvability_short_v2.txt"},
}


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (SERVICE / ".env.local").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def load_samples() -> list[dict]:
    samples: list[dict] = []
    for path, source in ((DEV_A, "dev_a"), (DEV_B, "dev_b")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                label = row.get("label")
                if label == "clean":
                    if source == "dev_a":
                        samples.append({
                            "sample_id": row["sample_id"], "source": source,
                            "legacy_type": "", "full_text": row["full_text"],
                            "reference": row.get("reference", ""),
                        })
                    continue
                if row.get("error_type") != "solvability_failure":
                    continue
                legacy = row.get("legacy_error_type") or ""
                if legacy not in {"missing_info", "unsolvable"}:
                    continue
                samples.append({
                    "sample_id": row["sample_id"], "source": source,
                    "legacy_type": legacy, "full_text": row["full_text"],
                    "reference": row.get("reference", ""),
                })
    clean = sorted((s for s in samples if not s["legacy_type"]), key=lambda s: s["sample_id"])[:20]
    keep = {s["sample_id"] for s in clean}
    return [s for s in samples if s["legacy_type"] or s["sample_id"] in keep]


def parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


async def call(client, semaphore, base, key, model, system_prompt, payload, max_tokens, attempts) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"[INPUT_PAYLOAD]\n{json.dumps(payload, ensure_ascii=False)}"},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    last = ""
    async with semaphore:
        for attempt in range(1, attempts + 1):
            started = datetime.now()
            try:
                resp = await client.post(
                    f"{base.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                )
                if resp.status_code == 400 and "response_format" in body:
                    body.pop("response_format")
                    continue
                if resp.status_code != 200:
                    last = f"HTTP {resp.status_code}"
                    await asyncio.sleep(attempt * 2)
                    continue
                parsed = parse_json(resp.json()["choices"][0]["message"].get("content") or "")
                if parsed is None:
                    last = "parse_fail"
                    await asyncio.sleep(attempt * 2)
                    continue
                return {
                    "has_error": bool(parsed.get("has_error")),
                    "types": [e.get("error_type") for e in parsed.get("errors") or []],
                    "latency_ms": int((datetime.now() - started).total_seconds() * 1000),
                    "error": None,
                }
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                last = type(exc).__name__
                await asyncio.sleep(attempt * 2)
    return {"has_error": None, "types": [], "latency_ms": 0, "error": last}


def prompts_for(arm: str, legacy: str) -> list[Path]:
    table = PROMPT_FILES[arm]
    if legacy:
        return [table.get(legacy) or table["*"]]
    if arm == "split":
        return [table["missing_info"], table["unsolvable"]]
    return [table["*"]]


async def run_arm(arm: str, samples: list[dict], env: dict[str, str], args) -> dict:
    base = args.base_url or env["EXAM_CHECKER_REVIEW_LLM_BASE_URL"]
    key = env[args.api_key_var]
    model = args.model or env["EXAM_CHECKER_REVIEW_LLM_MODEL"]
    max_tokens = int(env.get("EXAM_CHECKER_REVIEW_MAX_TOKENS", "4096"))
    constraint = CONSTRAINT.read_text(encoding="utf-8").strip()
    cache: dict[Path, str] = {}

    def system_prompt(path: Path) -> str:
        if path not in cache:
            cache[path] = path.read_text(encoding="utf-8").strip() + "\n\n" + constraint
        return cache[path]

    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        async def one(item: dict) -> None:
            legacy = item["legacy_type"]
            expected = (ARMS[arm].get(legacy) or ARMS[arm]["*"]) if legacy else None
            payload = {"reference": item["reference"], "detection_content": item["full_text"]}
            responses = []
            for path in prompts_for(arm, legacy):
                responses.append(await call(client, semaphore, base, key, model,
                                            system_prompt(path), payload, max_tokens, args.attempts))
            ok = [r for r in responses if r["has_error"] is not None]
            detected = any(r["has_error"] is True for r in ok)
            results.append({
                **item,
                "arm": arm,
                "expected_label": expected,
                "has_error": None if not ok else detected,
                "types": [t for r in ok for t in r["types"]],
                "label_match": bool(detected and expected and expected in [t for r in ok for t in r["types"]]),
                "latency_ms": sum(r["latency_ms"] for r in responses),
                "error": None if ok else responses[0]["error"],
            })

        await asyncio.gather(*(one(item) for item in samples))

    with (OUT / f"arm_{arm}.jsonl").open("w", encoding="utf-8") as handle:
        for record in results:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    bad = [r for r in results if r["legacy_type"]]
    clean = [r for r in results if not r["legacy_type"]]
    summary = {
        "arm": arm,
        "n_error": len(bad),
        "detected": sum(1 for r in bad if r["has_error"] is True),
        "recall": round(sum(1 for r in bad if r["has_error"] is True) / max(1, len(bad)), 4),
        "n_clean": len(clean),
        "false_positives": sum(1 for r in clean if r["has_error"] is True),
        "fpr": round(sum(1 for r in clean if r["has_error"] is True) / max(1, len(clean)), 4),
        "failed": sum(1 for r in results if r["has_error"] is None),
        "avg_latency_s": round(sum(r["latency_ms"] for r in results) / max(1, len(results)) / 1000, 1),
        "by_legacy_type": {
            t: {
                "n": sum(1 for r in bad if r["legacy_type"] == t),
                "detected": sum(1 for r in bad if r["legacy_type"] == t and r["has_error"] is True),
            }
            for t in ("missing_info", "unsolvable")
        },
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default="split,short,long,short_v2")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key-var", default="EXAM_CHECKER_REVIEW_LLM_API_KEY")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    samples = load_samples()
    if args.limit:
        samples = samples[: args.limit]
    print(json.dumps({
        "samples": len(samples),
        "legacy": dict(Counter(s["legacy_type"] or "clean" for s in samples)),
    }, ensure_ascii=False), flush=True)

    env = load_env()
    summaries = []
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        summaries.append(await run_arm(arm, samples, env, args))

    (OUT / "summary4.json").write_text(
        json.dumps({
            "samples": len(samples),
            "model": args.model or env.get("EXAM_CHECKER_REVIEW_LLM_MODEL"),
            "base_url": args.base_url or env.get("EXAM_CHECKER_REVIEW_LLM_BASE_URL"),
            "arms": summaries,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
