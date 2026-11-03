from __future__ import annotations

import json
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
    source: str = ""
    conflict_group: str = ""
    conflict_stance: str = ""


class KnowledgeBaseRetriever:
    def __init__(self, kb_root: str | Path | None = None, mode: str = "multi") -> None:
        self.kb_root = Path(kb_root) if kb_root else DEFAULT_KB_ROOT
        # off: no retrieval; single: only kb.sqlite; multi: every kb*.sqlite + relations
        self.mode = mode if mode in {"off", "single", "multi"} else "multi"
        self._relations_cache: dict[str, dict] = {}

    def is_available(self) -> bool:
        if self.mode == "off":
            return False
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

    def _subject_dbs(self, subject: str) -> list[Path]:
        subject_dir = self.kb_root / subject
        if not subject_dir.is_dir():
            return []
        primary = subject_dir / "kb.sqlite"
        extra = [
            p
            for p in sorted(subject_dir.glob("kb_*.sqlite"))
            if p.is_file() and self.mode != "single"
        ]
        return ([primary] if primary.exists() else []) + extra

    def _relations(self, subject: str) -> dict:
        """Optional sidecar mapping conflict groups to both sides."""
        if subject in self._relations_cache:
            return self._relations_cache[subject]
        path = self.kb_root / subject / "relations.json"
        data: dict = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        self._relations_cache[subject] = data
        return data

    def _query_db(self, db: Path, match_str: str, limit: int, source_label: str = "") -> list[KBEvidenceItem]:
        subject_name = db.parent.name
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                """
                SELECT c.chunk_id, c.heading_path, c.page_start, c.content,
                       bm25(chunks_fts) as score, c.metadata_json
                FROM chunks_fts f
                JOIN chunks c ON c.chunk_id = f.chunk_id
                WHERE chunks_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (match_str, limit),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()

        items: list[KBEvidenceItem] = []
        for chunk_id, heading, page, content, score, metadata_json in rows:
            metadata = {}
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json)
                except json.JSONDecodeError:
                    metadata = {}
            items.append(
                KBEvidenceItem(
                    subject=subject_name,
                    chunk_id=chunk_id,
                    heading_path=heading or "",
                    page_start=page,
                    content=content,
                    score=float(score) if score is not None else 0.0,
                    source=str(metadata.get("source") or source_label or ""),
                    conflict_group=str(metadata.get("conflict_group_id") or ""),
                    conflict_stance="",
                )
            )
        return items

    def search(
        self,
        subject: str,
        query: str,
        *,
        top_k: int = 2,
    ) -> tuple[list[KBEvidenceItem], float]:
        t0 = time.perf_counter()
        if self.mode == "off":
            return [], (time.perf_counter() - t0) * 1000.0
        normalized_sub = SUBJECT_ALIASES.get(subject, subject)
        target_dbs = self._subject_dbs(normalized_sub)
        if not target_dbs:
            target_dbs = [
                db
                for sub in SUBJECT_MAP
                for db in self._subject_dbs(sub)
            ]

        match_str = self._build_fts_query(query)
        if not match_str:
            return [], (time.perf_counter() - t0) * 1000.0

        relations = {} if self.mode == "single" else self._relations(normalized_sub)
        label_by_db = {
            Path(path).name: name
            for name, path in (relations.get("sources") or {}).items()
        }
        items: list[KBEvidenceItem] = []
        for db in target_dbs:
            items.extend(
                self._query_db(db, match_str, top_k * 2, label_by_db.get(db.name, ""))
            )
        items.sort(key=lambda x: x.score)

        # A conflict group must be returned whole: retrieval may not silently
        # keep only the best-ranked side.
        groups: dict[str, list[dict]] = relations.get("conflicts", {})
        selected = items[:top_k]
        seen_ids = {item.chunk_id for item in selected}
        expanded: list[KBEvidenceItem] = []
        for item in selected:
            expanded.append(item)
            group = groups.get(item.conflict_group) if item.conflict_group else None
            if not group:
                continue
            for member in group:
                if member["chunk_id"] in seen_ids:
                    continue
                seen_ids.add(member["chunk_id"])
                expanded.append(
                    KBEvidenceItem(
                        subject=normalized_sub,
                        chunk_id=member["chunk_id"],
                        heading_path="",
                        page_start=member.get("page"),
                        content=member.get("text", ""),
                        score=item.score,
                        source=member.get("source", ""),
                        conflict_group=item.conflict_group,
                        conflict_stance=member.get("stance", ""),
                    )
                )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return expanded, latency_ms

    def format_evidence(
        self, evidence: list[KBEvidenceItem], *, max_chars: int = 500
    ) -> str:
        if not evidence:
            return ""
        lines = ["[权威教材检索依据]"]
        conflicts: dict[str, list[KBEvidenceItem]] = {}
        for i, ev in enumerate(evidence, 1):
            subj_cn = SUBJECT_MAP.get(ev.subject, ev.subject)
            head = ev.heading_path or "正文"
            page = f" p.{ev.page_start}" if ev.page_start else ""
            source = f"｜来源 {ev.source}" if ev.source else ""
            snippet = ev.content.replace("\n", " ").strip()[:max_chars]
            lines.append(f"({i}) 【{subj_cn}｜{head}{page}{source}】{snippet}")
            if ev.conflict_group:
                conflicts.setdefault(ev.conflict_group, []).append(ev)
        for group, members in conflicts.items():
            if len(members) < 2:
                continue
            sides = "；".join(
                f"{m.source or '未知来源'} 说「{(m.conflict_stance or m.content)[:80]}」"
                for m in members
            )
            lines.append(
                "注意：以上来源对同一问题给出不同说法，请依据来源版本或题目适用范围作答，"
                f"不要合并成一句。{sides}"
            )
        return "\n".join(lines)
