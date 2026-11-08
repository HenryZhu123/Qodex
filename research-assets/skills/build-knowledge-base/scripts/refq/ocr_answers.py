#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR the scanned answer keys and extract the 40 choice answers.

Used for years whose answer PDF has no text layer:
2019, 2021, 2024, 2025, 2026.

The answer key always starts with a 5-row x 8-column table listing question
numbers and letters. We render the top region of page 1 at high DPI, OCR it with
chi_sim+eng, then parse "number + letter" pairs line by line.

Outputs (for human review):
  <out>/<year>_page1.png         rendered region used for OCR
  <out>/<year>_ocr.txt           raw OCR text
  <out>/<year>_parsed.json       parsed answers + per-question provenance
  <out>/<year>_review.md         side-by-side review sheet
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import fitz

TESSERACT = r"D:\Programs\Tesseract-OCR\tesseract.exe"

LETTER = re.compile(r"^[A-D]$")
NUM = re.compile(r"^(\d{1,2})\s*[.．,，:：]?$")
PAIR = re.compile(r"(\d{1,2})\s*[.．,，:：]\s*([A-D])(?![A-Za-z])")

# OCR confusions observed on scanned 408 answer tables.
OCR_FIX = {
    "Cc": "C", "cC": "C", "€": "C", "e": "C", "E": "C",
    "2B": "B", "BR": "B", "8B": "B", "&B": "B",
    "A4": "A", "4A": "A",
    "Dd": "D", "dD": "D",
}
ROW_HINT = re.compile(r"^\s*(?:l|I|1|\d{1,2})\s*[.．,，:：]")


def clean_letter(token: str) -> str:
    t = token.strip()
    if t in OCR_FIX:
        return OCR_FIX[t]
    # "Cc" -> "C", "（B" -> "B"
    stripped = re.sub(r"[^A-Da-d]", "", t)
    if len(stripped) == 1:
        return stripped.upper()
    if stripped and len(set(stripped.upper())) == 1:
        return stripped[0].upper()
    return ""


def parse_table_rows(text: str) -> dict[int, str]:
    """Parse the 5-row answer table row by row.

    Each row looks like: "1. B 2. B 3. C ... 8. C".
    We tokenise by question-number markers and take the following letter-ish
    token, repairing common OCR confusions.
    """
    answers: dict[int, str] = {}
    # Only consider lines that look like table rows (have >=3 number markers).
    for line in text.splitlines():
        markers = list(re.finditer(r"(?<![\d])(\d{1,2})\s*[.．,，:：]", line))
        if len(markers) < 3:
            continue
        for i, m in enumerate(markers):
            num = int(m.group(1))
            if num == 0:
                num = 1  # OCR often reads "1." as "l." or "I."
            if not (1 <= num <= 40):
                continue
            end = markers[i + 1].start() if i + 1 < len(markers) else len(line)
            seg = line[m.end():end]
            # Take the first letter-ish token in the segment.
            cand = re.findall(r"[A-Za-z€]{1,3}", seg)
            for token in cand:
                letter = clean_letter(token)
                if letter:
                    answers.setdefault(num, letter)
                    break
    return answers


def parse_answers(text: str) -> tuple[dict[int, str], list[str]]:
    """Parse OCR text into {question_no: letter}."""
    notes: list[str] = []
    answers = parse_table_rows(text)

    # Fallback: inline pairs and number-then-letter lines.
    if len(answers) < 35:
        for m in PAIR.finditer(text):
            num = int(m.group(1))
            if 1 <= num <= 40:
                answers.setdefault(num, m.group(2))

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    pending: int | None = None
    for ln in lines:
        if pending is not None:
            letter = clean_letter(ln)
            if letter:
                answers.setdefault(pending, letter)
                pending = None
                continue
        m = NUM.match(ln)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 40:
                pending = num
                continue
        pending = None

    missing = [n for n in range(1, 41) if n not in answers]
    if missing:
        notes.append(f"missing {len(missing)}: {missing}")
    return answers, notes


def render_region(pdf: Path, out_png: Path, page: int = 0, dpi: int = 400,
                  top_ratio: float = 0.0, bottom_ratio: float = 0.55) -> fitz.Rect:
    doc = fitz.open(str(pdf))
    pg = doc[page]
    h = pg.rect.height
    # The answer table usually occupies the middle of page 1; default covers
    # 0%-55% of the page height, which includes the title and the 5 rows.
    clip = fitz.Rect(0, h * top_ratio, pg.rect.width, h * bottom_ratio)
    pix = pg.get_pixmap(clip=clip, dpi=dpi)
    pix.save(str(out_png))
    doc.close()
    return clip


def run_tesseract(png: Path, out_base: Path, psm: int = 6, lang: str = "chi_sim+eng") -> str:
    cmd = [
        TESSERACT,
        str(png),
        str(out_base),
        "-l",
        lang,
        "--psm",
        str(psm),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract failed: {proc.stderr[:400]}")
    txt = Path(str(out_base) + ".txt")
    return txt.read_text(encoding="utf-8", errors="replace")


def parse_answers(text: str) -> tuple[dict[int, str], list[str]]:
    """Parse OCR text into {question_no: letter}.

    Two passes:
      1. inline pairs "1. B" / "1 B"
      2. line-wise: a line with only a number, followed by a line with only a letter
    """
    answers: dict[int, str] = {}
    notes: list[str] = []

    for m in PAIR.finditer(text):
        num = int(m.group(1))
        if 1 <= num <= 40 and num not in answers:
            answers[num] = m.group(2)

    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    pending: int | None = None
    for ln in lines:
        if pending is not None and LETTER.match(ln):
            if pending not in answers:
                answers[pending] = ln
            pending = None
            continue
        m = NUM.match(ln)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 40:
                pending = num
                continue
        pending = None

    missing = [n for n in range(1, 41) if n not in answers]
    if missing:
        notes.append(f"missing {len(missing)}: {missing}")
    return answers, notes


def write_review(year: int, answers: dict[int, str], notes: list[str], out_md: Path, png: Path, raw: Path) -> None:
    rows = ["# {0} 答案 OCR 审阅单".format(year), ""]
    rows.append(f"- 渲染图：`{png}`")
    rows.append(f"- OCR 原文：`{raw}`")
    rows.append("")
    rows.append(f"识别到 {len(answers)}/40 题。缺失：{', '.join(str(n) for n in range(1, 41) if n not in answers) or '无'}")
    rows.append("")
    rows.append("| 题号 | 识别答案 | 人工核对 | 是否一致 |")
    rows.append("|---:|:---:|:---:|:---:|")
    for n in range(1, 41):
        got = answers.get(n, "")
        rows.append(f"| {n} | {got or '—'} |  |  |")
    rows.append("")
    if notes:
        rows.append("## 备注")
        for note in notes:
            rows.append(f"- {note}")
        rows.append("")
    rows.append("## 使用方式")
    rows.append("")
    rows.append("核对后，把确认的答案写入 `manual_answers.json`：")
    rows.append("")
    rows.append("```json")
    rows.append(json.dumps({str(year): {str(n): answers.get(n, "") for n in range(1, 41)}}, ensure_ascii=False, indent=2)[:800])
    rows.append("```")
    out_md.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR scanned 408 answer keys.")
    parser.add_argument("--answer-pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--dpi", type=int, default=400)
    parser.add_argument("--psm", type=int, default=6)
    parser.add_argument("--page", type=int, default=0, help="1-based page number to OCR")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    year = args.year

    png = out_dir / f"{year}_page{args.page + 1}.png"
    render_region(Path(args.answer_pdf), png, page=args.page, dpi=args.dpi)

    # Write Tesseract output directly into the output dir (no temp dir: the
    # platform temp cleanup can fail under restricted sandboxes).
    base = out_dir / f"{year}_ocr_raw"
    text = run_tesseract(png, base, psm=args.psm)
    generated_txt = Path(str(base) + ".txt")
    if generated_txt.exists():
        generated_txt.unlink()

    raw = out_dir / f"{year}_ocr.txt"
    raw.write_text(text, encoding="utf-8")

    answers, notes = parse_answers(text)
    parsed = out_dir / f"{year}_parsed.json"
    parsed.write_text(
        json.dumps(
            {
                "year": year,
                "source_pdf": str(args.answer_pdf),
                "rendered_png": str(png),
                "raw_ocr": str(raw),
                "dpi": args.dpi,
                "psm": args.psm,
                "found": len(answers),
                "missing": [n for n in range(1, 41) if n not in answers],
                "answers": {str(n): answers[n] for n in sorted(answers)},
                "sequence": "".join(answers[n] for n in sorted(answers)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    review = out_dir / f"{year}_review.md"
    write_review(year, answers, notes, review, png, raw)

    print(f"rendered: {png}")
    print(f"ocr text: {raw}")
    print(f"parsed  : {parsed}")
    print(f"review  : {review}")
    print(f"found {len(answers)}/40")
    print("sequence:", "".join(answers[n] for n in sorted(answers)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
