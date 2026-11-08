#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run MinerU answer extraction for all scanned years in one batch."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

SKILL = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\skills\build-knowledge-base")
sys.path.insert(0, str(SKILL / "scripts" / "refq"))

import mineru_answers as m  # noqa: E402

ANSWERS_DIR = Path(
    r"D:\Code\hku\LLM\hku_agent\research-assets\408exam\真题\02_参考答案_2009-2026"
)
OUT = Path(r"D:\Code\hku\LLM\kb_ocr_review\mineru")

YEARS = [2019, 2021, 2024, 2025, 2026]


async def run_one(year: int) -> dict:
    pdf = ANSWERS_DIR / f"{year}-answer.pdf"
    args = type("A", (), {})()
    args.answer_pdf = str(pdf)
    args.out = str(OUT)
    args.year = year
    args.base_url = m.DEFAULT_BASE_URL
    args.timeout = 300.0
    args.poll = 3.0
    args.retries = 4
    print(f"=== {year} start", flush=True)
    code = await m.run(args)
    parsed = OUT / f"{year}_mineru_parsed.json"
    if parsed.exists():
        data = json.loads(parsed.read_text(encoding="utf-8"))
        print(f"=== {year} done rc={code} found={data['found']} missing={data['missing']}", flush=True)
        return data
    print(f"=== {year} failed rc={code}", flush=True)
    return {"year": year, "found": 0, "missing": list(range(1, 41)), "answers": {}}


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for year in YEARS:
        results.append(await run_one(year))

    summary = OUT / "batch_summary.json"
    summary.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== SUMMARY =====")
    for r in results:
        seq = r.get("sequence") or "".join(r["answers"].get(str(n), "?") for n in range(1, 41))
        print(f"{r['year']}: {r['found']}/40 missing={r['missing']}")
        print(f"   {seq}")
    print("summary:", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
