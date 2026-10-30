from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KB_ROOT = Path(r"D:\Code\hku\LLM\kb_review\books")

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


@dataclass(frozen=True, slots=True)
class KBEvidenceItem:
    subject: str
    chunk_id: str
    heading_path: str
    page_start: int | None
    content: str
    score: float = 0.0


class KnowledgeBaseRetriever:
    def __init__(self, kb_root: str | Path | None = None) -> None:
        self.kb_root = Path(kb_root) if kb_root else DEFAULT_KB_ROOT

    def is_available(self) -> bool:
        if not self.kb_root.is_dir():
            return False
        return any((self.kb_root / sub / "kb.sqlite").exists() for sub in SUBJECT_MAP)

    @staticmethod
    def _build_fts_query(text: str) -> str:
        tokens: list[str] = []
        try:
            import jieba

            jieba.setLogLevel(60)
            for tok in jieba.cut(text):
                tok = tok.strip()
                if len(tok) >= 2 and not tok.isspace():
                    tokens.append(tok)
        except Exception:
            pass
        tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9+#\-]{1,}", text))
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

    def search(
        self,
        subject: str,
        query: str,
        *,
        top_k: int = 2,
    ) -> tuple[list[KBEvidenceItem], float]:
        t0 = time.perf_counter()
        normalized_sub = SUBJECT_ALIASES.get(subject, subject)
        db_path = self.kb_root / normalized_sub / "kb.sqlite"
        if not db_path.exists():
            target_dbs = [
                self.kb_root / s / "kb.sqlite"
                for s in SUBJECT_MAP
                if (self.kb_root / s / "kb.sqlite").exists()
            ]
        else:
            target_dbs = [db_path]

        match_str = self._build_fts_query(query)
        if not match_str:
            return [], (time.perf_counter() - t0) * 1000.0

        items: list[KBEvidenceItem] = []
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
                    KBEvidenceItem(
                        subject=sub_name,
                        chunk_id=chunk_id,
                        heading_path=heading or "",
                        page_start=page,
                        content=content,
                        score=float(score) if score is not None else 0.0,
                    )
                )

        items.sort(key=lambda x: x.score)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return items[:top_k], latency_ms

    def format_evidence(
        self, evidence: list[KBEvidenceItem], *, max_chars: int = 500
    ) -> str:
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
