#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract 408 choice answers from scanned answer keys using MinerU Agent API.

MinerU converts the scanned PDF page into Markdown with layout and table
structure preserved, which is far more reliable than raw OCR for the answer
table.

Usage:
  python mineru_answers.py --answer-pdf <file.pdf> --year 2019 --out <dir>

Outputs:
  <out>/<year>_mineru.md        MinerU Markdown output
  <out>/<year>_mineru_parsed.json   parsed answers
  <out>/<year>_mineru_review.md     human review sheet

Requires: httpx (already used by pi-coding-agent services).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# Reuse the MinerU client already used by the exam-checker service.
SERVICE_SRC = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src"
)
if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from exam_checker.integrations.mineru_agent import (  # noqa: E402
    MinerUAgentClient,
    MinerUError,
    MinerULimitError,
)

DEFAULT_BASE_URL = "https://mineru.net/api/v1/agent"


def normalize_markdown(md: str) -> str:
    """Collapse MinerU spacing artifacts around digits and letters."""
    text = md.replace("\u3000", " ")
    # Full-width to half-width digits/letters.
    table = str.maketrans(
        "０１２３４５６７８９ＡＢＣＤａｂｃｄ",
        "0123456789ABCDabcd",
    )
    return text.translate(table)


def parse_html_tables(md: str) -> dict[int, str]:
    """Parse MinerU HTML tables such as
    <tr><td>1.</td><td>B</td><td>2.</td><td>B</td>...</tr>

    Cells alternate number / answer. Some cells are empty or contain a glued
    pair like "AＣ" or "16. D".
    """
    answers: dict[int, str] = {}
    for table in re.finditer(r"<table>(.*?)</table>", md, re.S | re.I):
        rows = re.findall(r"<tr>(.*?)</tr>", table.group(1), re.S | re.I)
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            i = 0
            while i < len(cells):
                cell = cells[i]
                m = re.fullmatch(r"([0-9]{1,2})\s*[.．]?", cell)
                if m:
                    num = int(m.group(1))
                    nxt = cells[i + 1] if i + 1 < len(cells) else ""
                    letter = first_letter(nxt)
                    if 1 <= num <= 40 and letter:
                        answers.setdefault(num, letter)
                    i += 2
                    continue
                # Glued pair inside one cell, e.g. "16. D".
                pair = re.fullmatch(r"([0-9]{1,2})\s*[.．]?\s*([A-D])", cell)
                if pair:
                    num = int(pair.group(1))
                    if 1 <= num <= 40:
                        answers.setdefault(num, pair.group(2))
                i += 1
    return answers


def first_letter(cell: str) -> str | None:
    """Return A-D from a cell that may also contain stray glyphs."""
    cleaned = re.sub(r"[^A-DＡ-Ｄ]", "", cell)
    if not cleaned:
        return None
    ch = cleaned[0]
    if "Ａ" <= ch <= "Ｄ":
        return chr(ord(ch) - ord("Ａ") + ord("A"))
    return ch


def parse_answers(md: str) -> tuple[dict[int, str], list[str]]:
    """Parse answers from MinerU Markdown/HTML."""
    text = normalize_markdown(md)
    answers: dict[int, str] = {}
    notes: list[str] = []

    # 0. MinerU emits HTML tables most of the time.
    answers.update(parse_html_tables(text))

    # 1. Markdown tables.
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        for i in range(len(cells) - 1):
            if re.fullmatch(r"\d{1,2}", cells[i]) and re.fullmatch(r"[A-D]", cells[i + 1]):
                num = int(cells[i])
                if 1 <= num <= 40:
                    answers.setdefault(num, cells[i + 1])

    # 2. Inline pairs.
    for m in re.finditer(r"(?<![\d])(\d{1,2})\s*[.．,，:：、]?\s*([A-D])(?![A-Za-z])", text):
        num = int(m.group(1))
        if 1 <= num <= 40:
            answers.setdefault(num, m.group(2))

    # 3. Number line followed by letter line.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    pending: int | None = None
    for ln in lines:
        plain = re.sub(r"[*_`#|]", "", ln).strip()
        if not plain:
            continue
        if re.fullmatch(r"[A-D]", plain) and pending is not None:
            answers.setdefault(pending, plain)
            pending = None
            continue
        m = re.fullmatch(r"(\d{1,2})\s*[.．,，:：、]?", plain)
        if m:
            num = int(m.group(1))
            pending = num if 1 <= num <= 40 else None
            continue
        pending = None

    missing = [n for n in range(1, 41) if n not in answers]
    if missing:
        notes.append(f"missing {len(missing)}: {missing}")
    return answers, notes


def write_review(
    year: int,
    md_path: Path,
    answers: dict[int, str],
    notes: list[str],
    out_md: Path,
) -> None:
    lines = [f"# {year} 年 408 选择题答案（MinerU）", ""]
    lines.append("## 文件")
    lines.append("")
    lines.append(f"- MinerU Markdown：`{md_path}`")
    lines.append("")
    lines.append(f"识别 {len(answers)}/40 题。")
    lines.append("")
    lines.append("| 题号 | MinerU 答案 | 人工核对 | 是否一致 |")
    lines.append("|---:|:---:|:---:|:---:|")
    for n in range(1, 41):
        got = answers.get(n, "")
        lines.append(f"| {n} | {got or '—'} |  |  |")
    lines.append("")
    if notes:
        lines.append("## 备注")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")
    lines.append("## 回填 manual_answers.json")
    lines.append("")
    lines.append("```json")
    payload = {str(year): {str(n): answers.get(n, "") for n in range(1, 41)}}
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
    lines.append("```")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run(args: argparse.Namespace) -> int:
    pdf = Path(args.answer_pdf)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    data = pdf.read_bytes()
    client = MinerUAgentClient(
        args.base_url,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll,
        max_retries=args.retries,
    )
    try:
        doc = await client.parse_file(
            data,
            pdf.name,
            language="ch",
            is_ocr=True,
            enable_table=True,
            enable_formula=False,
        )
    except MinerULimitError as exc:
        print(f"MinerU limit error: {exc}", file=sys.stderr)
        return 2
    except MinerUError as exc:
        print(f"MinerU error: {exc}", file=sys.stderr)
        return 3
    finally:
        await client.close()

    md_path = out / f"{args.year}_mineru.md"
    md_path.write_text(doc.markdown, encoding="utf-8")

    answers, notes = parse_answers(doc.markdown)
    parsed_path = out / f"{args.year}_mineru_parsed.json"
    parsed_path.write_text(
        json.dumps(
            {
                "year": args.year,
                "source_pdf": str(pdf),
                "task_id": doc.provider_task_id,
                "provider": doc.provider,
                "markdown_chars": len(doc.markdown),
                "found": len(answers),
                "missing": [n for n in range(1, 41) if n not in answers],
                "answers": {str(n): answers[n] for n in sorted(answers)},
                "sequence": "".join(answers.get(n, "?") for n in range(1, 41)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    review = out / f"{args.year}_mineru_review.md"
    write_review(args.year, md_path, answers, notes, review)

    print(f"markdown : {md_path}")
    print(f"parsed   : {parsed_path}")
    print(f"review   : {review}")
    print(f"found {len(answers)}/40")
    print("sequence:", "".join(answers.get(n, "?") for n in range(1, 41)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="MinerU-based answer extraction.")
    ap.add_argument("--answer-pdf", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--poll", type=float, default=3)
    ap.add_argument("--retries", type=int, default=4)
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
