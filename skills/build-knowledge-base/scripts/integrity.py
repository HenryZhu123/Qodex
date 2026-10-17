#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Random contiguous 10% sampling and text-integrity checks."""
from __future__ import annotations

import random
import re
import unicodedata
from pathlib import Path
from typing import Any

from utils import (
    HEADING_RE,
    QUESTION_START_RE,
    cjk_ratio,
    normalize_text,
    write_json,
)

MOJIBAKE_PATTERNS = ["锟斤拷", "烫烫烫", "屯屯屯", "Ã", "Â", "â€", "ï¿½", "\ufffd", "\x00"]


def _join_units(units: list[dict[str, Any]], unit_type: str) -> str:
    parts = []
    for u in units:
        text = u.get("text", "")
        if unit_type == "page":
            parts.append(f"[[PAGE:{u.get('page', u.get('index'))}]]\n{text}")
        elif unit_type == "paragraph":
            parts.append(text)
        else:
            parts.append(text)
    sep = "\n\n" if unit_type in {"paragraph", "block"} else "\n"
    return normalize_text(sep.join(parts))


def sample_contiguous(
    units: list[dict[str, Any]],
    unit_type: str,
    ratio: float = 0.10,
    seed: int = 42,
    windows: int = 1,
    min_units: int = 5,
) -> dict[str, Any]:
    """Select one or more random contiguous windows covering roughly `ratio` of units."""
    total = len(units)
    if total == 0:
        return {
            "unit_type": unit_type,
            "total_units": 0,
            "sample_units": 0,
            "ratio_requested": ratio,
            "ratio_actual": 0.0,
            "windows": [],
            "units": [],
            "text": "",
            "seed": seed,
        }

    ratio = max(0.0, min(1.0, ratio))
    sample_count = max(1, int(round(total * ratio)), min_units)
    sample_count = min(sample_count, total)
    windows = max(1, int(windows))
    rng = random.Random(seed)

    selected_ranges: list[tuple[int, int]] = []
    if windows > 1 and sample_count >= windows:
        per = max(1, sample_count // windows)
        # Greedily choose non-overlapping windows.
        candidates = list(range(0, max(1, total - per + 1)))
        rng.shuffle(candidates)
        for start in candidates:
            end = min(total, start + per)
            if any(not (end <= s or start >= e) for s, e in selected_ranges):
                continue
            selected_ranges.append((start, end))
            if len(selected_ranges) >= windows:
                break
        selected_ranges.sort()
        # Fill any shortfall with one window around the last gap.
        if len(selected_ranges) < windows:
            selected_ranges = selected_ranges[:1] or [(rng.randint(0, total - sample_count), rng.randint(0, total - sample_count) + sample_count)]

    if not selected_ranges:
        size = sample_count
        start = rng.randint(0, total - size)
        selected_ranges = [(start, start + size)]

    selected_units: list[dict[str, Any]] = []
    for start, end in selected_ranges:
        selected_units.extend(units[start:end])

    text = _join_units(selected_units, unit_type)
    ranges = [
        {
            "start_index": s + 1,
            "end_index": e,
            "unit_count": e - s,
        }
        for s, e in selected_ranges
    ]
    return {
        "unit_type": unit_type,
        "total_units": total,
        "sample_units": len(selected_units),
        "ratio_requested": ratio,
        "ratio_actual": len(selected_units) / total if total else 0.0,
        "windows": ranges,
        "units": selected_units,
        "text": text,
        "seed": seed,
        "min_units": min_units,
    }


def _count_mojibake(text: str) -> int:
    return sum(text.count(p) for p in MOJIBAKE_PATTERNS)


def check_integrity(sample: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    text = sample.get("text", "")
    lines = text.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]
    nonspace = re.sub(r"\s+", "", text)

    chars = len(text)
    replacement = text.count("\ufffd")
    replacement_ratio = replacement / max(1, chars)
    control = sum(
        1
        for ch in text
        if unicodedata.category(ch) in {"Cc", "Cf"} and ch not in "\n\r\t"
    )
    control_ratio = control / max(1, chars)
    mojibake_hits = _count_mojibake(text)
    cjk = cjk_ratio(text)
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha()) / max(1, len(nonspace))
    digits = sum(1 for ch in text if ch.isdigit()) / max(1, len(nonspace))
    symbols = sum(
        1
        for ch in text
        if unicodedata.category(ch) in {"So", "Sm", "Sc", "Sk", "Co", "Cn"}
    ) / max(1, len(nonspace))

    empty_line_ratio = 1.0 - (len(non_empty) / max(1, len(lines)))
    avg_line_len = sum(len(ln) for ln in lines) / max(1, len(lines))
    max_line_len = max((len(ln) for ln in lines), default=0)
    repeated = 0
    seen = set()
    for ln in non_empty:
        s = ln.strip()
        if s in seen:
            repeated += 1
        else:
            seen.add(s)
    repeated_line_ratio = repeated / max(1, len(non_empty))

    heading_count = sum(1 for ln in lines if HEADING_RE.match(ln.strip()))
    question_count = sum(1 for ln in lines if QUESTION_START_RE.match(ln))
    code_lines = sum(
        1
        for ln in lines
        if ln.startswith(("    ", "\t")) or any(tok in ln for tok in ("{", "}", "();", "def ", "class ", "#include"))
    )
    code_line_ratio = code_lines / max(1, len(lines))

    page_density = None
    if sample.get("unit_type") == "page":
        page_density = sum(len(u.get("text", "")) for u in sample.get("units", [])) / max(
            1, len(sample.get("units", []))
        )

    reasons: list[str] = []
    actions: list[str] = []
    verdict = "pass"

    def fail(reason: str, action: str) -> None:
        nonlocal verdict
        verdict = "fail"
        reasons.append(reason)
        actions.append(action)

    def warn(reason: str, action: str) -> None:
        nonlocal verdict
        if verdict != "fail":
            verdict = "warn"
        reasons.append(reason)
        actions.append(action)

    if chars < 10:
        fail("sample text is nearly empty", "check the parser and source file; do not ingest")
    elif chars < 100:
        warn(f"sample is short ({chars} chars)", "inspect the sample manually; the 10% window may be too small")
    if replacement_ratio > 0.005:
        fail(f"replacement-character ratio is high ({replacement_ratio:.3%})", "fix encoding or re-parse")
    if mojibake_hits >= 5:
        fail(f"multiple mojibake patterns detected ({mojibake_hits})", "fix encoding or OCR; do not ingest")
    if control_ratio > 0.02:
        fail(f"control-character ratio is high ({control_ratio:.3%})", "clean or re-parse the source")
    if page_density is not None and page_density < 80:
        warn(f"low average text density per page ({page_density:.0f} chars/page)", "consider OCR or verify scanned pages")

    if replacement_ratio > 0.001 and verdict != "fail":
        warn(f"replacement characters present ({replacement_ratio:.3%})", "inspect the sample manually")
    if mojibake_hits > 0 and verdict != "fail":
        warn(f"possible mojibake patterns detected ({mojibake_hits})", "inspect the sample manually")
    if symbols > 0.35:
        warn(f"symbol ratio is high ({symbols:.1%})", "check formulas/tables or extraction noise")
    if empty_line_ratio > 0.55:
        warn(f"empty-line ratio is high ({empty_line_ratio:.1%})", "check for fragmented PDF extraction")
    if avg_line_len < 10 and len(lines) > 20:
        warn(f"average line length is very short ({avg_line_len:.1f})", "check for one-word-per-line extraction or OCR noise")
    if repeated_line_ratio > 0.25:
        warn(f"repeated-line ratio is high ({repeated_line_ratio:.1%})", "remove repeated headers/footers before chunking")
    if cjk < 0.02 and doc.get("language") == "zh":
        warn(f"CJK ratio is low ({cjk:.1%}) for a Chinese document", "verify encoding and language detection")

    if verdict == "pass":
        actions.append("proceed to chunk-plan selection")
    elif verdict == "warn":
        actions.append("proceed with a conservative chunk plan and manual spot-check")
    else:
        actions.append("stop; repair parsing/encoding/OCR before chunking")

    metrics = {
        "chars": chars,
        "lines": len(lines),
        "non_empty_lines": len(non_empty),
        "replacement_chars": replacement,
        "replacement_ratio": round(replacement_ratio, 6),
        "control_chars": control,
        "control_ratio": round(control_ratio, 6),
        "mojibake_hits": mojibake_hits,
        "cjk_ratio": round(cjk, 4),
        "latin_ratio": round(latin, 4),
        "digit_ratio": round(digits, 4),
        "symbol_ratio": round(symbols, 4),
        "empty_line_ratio": round(empty_line_ratio, 4),
        "avg_line_len": round(avg_line_len, 2),
        "max_line_len": max_line_len,
        "repeated_line_ratio": round(repeated_line_ratio, 4),
        "heading_count": heading_count,
        "question_count": question_count,
        "code_line_ratio": round(code_line_ratio, 4),
        "page_density": round(page_density, 1) if page_density is not None else None,
    }
    return {
        "doc_id": doc.get("doc_id"),
        "source_path": doc.get("source_path"),
        "title": doc.get("title"),
        "unit_type": sample.get("unit_type"),
        "sample": {
            "seed": sample.get("seed"),
            "total_units": sample.get("total_units"),
            "sample_units": sample.get("sample_units"),
            "ratio_requested": sample.get("ratio_requested"),
            "ratio_actual": round(sample.get("ratio_actual", 0.0), 4),
            "min_units": sample.get("min_units"),
            "windows": sample.get("windows", []),
        },
        "metrics": metrics,
        "verdict": verdict,
        "reasons": reasons,
        "recommended_actions": actions,
    }


def write_integrity_outputs(
    doc: dict[str, Any],
    sample: dict[str, Any],
    report: dict[str, Any],
    out_dir: str | Path,
) -> dict[str, str]:
    out_dir = Path(out_dir)
    sample_dir = out_dir / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    doc_id = doc["doc_id"]
    sample_path = sample_dir / f"{doc_id}_sample.txt"
    integrity_path = sample_dir / f"{doc_id}_integrity.json"
    sample_path.write_text(sample.get("text", ""), encoding="utf-8")
    write_json(integrity_path, report)
    return {"sample_path": str(sample_path), "integrity_json": str(integrity_path)}


def render_integrity_report(docs: list[dict[str, Any]], reports: list[dict[str, Any]], out_dir: str | Path) -> str:
    out_dir = Path(out_dir)
    lines = ["# Text integrity report", ""]
    lines.append(f"- documents: {len(reports)}")
    lines.append(f"- sample ratio: 10% (random contiguous units by default)")
    lines.append("")
    for doc, report in zip(docs, reports):
        m = report["metrics"]
        lines.append(f"## {doc.get('title') or doc.get('doc_id')}")
        lines.append("")
        lines.append(f"- source: `{doc.get('source_path')}`")
        lines.append(f"- format: `{doc.get('format')}` | units: `{doc.get('unit_type')}` | language: `{doc.get('language')}`")
        s = report["sample"]
        lines.append(
            f"- sample: {s['sample_units']}/{s['total_units']} units "
            f"({s['ratio_actual']:.1%}), windows={s['windows']}, seed={s['seed']}"
        )
        lines.append(f"- verdict: **{report['verdict'].upper()}**")
        if report["reasons"]:
            lines.append("- reasons:")
            for reason in report["reasons"]:
                lines.append(f"  - {reason}")
        lines.append("")
        lines.append("| metric | value |")
        lines.append("|---|---|")
        for key in (
            "chars",
            "lines",
            "replacement_ratio",
            "control_ratio",
            "mojibake_hits",
            "cjk_ratio",
            "symbol_ratio",
            "empty_line_ratio",
            "avg_line_len",
            "repeated_line_ratio",
            "heading_count",
            "question_count",
            "code_line_ratio",
            "page_density",
        ):
            lines.append(f"| {key} | {m.get(key)} |")
        lines.append("")
        preview = sample_text_preview(doc, out_dir)
        if preview:
            lines.append("Sample preview:")
            lines.append("")
            lines.append("```text")
            lines.append(preview)
            lines.append("```")
            lines.append("")
        lines.append("Recommended actions:")
        for action in report["recommended_actions"]:
            lines.append(f"- {action}")
        lines.append("")
    content = "\n".join(lines).strip() + "\n"
    (out_dir / "integrity_report.md").write_text(content, encoding="utf-8")
    return content


def sample_text_preview(doc: dict[str, Any], out_dir: str | Path, limit: int = 1500) -> str:
    path = Path(out_dir) / "samples" / f"{doc['doc_id']}_sample.txt"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated]"
