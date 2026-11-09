#!/usr/bin/env python3
"""Text cleaning for knowledge-base ingestion (P2).

Fixes two concrete defects measured on the 数据结构（C语言版）book:

  1. A running footer watermark rendered as single characters across line breaks
     (``（ / C / （ / 第 / 2 / 版 / ） / ——``) repeated on every page.
  2. Vertical running headers and figure labels emitted one character per line.

Default mode only reports what it would change. Pass ``--write`` to emit cleaned
parsed JSON next to the input, leaving the original untouched.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

# Fragmented watermark: allow newlines/spaces between every character.
_WM_CHARS = ["（", "C", "（", "第", "2", "版", "）", "——"]
WATERMARK_RE = re.compile(
    r"\s*".join(re.escape(ch) for ch in _WM_CHARS) + r"\s*",
    re.S,
)
# A run of punctuation-only lines left behind after character splitting.
NOISE_LINE_RE = re.compile(r"^[\s—\-－_=·.,，、:：;；()（）\[\]【】]*$")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
CODE_CHARS = set("{}();=<>")


def split_lines(text: str) -> list[str]:
    return text.split("\n")


def is_single_char(line: str) -> bool:
    return len(line.strip()) == 1


def merge_char_runs(lines: list[str], max_join: int = 16) -> list[str]:
    """Join runs of one-character lines produced by vertical layout.

    Only merges when the joined text is CJK-ish and contains no code punctuation,
    so code blocks and tables keep their shape.
    """
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if not run:
            return
        joined = "".join(item.strip() for item in run)
        if (
            2 <= len(joined) <= max_join
            and CJK_RE.search(joined)
            and not (CODE_CHARS & set(joined))
        ):
            out.append(joined)
        else:
            out.extend(run)
        run.clear()

    for line in lines:
        if is_single_char(line):
            run.append(line)
        else:
            flush()
            out.append(line)
    flush()
    return out


def is_removable_overlay(line: str) -> bool:
    """Only running headers/footers qualify, never code or table rows.

    Rejects anything containing latin letters, digits or code punctuation, so
    lines like ``//for`` or ``return OK;`` that legitimately repeat across
    algorithm listings survive.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 12:
        return False
    if looks_structured(stripped):
        return False
    if re.search(r"[A-Za-z0-9]", stripped):
        return False
    return bool(CJK_RE.search(stripped)) or bool(NOISE_LINE_RE.match(stripped))


def drop_repeated_lines(units: list[dict], min_repeat: int = 12, max_len: int = 24) -> tuple[list[dict], list[str]]:
    """Remove short lines that repeat across many pages (running headers/footers)."""
    counter: Counter[str] = Counter()
    for unit in units:
        for line in set(split_lines(unit["text"])):
            key = line.strip()
            if 0 < len(key) <= max_len and is_removable_overlay(key):
                counter[key] += 1
    repeated = {text for text, n in counter.items() if n >= min_repeat}
    if not repeated:
        return units, []
    cleaned: list[dict] = []
    for unit in units:
        kept = [ln for ln in split_lines(unit["text"]) if ln.strip() not in repeated]
        cleaned.append({**unit, "text": "\n".join(kept)})
    return cleaned, sorted(repeated)[:20]


def looks_structured(line: str) -> bool:
    """True for code / tables / lists whose line breaks must be preserved."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("#define", "typedef", "void ", "int ", "for(", "while", "if(")):
        return True
    if line[:2].isspace() and len(stripped) > 1:
        return True
    code_marks = sum(stripped.count(ch) for ch in "{};")
    ascii_ops = sum(stripped.count(ch) for ch in "=<>")
    cjk = len(CJK_RE.findall(stripped))
    return (code_marks >= 1 or ascii_ops >= 2) and cjk <= 3


def normalize_newlines(text: str) -> str:
    """Merge wrapped prose lines; keep code, tables and list items intact."""
    lines = [ln.rstrip() for ln in split_lines(text)]
    out: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            out.append("".join(buffer))
            buffer.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            if out and out[-1] != "":
                out.append("")
            continue
        if NOISE_LINE_RE.match(stripped) and len(stripped) <= 3:
            continue
        if looks_structured(line):
            flush()
            if out and out[-1] != "":
                pass
            out.append(line.rstrip())
            continue
        buffer.append(stripped)
    flush()
    return "\n".join(out).strip()


def clean_text(text: str) -> str:
    text = WATERMARK_RE.sub("\n", text)
    text = "\n".join(merge_char_runs(split_lines(text)))
    return normalize_newlines(text)


# ----------------------------- OCR repairs -----------------------------
#
# Only shape-unique substitutions belong here. "千" appears 519 times in the
# corpus but is a wrong character only in a few collocations, so a blanket
# replacement would corrupt 数千个 / 以千计. Every rule below is a fixed
# collocation or a character that never occurs legitimately in prose.

COLLOCATION_FIXES: list[tuple[str, str]] = [
    (r"对千", "对于"),
    (r"由千", "由于"),
    (r"关千", "关于"),
    (r"至千", "至于"),
    (r"鉴千", "鉴于"),
    (r"千是", "于是"),
    (r"千此", "于此"),
    (r"千其", "于其"),
    (r"巳经", "已经"),
    (r"巳有", "已有"),
    (r"巳是", "已是"),
    (r"而巳", "而已"),
    (r"阙值", "阈值"),
    (r"阔值", "阈值"),
    (r"橾", "操"),
]

# Characters that are pure noise in a Chinese textbook body.
NOISE_CHARS = re.compile(r"[｀｢｣]")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
HTML_ENTITY = re.compile(r"&(lt|gt|amp|nbsp|quot|#\d{1,4});")
ENTITY_MAP = {"lt": "<", "gt": ">", "amp": "&", "nbsp": " ", "quot": '"'}
BULLET_RUN = re.compile(r"[•·]{2,}")


def _unescape_entity(match: re.Match[str]) -> str:
    key = match.group(1)
    if key.startswith("#"):
        try:
            return chr(int(key[1:]))
        except ValueError:
            return match.group(0)
    return ENTITY_MAP.get(key, match.group(0))


def repair_ocr(text: str) -> dict:
    """Apply the safe repairs and report what changed.

    Returns {"text": repaired, "counts": {rule: n}}. The caller decides whether to
    keep the repaired text; this function never touches the database.
    """
    counts: dict[str, int] = {}
    out = text or ""

    for pattern, replacement in COLLOCATION_FIXES:
        out, n = re.subn(pattern, replacement, out)
        if n:
            counts[f"{pattern}→{replacement}"] = n

    out, n = NOISE_CHARS.subn("", out)
    if n:
        counts["noise_chars"] = n

    out, n = HTML_COMMENT.subn("", out)
    if n:
        counts["html_comment"] = n

    out, n = HTML_ENTITY.subn(_unescape_entity, out)
    if n:
        counts["html_entity"] = n

    out, n = BULLET_RUN.subn("", out)
    if n:
        counts["bullet_run"] = n

    return {"text": out, "counts": counts}


def stats(units: list[dict]) -> dict:
    lines = [ln for unit in units for ln in split_lines(unit["text"])]
    nonempty = [ln for ln in lines if ln.strip()]
    single = sum(1 for ln in nonempty if len(ln.strip()) == 1)
    return {
        "units": len(units),
        "nonempty_lines": len(nonempty),
        "single_char_lines": single,
        "single_char_ratio": round(single / len(nonempty), 4) if nonempty else 0.0,
        "watermark_units": sum(
            1 for unit in units if WATERMARK_RE.search(unit["text"])
        ),
        "units_with_5plus_newlines": sum(
            1 for unit in units if unit["text"].count("\n") >= 5
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parsed", required=True, help="path to parsed/<doc>.json")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--min-repeat", type=int, default=12)
    args = parser.parse_args()

    src = Path(args.parsed)
    doc = json.loads(src.read_text(encoding="utf-8"))
    units = doc["units"]
    before = stats(units)

    cleaned_units = [{**unit, "text": clean_text(unit["text"])} for unit in units]
    cleaned_units, repeated = drop_repeated_lines(
        cleaned_units, min_repeat=args.min_repeat
    )
    after = stats(cleaned_units)

    report = {
        "input": str(src),
        "before": before,
        "after": after,
        "removed_repeated_lines_sample": repeated,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.write:
        out_dir = src.parent.parent / "parsed_clean"
        out_dir.mkdir(parents=True, exist_ok=True)
        doc["units"] = cleaned_units
        doc["cleaned_at"] = "textclean-v1"
        (out_dir / src.name).write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {out_dir / src.name}")


if __name__ == "__main__":
    main()
