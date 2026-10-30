#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Autonomous Router and Targeted Retriever for 408 Exam Review.

Decides whether a question requires knowledge base retrieval, and if so,
generates targeted query terms and performs scoped retrieval over subject DBs.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
PROMPT_PATH = ROOT_DIR / "prompts" / "router" / "task.txt"
KB_ROOT = Path(r"D:\Code\hku\LLM\kb_review\books")

SUBJECT_MAP = {
    "data_structure": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_system": "操作系统",
    "computer_network": "计算机网络",
}

SUBJECT_ALIASES = {
    "数据结构": "data_structure",
    "计组": "computer_organization",
    "计算机组成原理": "computer_organization",
    "计算机组成": "computer_organization",
    "操作系统": "operating_system",
    "计网": "computer_network",
    "计算机网络": "computer_network",
}


@dataclass
class EvidenceItem:
    subject: str
    chunk_id: str
    heading_path: str
    page_start: int | None
    content: str
    score: float = 0.0


@dataclass
class RouterDecision:
    decision: str  # "NEED_KB" | "SKIP"
    reason: str
    subject: str
    search_queries: list[str] = field(default_factory=list)
    raw_response: str = ""
    latency_ms: float = 0.0
    evidence: list[EvidenceItem] = field(default_factory=list)
    retrieval_latency_ms: float = 0.0


def parse_json_from_text(text: str) -> dict[str, Any] | None:
    """Robustly extract first complete JSON object from text."""
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


_JIEBA: object | None = None


def _jieba_module():
    """Lazily import jieba; the FTS index was built on jieba tokens.

    The ``chunks_fts.content_tokens`` column stores space-separated jieba
    tokens, so a raw compound query such as "突发传输" becomes a single FTS
    token and matches nothing. Queries must be segmented the same way.
    """
    global _JIEBA
    if _JIEBA is None:
        try:
            import jieba

            jieba.setLogLevel(60)
            _JIEBA = jieba
        except Exception:
            _JIEBA = False
    return _JIEBA or None


def build_fts_query(text: str) -> str:
    tokens: list[str] = []
    jb = _jieba_module()
    if jb is not None:
        # jieba emits the same segmentation used to build the index.
        for tok in jb.cut(text):
            tok = tok.strip()
            if len(tok) >= 2 and not tok.isspace():
                tokens.append(tok)
    # ASCII / technical identifiers survive tokenisation untouched.
    tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9+#\-]{1,}", text))
    # Fallback: if segmentation produced nothing usable, use raw CJK runs.
    if not tokens:
        tokens.extend(re.findall(r"[\u4e00-\u9fff]{2,}", text))

    seen: set[str] = set()
    uniq: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    if not uniq:
        return ""
    return " OR ".join(f'"{t}"' for t in uniq[:16])


def targeted_retrieve(
    subject: str,
    queries: list[str],
    top_k: int = 2,
    kb_root: Path = KB_ROOT,
) -> tuple[list[EvidenceItem], float]:
    """Search subject-specific SQLite DB using targeted queries."""
    t0 = time.perf_counter()
    normalized_sub = SUBJECT_ALIASES.get(subject, subject)
    db_path = kb_root / normalized_sub / "kb.sqlite"
    if not db_path.exists():
        # Fallback to searching all subjects if specific DB missing
        target_dbs = [kb_root / s / "kb.sqlite" for s in SUBJECT_MAP if (kb_root / s / "kb.sqlite").exists()]
    else:
        target_dbs = [db_path]

    combined_query_text = " ".join(queries).strip()
    match_str = build_fts_query(combined_query_text)
    if not match_str:
        return [], (time.perf_counter() - t0) * 1000.0

    items: list[EvidenceItem] = []
    for db in target_dbs:
        sub_name = db.parent.name
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                """
                SELECT c.chunk_id, c.heading_path, c.page_start, c.content, bm25(chunks_fts) as score
                FROM chunks_fts f
                JOIN chunks c ON c.chunk_id = f.chunk_id
                WHERE chunks_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (match_str, top_k),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()

        for chunk_id, heading, page, content, score in rows:
            items.append(
                EvidenceItem(
                    subject=sub_name,
                    chunk_id=chunk_id,
                    heading_path=heading or "",
                    page_start=page,
                    content=content,
                    score=float(score) if score is not None else 0.0,
                )
            )

    # Sort overall by bm25 score ascending (lower is better in sqlite bm25)
    items.sort(key=lambda x: x.score)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return items[:top_k], latency_ms


def format_evidence_block(evidence: list[EvidenceItem], max_chars: int = 500) -> str:
    if not evidence:
        return ""
    lines = ["[权威教材检索依据]"]
    for i, ev in enumerate(evidence, 1):
        subj_cn = SUBJECT_MAP.get(ev.subject, ev.subject)
        head = ev.heading_path or "正文"
        page = f" p.{ev.page_start}" if ev.page_start else ""
        snippet = ev.content.replace("\n", " ").strip()[:max_chars]
        lines.append(f"({i}) 【{subj_cn}｜{head}{page}】{snippet}")
    return "\n".join(lines)


async def call_router(
    client: Any,
    base_url: str,
    api_key: str,
    model: str,
    full_text: str,
    subject_hint: str | None = None,
    system_prompt: str | None = None,
) -> RouterDecision:
    """Invokes LLM router to decide whether KB retrieval is needed."""
    if system_prompt is None:
        system_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()

    user_payload: dict[str, Any] = {"question_text": full_text}
    if subject_hint:
        user_payload["subject_hint"] = subject_hint

    user_content = "[INPUT_PAYLOAD]\n" + json.dumps(user_payload, ensure_ascii=False)

    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.0,
                "seed": 42,
                "response_format": {"type": "json_object"},
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=60,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        if resp.status_code != 200:
            return RouterDecision(
                decision="SKIP",
                reason=f"Router API error: {resp.status_code}",
                subject=subject_hint or "unknown",
                latency_ms=latency_ms,
            )

        raw = resp.json()["choices"][0]["message"]["content"]
        data = parse_json_from_text(raw) or {}
        decision_val = (data.get("decision") or "SKIP").upper()
        if decision_val not in ("NEED_KB", "SKIP"):
            decision_val = "SKIP"

        res = RouterDecision(
            decision=decision_val,
            reason=data.get("reason") or "",
            subject=data.get("subject") or (subject_hint or "unknown"),
            search_queries=data.get("search_queries") or [],
            raw_response=raw,
            latency_ms=latency_ms,
        )

        if res.decision == "NEED_KB" and res.search_queries:
            ev, r_lat = targeted_retrieve(res.subject, res.search_queries, top_k=2)
            res.evidence = ev
            res.retrieval_latency_ms = r_lat

        return res

    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return RouterDecision(
            decision="SKIP",
            reason=f"Exception: {type(exc).__name__}: {exc}",
            subject=subject_hint or "unknown",
            latency_ms=latency_ms,
        )
