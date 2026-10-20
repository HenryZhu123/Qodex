#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared utilities for the build-knowledge-base skill."""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".log"}
SUPPORTED_HTML_EXTENSIONS = {".html", ".htm"}
SUPPORTED_DOC_EXTENSIONS = {".docx", ".doc"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = (
    SUPPORTED_TEXT_EXTENSIONS
    | SUPPORTED_HTML_EXTENSIONS
    | SUPPORTED_DOC_EXTENSIONS
    | SUPPORTED_PDF_EXTENSIONS
)

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
HEADING_RE = re.compile(
    r"^(?:"
    r"第\s*[0-9一二三四五六七八九十百千]+\s*[章节]"
    r"|Chapter\s+\d+"
    r"|Appendix\s+[A-Z0-9]"
    r"|附录\s*[A-Z0-9]?"
    r"|[0-9]+(?:\.[0-9]+)*\s+\S"
    r"|[一二三四五六七八九十]+\s*[、.．]"
    r"|（[一二三四五六七八九十]+）"
    r"|#{1,6}\s+\S"
    r")",
    re.IGNORECASE,
)
QUESTION_START_RE = re.compile(
    r"^\s*(?:"
    r"[0-9]{1,3}\s*[.、)]"
    r"|（[0-9]{1,3}）"
    r"|第\s*[0-9一二三四五六七八九十]+\s*题"
    r")"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def make_doc_id(source_path: str | Path, source_hash: str) -> str:
    seed = f"{Path(source_path).resolve()}|{source_hash}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def sanitize_text(text: str) -> str:
    """Replace lone surrogates and other invalid Unicode with safe characters."""
    if not isinstance(text, str):
        return text
    return text.encode("utf-8", "replace").decode("utf-8", "replace")


def sanitize_obj(obj: Any) -> Any:
    """Recursively sanitize strings in JSON-like objects."""
    if isinstance(obj, str):
        return sanitize_text(obj)
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(sanitize_obj(x) for x in obj)
    if isinstance(obj, dict):
        return {sanitize_text(k): sanitize_obj(v) for k, v in obj.items()}
    return obj


def normalize_text(text: str) -> str:
    """Normalize line endings and remove invisible characters without flattening code indentation."""
    if not text:
        return ""
    text = sanitize_text(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x0c", "\n").replace("\x0b", "\n").replace("\x00", "")
    text = text.replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "")
    text = text.replace("\u00a0", " ")
    # trim trailing horizontal whitespace per line
    text = re.sub(r"[ \t]+\n", "\n", text)
    # collapse runs of blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def safe_slug(name: str, max_len: int = 80) -> str:
    slug = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "_", name).strip(" ._")
    slug = re.sub(r"\s+", " ", slug)
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip(" ._")
    return slug or "document"


def cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    nonspace = re.sub(r"\s+", "", text)
    if not nonspace:
        return 0.0
    return len(CJK_RE.findall(nonspace)) / len(nonspace)


def detect_language(text: str) -> str:
    ratio = cjk_ratio(text)
    if ratio >= 0.15:
        return "zh"
    if ratio <= 0.02:
        return "en"
    return "mixed"


def _tokenize_cjk_run(run: str) -> list[str]:
    """Character unigrams + bigrams are a dependency-free fallback for Chinese FTS."""
    if not run:
        return []
    tokens = list(run)
    if len(run) >= 2:
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def tokenize_for_fts(text: str) -> str:
    """Tokenize text for SQLite FTS5.

    Prefer jieba when available; otherwise use CJK unigrams + bigrams and ASCII words.
    The result is a space-separated token string stored in the FTS table.
    Query strings must use the same function.
    """
    if not text:
        return ""
    try:
        import jieba  # type: ignore

        tokens: list[str] = []
        for tok in jieba.cut_for_search(text):
            tok = tok.strip().lower()
            if not tok:
                continue
            if CJK_RE.search(tok) or tok.isalnum():
                tokens.append(tok)
        return " ".join(tokens)
    except Exception:
        pass

    tokens: list[str] = []
    pos = 0
    for match in re.finditer(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+|[A-Za-z0-9_]+", text):
        if match.start() > pos:
            gap = text[pos:match.start()]
            tokens.extend(ASCII_WORD_RE.findall(gap.lower()))
        chunk = match.group(0)
        if CJK_RE.search(chunk):
            tokens.extend(_tokenize_cjk_run(chunk))
        else:
            tokens.append(chunk.lower())
        pos = match.end()
    if pos < len(text):
        tokens.extend(ASCII_WORD_RE.findall(text[pos:].lower()))
    return " ".join(tokens)


def split_sentences(text: str) -> list[str]:
    """Split text into sentence-like units while keeping the original punctuation."""
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def is_heading_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 120:
        return False
    if s.endswith(("。", "．", ".", "？", "?", "！", "!", "；", ";", "，", ",")):
        return False
    # Code fragments and equations are not headings.
    if any(ch in s for ch in "={}[]"):
        return False
    return bool(HEADING_RE.match(s))


def is_question_start(line: str) -> bool:
    return bool(QUESTION_START_RE.match(line))


def read_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sanitize_obj(data), f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_jsonl(path: str | Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(sanitize_obj(row), ensure_ascii=False) + "\n")
            count += 1
    return count


def iter_input_files(input_path: str | Path) -> list[Path]:
    root = Path(input_path)
    if root.is_file():
        return [root] if root.suffix.lower() in SUPPORTED_EXTENSIONS else []
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(p)
    return files


def format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def char_class_ratio(text: str, predicate) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if predicate(ch)) / len(text)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def relative_posix(path: str | Path, root: str | Path) -> str:
    try:
        return Path(os.path.relpath(Path(path), Path(root))).as_posix()
    except ValueError:
        return Path(path).as_posix()


def normalize_heading(text: str) -> str:
    s = unicodedata.normalize("NFC", text)
    s = re.sub(r"\s+", " ", s).strip()
    # "第1 章" -> "第1章"; "Chapter 1" keeps its space.
    s = re.sub(r"(第\s*[0-9一二三四五六七八九十百千]+)\s+([章节])", r"\1\2", s)
    return s
