"""Audit heading quality per segment, not per joined path.

A joined path like 「第1章 > 1.2 基本概念 > 1.2.1 数据」 is long but healthy. The
defect is a *segment* that is really body text: a sentence, a binary string, code,
or a bare page running head.
"""

from __future__ import annotations

import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

BODY_PUNCT = re.compile(r"[。，；！？]")
CODE_MARK = re.compile(r"(/\*|//|#include|wake_up|__)")
BINARY = re.compile(r"^[01\s]{8,}$")
NUMERIC_ONLY = re.compile(r"^[\d\s.]+$")
CHAPTER_ONLY = re.compile(r"^第\s*\d+\s*章$")
SEGMENT_MAX = 48

DBS = {
    "data_structure": ["data_structure/kb.sqlite"],
    "computer_organization": ["computer_organization/kb.sqlite"],
    "operating_system": ["operating_system/kb.sqlite"],
    "computer_network": ["computer_network/kb.sqlite", "computer_network/kb_8th.sqlite"],
}


def bad_segment(segment: str) -> bool:
    s = segment.strip()
    if not s:
        return False
    if len(s) > SEGMENT_MAX or BODY_PUNCT.search(s) or CODE_MARK.search(s):
        return True
    if BINARY.match(s) or NUMERIC_ONLY.match(s):
        return True
    return False


def audit(root: Path) -> dict:
    report: dict[str, dict] = {}
    for subject, rels in DBS.items():
        stats = collections.Counter()
        samples: list[str] = []
        for rel in rels:
            db = root / rel
            if not db.is_file():
                continue
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            rows = conn.execute(
                "SELECT heading_path, content FROM chunks"
            ).fetchall()
            indexed = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
            conn.close()
            stats["chunks"] += len(rows)
            stats["indexed"] += indexed
            for heading, content in rows:
                segments = [s for s in (heading or "").split(">") if s.strip()]
                stats["segments"] += len(segments)
                if any(bad_segment(s) for s in segments):
                    stats["chunks_with_bad_segment"] += 1
                    if len(samples) < 3:
                        samples.append(max(segments, key=len)[:70])
                if not segments:
                    stats["chunks_without_heading"] += 1
                if " > " in (content or ""):
                    stats["content_has_path_separator"] += 1
        report[subject] = {**dict(stats), "samples": samples}
    return report


def main() -> int:
    root = Path(sys.argv[1])
    print(json.dumps(audit(root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
