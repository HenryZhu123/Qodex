#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backfill explanations from MinerU Markdown into reference-question records.

MinerU produces Markdown like:

    ## 1.解析：
    假设第k次循环终止...

    ## 2.解析：
    ...

or the heading may carry the number inside the body. This script extracts each
"解析" block keyed by question number and merges it into
reference_questions.jsonl as the `explanation` field (only when empty).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:\*\*)?\s*(\d{1,2})\s*[.．]\s*(?:【\s*解析\s*】|解析)\s*[:：]?\s*(?:\*\*)?\s*$",
    re.M,
)
INLINE_RE = re.compile(
    r"(?<![\d])(\d{1,2})\s*[.．]\s*(?:【\s*解析\s*】|解析)\s*[:：]", re.M
)


def extract_explanations(md: str) -> dict[int, str]:
    text = md.replace("\r\n", "\n")
    marks: list[tuple[int, int, int]] = []
    for m in HEADING_RE.finditer(text):
        marks.append((int(m.group(1)), m.start(), m.end()))
    if len(marks) < 20:
        # Fall back to inline markers.
        marks = []
        for m in INLINE_RE.finditer(text):
            marks.append((int(m.group(1)), m.start(), m.end()))
    marks = [m for m in marks if 1 <= m[0] <= 47]
    marks.sort(key=lambda x: x[1])

    out: dict[int, str] = {}
    for i, (num, _, end) in enumerate(marks):
        stop = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        body = text[end:stop]
        body = re.sub(r"<!--\s*image\s*-->", "", body)
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{2,}", "\n", body).strip()
        if body and num not in out:
            out[num] = body[:4000]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True, help="reference_questions.jsonl")
    ap.add_argument("--mineru-dir", required=True, help="dir with <year>_mineru.md")
    ap.add_argument("--out", required=True, help="output jsonl")
    args = ap.parse_args()

    records_path = Path(args.records)
    mineru_dir = Path(args.mineru_dir)
    out_path = Path(args.out)

    records = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    cache: dict[int, dict[int, str]] = {}
    for md_file in sorted(mineru_dir.glob("*_mineru.md")):
        m = re.match(r"(\d{4})_mineru\.md$", md_file.name)
        if not m:
            continue
        year = int(m.group(1))
        cache[year] = extract_explanations(md_file.read_text(encoding="utf-8"))
        print(f"{year}: {len(cache[year])} explanations extracted")

    filled = 0
    for rec in records:
        if rec.get("explanation"):
            continue
        year = rec.get("year")
        qno = rec.get("question_no")
        exp = cache.get(year, {}).get(qno)
        if exp:
            rec["explanation"] = exp
            rec["explanation_source"] = "mineru"
            filled += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    total_with = sum(1 for r in records if r.get("explanation"))
    print(f"backfilled {filled}; total with explanation: {total_with}/{len(records)}")
    print("written:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
