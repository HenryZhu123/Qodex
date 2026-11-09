#!/usr/bin/env python3
"""Build the 8th-edition index from the Phase 6 delta (3a + 3b).

Only chunks that add information over the 7th edition are indexed:

  exclusive (155)      new knowledge
  complementary (6)    related but non-duplicate
  conflict (25)        contradictory variants, kept on both sides

The 602 `equivalent` chunks are deliberately NOT indexed — indexing them would
return the same fact twice, which the relation rules forbid. Their text is
recorded as aliases of the canonical 7th-edition chunk instead.

Outputs:
  kb_review/books/computer_network/kb_8th.sqlite
  kb_review/books/computer_network/relations.json
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\skills\build-knowledge-base\scripts")
sys.path.insert(0, str(SCRIPTS))

from kb_registry import content_sha256  # noqa: E402
from phase6_align import chunk_eighth  # noqa: E402
from store import is_stub  # noqa: E402
from textclean import repair_ocr  # noqa: E402
from utils import tokenize_for_fts  # noqa: E402

MAX_CHARS = 1200


def _split_for_budget(text: str, max_chars: int) -> list[str]:
    """Split a MinerU block so no chunk exceeds the review budget.

    Blocks arrive whole; a few in the 8th edition pass 5,000 characters, which no
    review prompt can use. Split on blank lines first, then on line breaks, then
    by characters, so the result keeps paragraph structure where possible.
    """
    if len(text) <= max_chars:
        return [text]
    for separator in ("\n\n", "\n"):
        parts = text.split(separator)
        if len(parts) > 1:
            pieces: list[str] = []
            buffer = ""
            for part in parts:
                candidate = f"{buffer}{separator}{part}" if buffer else part
                if len(candidate) <= max_chars:
                    buffer = candidate
                    continue
                if buffer:
                    pieces.append(buffer)
                buffer = part
                while len(buffer) > max_chars:
                    pieces.append(buffer[:max_chars])
                    buffer = buffer[max_chars:]
            if buffer:
                pieces.append(buffer)
            if all(len(piece) <= max_chars for piece in pieces):
                return [piece for piece in pieces if piece.strip()]
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

SUBJECT_DIR = Path(r"D:\Code\hku\LLM\kb_review\books\computer_network")
DELTA = SUBJECT_DIR.parent / "computer_network_8th" / "delta" / "kurose8th.jsonl"
SEVENTH_DB = SUBJECT_DIR / "kb.sqlite"
EIGHTH_DB = SUBJECT_DIR / "kb_8th.sqlite"
RELATIONS = SUBJECT_DIR / "relations.json"

INDEXED = {"exclusive", "complementary", "conflict"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY, source_path TEXT, source_hash TEXT, title TEXT,
    format TEXT, parse_method TEXT, unit_type TEXT, unit_count INTEGER,
    char_count INTEGER, language TEXT, created_at TEXT, metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY, doc_id TEXT, chunk_index INTEGER, content TEXT,
    content_hash TEXT, char_count INTEGER, chunk_type TEXT, heading_path TEXT,
    page_start INTEGER, page_end INTEGER, metadata_json TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content_tokens, heading_path, doc_id, chunk_id, tokenize='unicode61'
);
"""


def seventh_text(chunk_id: str) -> dict:
    conn = sqlite3.connect(f"file:{SEVENTH_DB.as_posix()}?mode=ro", uri=True)
    row = conn.execute(
        "SELECT content, page_start, heading_path FROM chunks WHERE chunk_id = ?",
        (chunk_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {}
    return {"text": row[0], "page": row[1], "heading": row[2] or ""}


def main() -> None:
    delta = {}
    for line in DELTA.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            delta[row["chunk_id"]] = row
    chunks = {c["chunk_id"]: c for c in chunk_eighth()}

    EIGHTH_DB.unlink(missing_ok=True)
    conn = sqlite3.connect(EIGHTH_DB)
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    indexed = [cid for cid, row in delta.items() if row.get("relation") in INDEXED]
    total_chars = 0
    skipped = 0
    split_count = 0
    for position, cid in enumerate(sorted(indexed), start=1):
        row = delta[cid]
        chunk = chunks.get(cid)
        if chunk is None:
            continue
        text = repair_ocr(chunk["text"])["text"]
        # MinerU returns whole blocks; some exceed 5,000 characters, which blows
        # the review budget. Split them so every chunk fits MAX_CHARS.
        pieces = _split_for_budget(text, MAX_CHARS)
        if len(pieces) > 1:
            split_count += 1
        total_chars += len(text)
        metadata = {
            "relation": row["relation"],
            "canonical_id": row.get("canonical_id"),
            "source": "kurose-8th",
            "source_versions": row.get("source_versions", ["kurose-8th"]),
            "conflict_group_id": row.get("conflict_group_id"),
            "related_to": row.get("related_to", []),
        }
        for part_index, part in enumerate(pieces, start=1):
            part_id = cid if len(pieces) == 1 else f"{cid}#{part_index}"
            conn.execute(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    part_id,
                    "kurose8th",
                    position,
                    part,
                    content_sha256(part),
                    len(part),
                    "markdown_block",
                    "",
                    chunk.get("page"),
                    chunk.get("page"),
                    json.dumps({**metadata, "part": part_index}, ensure_ascii=False),
                ),
            )
            if is_stub(part):
                # A caption or a page number would rank high in BM25 precisely
                # because it is short; keep the row, leave it out of the index.
                skipped += 1
            else:
                conn.execute(
                    "INSERT INTO chunks_fts (content_tokens, heading_path, doc_id, chunk_id) VALUES (?,?,?,?)",
                    (tokenize_for_fts(part), "", "kurose8th", part_id),
                )

    conn.execute(
        "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "kurose8th",
            str(SUBJECT_DIR.parent / "computer_network_8th"),
            None,
            "计算机网络：自顶向下方法（原书第8版）",
            "pdf",
            "mineru-agent",
            "page_range",
            26,
            total_chars,
            "zh",
            now,
            json.dumps({"role": "second_source", "source": "kurose-8th"}, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()

    # relations sidecar: per-chunk metadata plus conflict groups with both sides
    relations: dict[str, object] = {
        "subject": "computer_network",
        "generated_at": now,
        "sources": {"kurose-7th": "kb.sqlite", "kurose-8th": "kb_8th.sqlite"},
        "chunks": {},
        "conflicts": {},
        "equivalent_aliases": {},
    }
    counts = Counter()
    for cid, row in delta.items():
        relation = row.get("relation")
        counts[relation] += 1
        relations["chunks"][cid] = {
            "relation": relation,
            "source": "kurose-8th",
            "canonical_id": row.get("canonical_id"),
            "conflict_group_id": row.get("conflict_group_id"),
        }
        if relation == "equivalent" and row.get("canonical_id"):
            relations["equivalent_aliases"].setdefault(row["canonical_id"], []).append(
                {"chunk_id": cid, "text": (chunks.get(cid) or {}).get("text", "")[:400]}
            )
        if relation == "conflict":
            group = row.get("conflict_group_id") or f"conflict:{cid}"
            old = seventh_text(row["candidates"][0]["chunk_id"]) if row.get("candidates") else {}
            relations["conflicts"][group] = [
                {
                    "chunk_id": row["candidates"][0]["chunk_id"] if row.get("candidates") else "",
                    "source": "kurose-7th",
                    "page": old.get("page"),
                    "text": (old.get("text") or "")[:800],
                    "stance": row.get("counterpart_stance", ""),
                },
                {
                    "chunk_id": cid,
                    "source": "kurose-8th",
                    "page": (chunks.get(cid) or {}).get("page"),
                    "text": (chunks.get(cid) or {}).get("text", "")[:800],
                    "stance": row.get("conflict_stance", ""),
                },
            ]

    relations["counts"] = dict(counts)
    RELATIONS.write_text(json.dumps(relations, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "indexed_chunks": len(indexed),
                "skipped_equivalent": counts.get("equivalent", 0),
                "conflict_groups": len(relations["conflicts"]),
                "alias_canonicals": len(relations["equivalent_aliases"]),
                "db": str(EIGHTH_DB),
                "relations": str(RELATIONS),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
