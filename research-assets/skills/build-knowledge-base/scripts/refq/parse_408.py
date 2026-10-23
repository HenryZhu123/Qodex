#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse 408 exam papers and answer keys into reference-question records.

Input layout (research-assets/408exam/真题/):
  01_重排版试卷_2009-2026/<year>.pdf           re-typeset exam papers
  02_参考答案_2009-2026/<year>-answer.pdf      answer keys
  manual_answers.json                          human-verified overrides

The parser handles five answer-key layouts. Anything it cannot read is
reported as a gap; gaps can be filled by manual_answers.json, which always
wins over automatic extraction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz

PAPER_DIR = "01_重排版试卷_2009-2026"
ANSWER_DIR = "02_参考答案_2009-2026"
MANUAL_FILE = "manual_answers.json"

# 408 subject split (official blueprint).
CHOICE_SUBJECT = {
    **{n: "data_structure" for n in range(1, 11)},
    **{n: "computer_organization" for n in range(11, 16)},
    **{n: "operating_system" for n in range(16, 26)},
    **{n: "computer_network" for n in range(26, 41)},
}
COMPREHENSIVE_SUBJECT = {
    **{n: "data_structure" for n in range(41, 43)},
    **{n: "computer_organization" for n in range(43, 45)},
    **{n: "operating_system" for n in range(45, 47)},
    **{n: "computer_network" for n in range(47, 48)},
}

# Page furniture, e.g.
# "2024 年全国硕士研究生入学统一考试计算机学科专业基础综合试题 第 5 页（共 12 页）"
PAGE_FURNITURE_RE = re.compile(
    r"^\s*\d{4}\s*年全国硕士研究生入学统一考试.{0,60}第\s*\d+\s*页.*$", re.M
)
SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十]\s*、\s*(.+?)\s*$", re.M)
ITEM_RE = re.compile(r"^[ \t]*(\d{1,2})[.．][ \t]*(\S.*)$", re.M)
OPTION_RE = re.compile(r"^[ \t]*([A-D])[.．][ \t]*(\S.*)$", re.M)
SUBQ_RE = re.compile(r"^\s*[（(]\s*(\d{1,2})\s*[)）]", re.M)
SCORE_RE = re.compile(r"[（(]\s*(\d{1,2}(?:\.\d)?)\s*分\s*[)）]")

# Answer-key layouts.
LABEL_RE = re.compile(r"^(\d{1,2})\s*[.．:：]$")
LETTER_RE = re.compile(r"^[A-D]$")
MULTI_RE = re.compile(r"^[A-D]{4,}$")
INLINE_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*[.．]\s*([A-D])(?![\u4e00-\u9fff])")
LABELLED_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*[.．]\s*[【\[]\s*参考答案\s*[】\]]\s*([A-D])")
EXPLAIN_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*[.．]\s*[【\[]?\s*解析\s*[】\]]?\s*[:：]?")
# "<num>. X。【解析】..."  (2022 style)
EXPLAIN_INLINE_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*[.．]\s*([A-D])\s*[。.．]?\s*[【\[]\s*解析\s*[】\]]", re.M
)
# "<num>.【参考答案】X 【解析】..."  (2023 style)
EXPLAIN_WITH_ANSWER_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*[.．]\s*[【\[]\s*参考答案\s*[】\]]\s*([A-D])\s*[【\[]\s*解析\s*[】\]]",
    re.M,
)


@dataclass
class AnswerKey:
    year: int
    answers: dict[int, str] = field(default_factory=dict)
    explanations: dict[int, str] = field(default_factory=dict)
    text_available: bool = True
    method: str = "unknown"


@dataclass
class Paper:
    year: int
    choices: list[dict[str, Any]] = field(default_factory=list)
    comprehensive: list[dict[str, Any]] = field(default_factory=list)


# --------------------------------------------------------------------------
# PDF helpers
# --------------------------------------------------------------------------

def read_pages(pdf: Path) -> list[str]:
    doc = fitz.open(str(pdf))
    pages = [doc[i].get_text() for i in range(len(doc))]
    doc.close()
    return pages


def read_words(pdf: Path, pages: int = 3) -> list[tuple[float, float, str]]:
    doc = fitz.open(str(pdf))
    out: list[tuple[float, float, str]] = []
    for i in range(min(pages, len(doc))):
        for w in doc[i].get_text("words"):
            out.append((w[1], w[0], w[4]))
    doc.close()
    return out


def cluster(values: list[float], tol: float) -> list[float]:
    if not values:
        return []
    values = sorted(values)
    centers = [values[0]]
    for v in values[1:]:
        if abs(v - centers[-1]) <= tol:
            centers[-1] = (centers[-1] + v) / 2
        else:
            centers.append(v)
    return centers


def clean_page_text(raw: str) -> str:
    text = PAGE_FURNITURE_RE.sub("", raw)
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --------------------------------------------------------------------------
# Paper parsing
# --------------------------------------------------------------------------

def split_sections(full_text: str) -> tuple[str, str]:
    choice_start = comp_start = None
    for m in SECTION_RE.finditer(full_text):
        title = m.group(1)
        if "单项选择" in title and choice_start is None:
            choice_start = m.end()
        elif "综合应用" in title and comp_start is None:
            comp_start = m.start()
    if choice_start is None:
        return "", ""
    if comp_start is None:
        return full_text[choice_start:], ""
    return full_text[choice_start:comp_start], full_text[comp_start:]


def _item_boundaries(block: str, lo: int, hi: int) -> dict[int, tuple[int, int]]:
    seen: dict[int, tuple[int, int]] = {}
    for m in ITEM_RE.finditer(block):
        num = int(m.group(1))
        if lo <= num <= hi and num not in seen:
            seen[num] = (m.start(), m.end())
    return seen


def parse_choices(block: str) -> list[dict[str, Any]]:
    seen = _item_boundaries(block, 1, 40)
    nums = sorted(seen)
    items: list[dict[str, Any]] = []
    for idx, num in enumerate(nums):
        start, _ = seen[num]
        stop = seen[nums[idx + 1]][0] if idx + 1 < len(nums) else len(block)
        # Keep the whole span (including the first line) and drop only the
        # "N." prefix so multi-line stems are preserved.
        span = block[start:stop]
        span = re.sub(r"^[ \t]*\d{1,2}[.．][ \t]*", "", span, count=1)
        body = span.strip()
        # PDF text extraction often places several options on one line, e.g.
        # "A. 顺序存储B. 散列存储C. 链式存储D. 索引存储". Find every option
        # marker anywhere in the body, not just at line starts.
        opt_marks = [
            m for m in re.finditer(r"(?<![A-Za-z0-9])[ \t]*([A-D])[.．][ \t]*", body)
        ]
        # Keep the first occurrence of each letter, in order.
        kept: list[re.Match[str]] = []
        seen_letters: set[str] = set()
        for m in opt_marks:
            letter = m.group(1)
            if letter in seen_letters:
                continue
            seen_letters.add(letter)
            kept.append(m)
        stem = body[: kept[0].start()].strip() if kept else body
        options: dict[str, str] = {}
        for i, m in enumerate(kept):
            end = kept[i + 1].start() if i + 1 < len(kept) else len(body)
            value = re.sub(r"[ \t]*\n[ \t]*", " ", body[m.end():end]).strip()
            if value:
                options[m.group(1)] = value
        complete = all(a in options and options[a] for a in "ABCD")
        items.append({
            "question_no": num,
            "subject": CHOICE_SUBJECT.get(num, "unknown"),
            "question_type": "single_choice",
            "stem": re.sub(r"[ \t]*\n[ \t]*", "\n", stem).strip(),
            "options": options,
            "options_complete": complete,
        })
    return items


def parse_comprehensive(block: str) -> list[dict[str, Any]]:
    seen = _item_boundaries(block, 41, 47)
    nums = sorted(seen)
    items: list[dict[str, Any]] = []
    for idx, num in enumerate(nums):
        start, end = seen[num]
        stop = seen[nums[idx + 1]][0] if idx + 1 < len(nums) else len(block)
        score_m = SCORE_RE.search(block[start:stop])
        span = block[start:stop]
        span = re.sub(r"^[ \t]*\d{1,2}[.．][ \t]*", "", span, count=1)
        body = span.strip()
        items.append({
            "question_no": num,
            "subject": COMPREHENSIVE_SUBJECT.get(num, "unknown"),
            "question_type": "comprehensive",
            "stem": re.sub(r"[ \t]*\n[ \t]*", "\n", body).strip(),
            "score": float(score_m.group(1)) if score_m else None,
            "subquestions": [m.group(1) for m in SUBQ_RE.finditer(body)],
        })
    return items


def parse_paper(pdf: Path, year: int) -> Paper:
    full = "\n".join(clean_page_text(p) for p in read_pages(pdf))
    choice_block, comp_block = split_sections(full)
    return Paper(
        year=year,
        choices=parse_choices(choice_block),
        comprehensive=parse_comprehensive(comp_block),
    )


# --------------------------------------------------------------------------
# Answer-key parsing
# --------------------------------------------------------------------------

def parse_explanations(text: str) -> dict[int, str]:
    """Collect explanation bodies across the observed layouts.

    Layouts:
      A. "<n>. 解析："                        (2009-2018, 2020)
      B. "<n>. X。【解析】"                    (2022)
      C. "<n>.【参考答案】X 【解析】"           (2023)
      D. MinerU "## <n>.解析："               (not used here)
    """
    marks: list[tuple[int, int, int]] = []
    for regex in (EXPLAIN_WITH_ANSWER_RE, EXPLAIN_INLINE_RE):
        for m in regex.finditer(text):
            marks.append((int(m.group(1)), m.start(), m.end()))
    # Plain "<n>. 解析：" style: append only numbers not already covered.
    covered = {m[0] for m in marks}
    for m in EXPLAIN_RE.finditer(text):
        num = int(m.group(1))
        if num not in covered:
            marks.append((num, m.start(), m.end()))

    marks.sort(key=lambda x: x[1])
    out: dict[int, str] = {}
    for i, (num, _, end) in enumerate(marks):
        if num > 47 or num in out:
            continue
        stop = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        body = re.sub(r"\s+", " ", text[end:stop]).strip()
        if body:
            out[num] = body[:4000]
    return out


def answers_from_labelled(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for m in LABELLED_RE.finditer(text):
        num = int(m.group(1))
        if 1 <= num <= 40:
            out.setdefault(num, m.group(2))
    return out


def answers_from_grid(pdf: Path) -> dict[int, str]:
    """Read the 5-row answer table using label/letter coordinates."""
    words = read_words(pdf)
    labels = [(y, x, int(m.group(1))) for y, x, t in words for m in [LABEL_RE.match(t)] if m]
    if len(labels) < 40:
        return {}

    rows = cluster([y for y, _, _ in labels], tol=6.0)
    cols = cluster([x for _, x, _ in labels], tol=6.0)
    if len(rows) < 5 or len(cols) < 5:
        return {}

    number_at: dict[tuple[int, int], int] = {}
    for y, x, num in labels:
        r = min(range(len(rows)), key=lambda i: abs(rows[i] - y))
        c = min(range(len(cols)), key=lambda i: abs(cols[i] - x))
        if 1 <= num <= 40:
            number_at.setdefault((r, c), num)

    answers: dict[int, str] = {}

    # Standalone letters beside a label.
    for y, x, t in words:
        if not LETTER_RE.match(t):
            continue
        r = min(range(len(rows)), key=lambda i: abs(rows[i] - y))
        if abs(rows[r] - y) > 6:
            continue
        c = min(range(len(cols)), key=lambda i: abs(cols[i] - x))
        num = number_at.get((r, c))
        if num is not None:
            answers.setdefault(num, t)

    # Multi-letter runs: assign consecutive numbers within the row.
    row_runs: dict[int, list[tuple[float, str]]] = {}
    for y, x, t in words:
        if not MULTI_RE.match(t):
            continue
        r = min(range(len(rows)), key=lambda i: abs(rows[i] - y))
        if abs(rows[r] - y) > 12:
            continue
        row_runs.setdefault(r, []).append((x, t))
    for r, items in row_runs.items():
        letters = "".join(t for _, t in sorted(items))
        row_numbers = sorted(number_at[(r, c)] for c in range(len(cols)) if (r, c) in number_at)
        if not row_numbers:
            continue
        for i, letter in enumerate(letters):
            num = row_numbers[0] + i
            if 1 <= num <= 40:
                answers.setdefault(num, letter)

    return answers


def answers_from_inline(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for m in INLINE_RE.finditer(text):
        num = int(m.group(1))
        if 1 <= num <= 40:
            out.setdefault(num, m.group(2))
    return out


def answers_from_single_column(text: str) -> dict[int, str]:
    """40 lone letters in reading order (2022 style)."""
    letters = [ln.strip() for ln in text.splitlines() if LETTER_RE.match(ln.strip())]
    if len(letters) < 40:
        return {}
    return {i: letter for i, letter in enumerate(letters[:40], start=1)}


def parse_answer_key(pdf: Path, year: int) -> AnswerKey:
    pages = read_pages(pdf)
    if not any(p.strip() for p in pages):
        return AnswerKey(year=year, text_available=False, method="scanned")

    full = "\n".join(clean_page_text(p) for p in pages)
    key = AnswerKey(year=year, explanations=parse_explanations(full))

    for name, candidate in (
        ("labelled", answers_from_labelled(full)),
        ("grid", answers_from_grid(pdf)),
        ("inline", answers_from_inline(full)),
        ("single_column", answers_from_single_column(full)),
    ):
        if len(candidate) > len(key.answers):
            key.answers = candidate
            key.method = name

    return key


# --------------------------------------------------------------------------
# Manual overrides
# --------------------------------------------------------------------------

def load_manual(path: Path) -> dict[int, dict[int, str]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, dict[int, str]] = {}
    for year_key, answers in raw.items():
        try:
            year = int(year_key)
        except ValueError:
            continue
        if not isinstance(answers, dict):
            continue
        out[year] = {
            int(num): str(letter).strip().upper()
            for num, letter in answers.items()
            if str(letter).strip().upper() in {"A", "B", "C", "D"}
        }
    return out


def apply_overrides(key: AnswerKey, manual: dict[int, str]) -> tuple[int, int]:
    """Apply manual answers. Returns (replaced, added)."""
    replaced = added = 0
    for num, letter in manual.items():
        if num in key.answers:
            if key.answers[num] != letter:
                replaced += 1
            key.answers[num] = letter
        else:
            key.answers[num] = letter
            added += 1
    return replaced, added


# --------------------------------------------------------------------------
# Record assembly
# --------------------------------------------------------------------------

def build_records(
    paper: Paper,
    key: AnswerKey,
    base_dir: Path,
    paper_file: str,
    answer_file: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in paper.choices:
        num = item["question_no"]
        letter = key.answers.get(num)
        stem = item["stem"]
        record = {
            "record_id": f"refq-408-{paper.year}-{num:02d}",
            "source": "408_exam",
            "year": paper.year,
            "exam_title": f"{paper.year}年全国硕士研究生入学统一考试计算机学科专业基础综合",
            "question_no": num,
            "subject": item["subject"],
            "question_type": item["question_type"],
            "stem": stem,
            "stem_norm": re.sub(r"\s+", "", stem),
            "options": item["options"],
            "options_complete": item["options_complete"],
            "standard_answer": letter,
            "answer_available": letter is not None,
            "explanation": key.explanations.get(num),
            "answer_method": key.method if letter is not None else None,
            "anchors": {
                "paper_file": paper_file,
                "answer_file": answer_file,
                "question_no": num,
            },
            "trust_level": "A",
            "knowledge_points": [],
        }
        records.append(record)
    return records


def answer_gaps(key: AnswerKey) -> list[int]:
    return [n for n in range(1, 41) if n not in key.answers]


def main() -> int:
    """CLI: build the reference-question dataset and write a gap template."""
    import argparse

    parser = argparse.ArgumentParser(description="Build 408 reference questions.")
    parser.add_argument("--exam-root", required=True, help="path to 408exam/真题")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--years", default="2009-2026")
    parser.add_argument(
        "--manual-dir",
        default=None,
        help="directory holding manual_answers.json (default: --out)",
    )
    args = parser.parse_args()

    exam_root = Path(args.exam_root)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manual_dir = Path(args.manual_dir) if args.manual_dir else out_dir
    manual_dir.mkdir(parents=True, exist_ok=True)

    start, _, end = args.years.partition("-")
    years = range(int(start), int(end or start) + 1)

    manual = load_manual(manual_dir / MANUAL_FILE)
    all_records: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    template: dict[str, dict[str, str]] = {}

    for year in years:
        paper_pdf = exam_root / PAPER_DIR / f"{year}.pdf"
        answer_pdf = exam_root / ANSWER_DIR / f"{year}-answer.pdf"
        if not paper_pdf.exists():
            continue
        paper = parse_paper(paper_pdf, year)
        key = parse_answer_key(answer_pdf, year) if answer_pdf.exists() else AnswerKey(year=year, text_available=False)

        replaced = added = 0
        if year in manual:
            replaced, added = apply_overrides(key, manual[year])

        gaps = answer_gaps(key)
        if gaps:
            template[str(year)] = {str(n): "" for n in gaps}

        records = build_records(
            paper, key, exam_root,
            paper_file=str(paper_pdf.name),
            answer_file=str(answer_pdf.name),
        )
        all_records.extend(records)
        summary.append({
            "year": year,
            "choices": len(paper.choices),
            "comprehensive": len(paper.comprehensive),
            "options_complete": sum(1 for c in paper.choices if c["options_complete"]),
            "answers": len(key.answers),
            "answer_method": key.method,
            "text_available": key.text_available,
            "manual_replaced": replaced,
            "manual_added": added,
            "gaps": gaps,
        })
        print(
            f"{year}: choices={len(paper.choices)} "
            f"answers={len(key.answers)}/40 via {key.method} "
            f"manual(+{added}/~{replaced}) gaps={len(gaps)}"
        )

    (out_dir / "reference_questions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in all_records) + "\n",
        encoding="utf-8",
    )
    (out_dir / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if template:
        (manual_dir / "manual_answers.template.json").write_text(
            json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    total_answers = sum(1 for r in all_records if r["answer_available"])
    print(f"\nrecords={len(all_records)} with_answer={total_answers}")
    if template:
        print(f"gap template written: {manual_dir / 'manual_answers.template.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
