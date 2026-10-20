#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chunk-plan selection and structure-aware chunking."""
from __future__ import annotations

import re
from typing import Any

from utils import (
    HEADING_RE,
    QUESTION_START_RE,
    is_heading_line,
    is_question_start,
    normalize_heading,
    normalize_text,
    sha256_text,
    split_sentences,
)

PAGE_MARKER_RE = re.compile(r"^\[\[PAGE:(\d+)\]\]$")


def choose_chunk_plan(
    integrity_report: dict[str, Any],
    doc: dict[str, Any],
    forced_mode: str = "auto",
) -> dict[str, Any]:
    m = integrity_report.get("metrics", {})
    verdict = integrity_report.get("verdict", "warn")
    language = doc.get("language", "zh")
    doc_meta = doc.get("metadata", {}) or {}
    content_start_page = doc_meta.get("content_start_page")
    content_end_page = doc_meta.get("content_end_page")

    # Integrity is judged on the 10% sample. Structure detection additionally
    # scans the whole document's line metadata (cheap) so a sample that happens
    # to miss headings does not force a flat paragraph plan on a textbook.
    full_lines = doc.get("text", "").splitlines()
    full_heading_count = sum(1 for line in full_lines if is_heading_line(line))
    full_question_count = sum(1 for line in full_lines if is_question_start(line))
    full_code_lines = sum(
        1
        for line in full_lines
        if line.startswith(("    ", "\t")) or any(tok in line for tok in ("{", "}", "();", "def ", "class ", "#include"))
    )
    code_line_ratio = full_code_lines / max(1, len(full_lines)) if full_lines else 0.0
    lines = max(1, len(full_lines) or m.get("lines", 1))
    heading_count = max(m.get("heading_count", 0), full_heading_count)
    question_count = max(m.get("question_count", 0), full_question_count)

    if verdict == "fail":
        return {
            "doc_id": doc.get("doc_id"),
            "title": doc.get("title"),
            "mode": "blocked",
            "blocked": True,
            "target_chars": 0,
            "max_chars": 0,
            "min_chars": 0,
            "overlap_chars": 0,
            "preserve_pages": True,
            "content_start_page": content_start_page,
            "content_end_page": content_end_page,
            "full_heading_count": full_heading_count,
            "full_question_count": full_question_count,
            "question_signal": question_signal,
            "question_ratio": round(question_ratio, 4),
            "exam_heading_count": exam_heading_count,
            "full_code_line_ratio": round(code_line_ratio, 4),
            "rationale": [
                "integrity verdict is fail",
                "do not chunk until parsing/encoding/OCR is repaired",
            ],
            "sample_metrics": m,
        }

    option_marker_count = sum(
        1 for line in full_lines if re.match(r"^\s*[A-DＡ-Ｄ][.、)]\s*", line)
    )
    answer_marker_count = sum(
        1 for line in full_lines if any(k in line for k in ("答案", "解析", "参考答案", "Answer"))
    )
    blank_marker_count = sum(
        1 for line in full_lines if "（ ）" in line or "( )" in line or "____" in line
    )
    exam_heading_count = sum(
        1
        for line in full_lines
        if re.search(r"单项选择题|多项选择题|选择题|简答题|判断题|计算题|名词解释|论述题|案例分析|填空题", line)
    )
    question_signal = question_count + option_marker_count + answer_marker_count + blank_marker_count
    question_ratio = question_count / lines

    is_question_doc = (
        (question_count >= 8 and question_ratio >= 0.10)
        or (exam_heading_count >= 1 and question_count >= 3 and question_ratio >= 0.15)
        or (question_count >= 5 and question_signal >= 10 and question_ratio >= 0.10)
    )

    if is_question_doc:
        mode = "question"
    elif code_line_ratio > 0.15:
        mode = "code"
    elif heading_count >= 3:
        mode = "hierarchical"
    else:
        mode = "paragraph"

    if forced_mode in {"hierarchical", "paragraph", "question", "code"}:
        mode = forced_mode

    if language == "zh":
        target = 700
    elif language == "en":
        target = 1200
    else:
        target = 900

    if verdict == "warn":
        target = int(target * 0.8)

    if mode == "question":
        target = 500
        max_chars = 1500
        min_chars = 120
        overlap = 0
    elif mode == "code":
        target = 1200
        max_chars = 2400
        min_chars = 200
        overlap = 0
    else:
        max_chars = int(target * 2.2)
        min_chars = int(target * 0.3)
        overlap = 100 if language != "en" else 150

    rationale = [
        f"integrity={verdict} (based on 10% sample)",
        f"language={language}",
        f"sample headings={m.get('heading_count', 0)}, sample questions={m.get('question_count', 0)}",
        f"full-doc headings={full_heading_count}, questions={full_question_count}, "
        f"question_ratio={question_ratio:.2%}, question_signal={question_signal}, "
        f"exam_headings={exam_heading_count}, code_ratio={code_line_ratio:.2%}",
        f"selected mode={mode}" + (" (forced by user)" if forced_mode in {"hierarchical", "paragraph", "question", "code"} else ""),
    ]
    if verdict == "warn":
        rationale.append("integrity warning: use a smaller target and inspect result chunks")
    if mode == "question":
        rationale.append("question-like line density suggests question-level chunking")
    if mode == "code":
        rationale.append("indented/code-like lines suggest preserving code blocks")
    if mode == "hierarchical":
        rationale.append("headings detected; preserve heading path in metadata")
    if mode == "paragraph":
        rationale.append("no strong structure signal; use paragraph packing")

    return {
        "doc_id": doc.get("doc_id"),
        "title": doc.get("title"),
        "mode": mode,
        "blocked": False,
        "target_chars": target,
        "max_chars": max_chars,
        "min_chars": min_chars,
        "overlap_chars": overlap,
        "preserve_pages": True,
        "content_start_page": content_start_page,
        "content_end_page": content_end_page,
        "full_heading_count": full_heading_count,
        "full_question_count": full_question_count,
        "question_signal": question_signal,
        "question_ratio": round(question_ratio, 4),
        "exam_heading_count": exam_heading_count,
        "full_code_line_ratio": round(code_line_ratio, 4),
        "rationale": rationale,
        "sample_metrics": m,
    }


# ----------------------------- paragraph preparation -----------------------------

def prepare_paragraphs(text: str, detect_headings: bool = True) -> list[dict[str, Any]]:
    """Split text into paragraphs, tracking PDF page numbers and heading kind."""
    paragraphs: list[dict[str, Any]] = []
    current: list[str] = []
    current_pages: list[int] = []
    current_page: int | None = None

    def flush() -> None:
        nonlocal current, current_pages
        if not current:
            return
        body = normalize_text("\n".join(current))
        if body:
            paragraphs.append({
                "text": body,
                "page_start": min(current_pages) if current_pages else None,
                "page_end": max(current_pages) if current_pages else None,
                "kind": "heading" if is_heading_line(body.splitlines()[0]) else "paragraph",
            })
        current = []
        current_pages = []

    for raw_line in text.splitlines():
        marker = PAGE_MARKER_RE.match(raw_line.strip())
        if marker:
            current_page = int(marker.group(1))
            continue
        if not raw_line.strip():
            flush()
            continue
        # A heading always starts a new paragraph.
        if detect_headings and is_heading_line(raw_line) and current:
            flush()
        current.append(raw_line)
        if current_page is not None:
            current_pages.append(current_page)
        if detect_headings and is_heading_line(raw_line):
            flush()

    flush()
    return paragraphs


def detect_heading_level(text: str) -> int | None:
    s = normalize_heading(text)
    if not s or len(s) > 120:
        return None
    if s.startswith("#"):
        level = 0
        while level < len(s) and s[level] == "#":
            level += 1
        return min(max(level, 1), 6)
    if re.match(r"^第\s*[0-9一二三四五六七八九十百千]+\s*[章节]", s):
        return 1
    if re.match(r"^(Chapter|Appendix)\s+", s, re.IGNORECASE):
        return 1
    if re.match(r"^附录\s*[A-Z0-9]?", s):
        return 1
    m = re.match(r"^([0-9]+(?:\.[0-9]+)*)\s+\S", s)
    if m:
        return m.group(1).count(".") + 1
    if re.match(r"^[一二三四五六七八九十]+\s*[、.．]", s):
        return 2
    if re.match(r"^（[一二三四五六七八九十]+）", s):
        return 3
    return None


def _strip_heading_markup(text: str) -> str:
    return normalize_heading(re.sub(r"^#{1,6}\s*", "", text))


def build_sections(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    current: dict[str, Any] | None = None

    def new_section() -> dict[str, Any]:
        return {"path": [t for _, t in stack], "level": stack[-1][0] if stack else 0, "paragraphs": []}

    for para in paragraphs:
        level = detect_heading_level(para["text"].splitlines()[0]) if para.get("kind") == "heading" else None
        if level is not None:
            title = _strip_heading_markup(para["text"].splitlines()[0])
            # "1. 方便性" inside a chapter is usually an enumerated point, not a new chapter.
            if level == 1 and stack and len(title) < 25 and not re.match(
                r"^(第|Chapter|Appendix|附录)", title, re.IGNORECASE
            ):
                if current is None:
                    current = new_section()
                    sections.append(current)
                current["paragraphs"].append(para)
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            current = new_section()
            sections.append(current)
            # Include the heading text in the section content for retrieval context.
            current["paragraphs"].append({**para, "text": title, "kind": "heading"})
            continue
        if current is None:
            current = new_section()
            sections.append(current)
        current["paragraphs"].append(para)
    return sections


# ----------------------------- packing -----------------------------

def _split_large_paragraph(para: dict[str, Any], max_chars: int) -> list[dict[str, Any]]:
    text = para["text"]
    if len(text) <= max_chars:
        return [para]
    sentences = split_sentences(text)
    if not sentences:
        sentences = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
    out: list[dict[str, Any]] = []
    buf: list[str] = []
    size = 0
    for sent in sentences:
        if buf and size + len(sent) > max_chars:
            out.append({**para, "text": "\n".join(buf)})
            buf = []
            size = 0
        buf.append(sent)
        size += len(sent) + 1
    if buf:
        out.append({**para, "text": "\n".join(buf)})
    return out


def _pack_paragraphs(
    paragraphs: list[dict[str, Any]],
    plan: dict[str, Any],
    heading_path: list[str],
    chunk_type: str,
    force_group: bool = False,
) -> list[dict[str, Any]]:
    target = plan["target_chars"]
    max_chars = plan["max_chars"]
    min_chars = plan["min_chars"]
    overlap = plan["overlap_chars"]

    expanded: list[dict[str, Any]] = []
    for para in paragraphs:
        expanded.extend(_split_large_paragraph(para, max_chars))

    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    cur_len = 0

    def emit() -> None:
        nonlocal current, cur_len
        if not current:
            return
        content = normalize_text("\n\n".join(p["text"] for p in current))
        if not content:
            current = []
            cur_len = 0
            return
        pages = [p.get("page_start") for p in current if p.get("page_start") is not None]
        pages_end = [p.get("page_end") for p in current if p.get("page_end") is not None]
        chunks.append({
            "content": content,
            "char_count": len(content),
            "chunk_type": chunk_type,
            "heading_path": list(heading_path),
            "page_start": min(pages) if pages else None,
            "page_end": max(pages_end) if pages_end else None,
        })
        # overlap: keep the last paragraph if it is not huge
        if overlap > 0 and current and len(current[-1]["text"]) <= overlap * 3:
            current = [current[-1]]
            cur_len = len(current[0]["text"])
        else:
            current = []
            cur_len = 0

    for para in expanded:
        plen = len(para["text"])
        if current and cur_len + plen + 2 > max_chars:
            emit()
        current.append(para)
        cur_len += plen + 2
        if force_group:
            continue
        if cur_len >= target and len(current) >= 2:
            emit()

    if current:
        emit()
    return chunks


# ----------------------------- modes -----------------------------

def chunk_hierarchical(paragraphs: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    sections = build_sections(paragraphs)
    if not sections:
        return chunk_paragraphs(paragraphs, plan)
    chunks: list[dict[str, Any]] = []
    for section in sections:
        chunks.extend(_pack_paragraphs(section["paragraphs"], plan, section["path"], "hierarchical"))
    return chunks


def chunk_paragraphs(paragraphs: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    return _pack_paragraphs(paragraphs, plan, [], "paragraph")


def _split_question_paragraphs(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split paragraphs at question-start lines even when the source has no blank line."""
    out: list[dict[str, Any]] = []
    for para in paragraphs:
        buf: list[str] = []
        for line in para["text"].splitlines():
            if is_question_start(line) and buf:
                text = "\n".join(buf).strip()
                if text:
                    out.append({**para, "text": text})
                buf = []
            buf.append(line)
        if buf:
            text = "\n".join(buf).strip()
            if text:
                out.append({**para, "text": text})
    return out


def chunk_questions(paragraphs: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    paragraphs = _split_question_paragraphs(paragraphs)
    groups: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    current: dict[str, Any] | None = None

    def start_group(path: list[str]) -> dict[str, Any]:
        return {"path": path, "paragraphs": []}

    for para in paragraphs:
        first_line = para["text"].splitlines()[0]
        level = detect_heading_level(first_line) if para.get("kind") == "heading" else None
        if level is not None:
            title = _strip_heading_markup(first_line)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            # Heading starts a new group.
            if current and current["paragraphs"]:
                groups.append(current)
            current = start_group([t for _, t in stack])
            current["paragraphs"].append({**para, "text": title, "kind": "heading"})
            continue
        if is_question_start(first_line):
            if current and current["paragraphs"]:
                groups.append(current)
            current = start_group([t for _, t in stack])
        if current is None:
            current = start_group([t for _, t in stack])
        current["paragraphs"].append(para)

    if current and current["paragraphs"]:
        groups.append(current)

    if not groups:
        return chunk_paragraphs(paragraphs, plan)

    chunks: list[dict[str, Any]] = []
    for group in groups:
        chunks.extend(_pack_paragraphs(group["paragraphs"], plan, group["path"], "question", force_group=True))
    return chunks


def chunk_code(paragraphs: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    return _pack_paragraphs(paragraphs, plan, [], "code", force_group=False)


def chunk_document(
    doc: dict[str, Any],
    plan: dict[str, Any],
    include_front_matter: bool = False,
) -> list[dict[str, Any]]:
    if plan.get("blocked"):
        raise ValueError("chunk plan is blocked by integrity failure")
    text = doc.get("text", "")
    mode = plan.get("mode", "paragraph")
    paragraphs = prepare_paragraphs(text, detect_headings=(mode != "code"))
    if not paragraphs:
        return []

    if not include_front_matter:
        meta = doc.get("metadata", {}) or {}
        start = meta.get("content_start_page")
        end = meta.get("content_end_page")
        if start:
            filtered = []
            for para in paragraphs:
                ps, pe = para.get("page_start"), para.get("page_end")
                if ps is None or pe is None:
                    filtered.append(para)
                    continue
                if pe < start:
                    continue
                if end and ps > end:
                    continue
                filtered.append(para)
            paragraphs = filtered
            if not paragraphs:
                return []
    if mode == "hierarchical":
        raw_chunks = chunk_hierarchical(paragraphs, plan)
    elif mode == "question":
        raw_chunks = chunk_questions(paragraphs, plan)
    elif mode == "code":
        raw_chunks = chunk_code(paragraphs, plan)
    else:
        raw_chunks = chunk_paragraphs(paragraphs, plan)

    out: list[dict[str, Any]] = []
    for ch in raw_chunks:
        content = ch["content"].strip()
        if not content:
            continue
        # Drop heading-only fragments (e.g. a chapter title with no body).
        if len(content) < plan.get("min_chars", 100):
            lines = [ln for ln in content.splitlines() if ln.strip()]
            if lines and all(is_heading_line(ln) for ln in lines):
                continue
        i = len(out) + 1
        out.append({
            "chunk_id": f"{doc['doc_id']}:{i:05d}",
            "doc_id": doc["doc_id"],
            "chunk_index": i,
            "content": content,
            "content_hash": sha256_text(content),
            "char_count": len(content),
            "chunk_type": ch["chunk_type"],
            "heading_path": ch["heading_path"],
            "page_start": ch["page_start"],
            "page_end": ch["page_end"],
            "metadata": {
                "source_path": doc.get("source_path"),
                "title": doc.get("title"),
                "format": doc.get("format"),
                "language": doc.get("language"),
                "unit_type": doc.get("unit_type"),
            },
        })
    return out
