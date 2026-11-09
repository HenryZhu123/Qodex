#!/usr/bin/env python3
"""Rebuild the dedup registry from the current indexes.

The registry stores content hashes, so re-chunking invalidates it: the old
fingerprints describe boundaries that no longer exist. This wipes
`chunk_registry` and repopulates it from every index, then refreshes
`documents.chunk_count`. Document metadata (title, file hash, term fingerprint)
describes the PDF, not the chunking, and is left alone.

Run after any re-chunk or re-ingest. The 8th-edition index is included because a
future import of that book must also be deduplicated.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

SCRIPTS = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\skills\build-knowledge-base\scripts")
sys.path.insert(0, str(SCRIPTS))

from kb_registry import DEFAULT_REGISTRY, chunk_sha256, connect  # noqa: E402

KB_ROOT = Path(r"D:\Code\hku\LLM\kb_review\books")


def main() -> int:
    registry = connect(DEFAULT_REGISTRY)
    index_paths = sorted(KB_ROOT.rglob("kb*.sqlite"))
    if not index_paths:
        print("no indexes found", file=sys.stderr)
        return 1

    seen: dict[str, str] = {}
    per_doc: dict[str, int] = {}
    for db in index_paths:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT doc_id, content FROM chunks").fetchall()
        finally:
            conn.close()
        for doc_id, content in rows:
            if not content:
                continue
            seen[chunk_sha256(content)] = doc_id
            per_doc[doc_id] = per_doc.get(doc_id, 0) + 1

    registry.execute("DELETE FROM chunk_registry")
    registry.executemany(
        "INSERT OR IGNORE INTO chunk_registry (chunk_hash, doc_id) VALUES (?, ?)",
        list(seen.items()),
    )
    for doc_id, count in per_doc.items():
        registry.execute("UPDATE documents SET chunk_count = ? WHERE doc_id = ?", (count, doc_id))

    registered = {
        row[0]: row[1]
        for row in registry.execute("SELECT doc_id, chunk_count FROM documents").fetchall()
    }
    orphan_docs = sorted(set(per_doc) - set(registered))
    registry.commit()
    registry.close()

    print(json.dumps({
        "indexes": [str(p.relative_to(KB_ROOT)) for p in index_paths],
        "chunk_hashes": len(seen),
        "per_doc": per_doc,
        "registered_chunk_counts": registered,
        "documents_not_in_registry": orphan_docs,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
