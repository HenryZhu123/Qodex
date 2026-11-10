#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the four-subject textbook knowledge base used by the review ablation.

Runs the build-knowledge-base pipeline once per textbook, then merges the
resulting chunk stores into a single SQLite database used for retrieval.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

BOOKS = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\408exam\参考教材")
SKILL = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\skills\build-knowledge-base")
OUT = Path(r"D:\Code\hku\LLM\kb_review")
EACH = OUT / "books"

TEXTBOOKS = {
    "data_structure": "数据结构（C语言版）（第2版） (严蔚敏 李冬梅 吴伟民) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
    "computer_organization": "计算机组成原理 (谭志虎) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
    "operating_system": "计算机操作系统（慕课版） (汤小丹, 王红玲, 姜华, 汤子瀛) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
    "computer_network": "计算机网络：自顶向下方法（原书第8版） (James F. Kurose, Keith W. Ross, 陈鸣) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
}


def build_one(subject: str, pdf: Path) -> Path | None:
    out_dir = EACH / subject
    cmd = [
        sys.executable,
        str(SKILL / "scripts" / "kb_pipeline.py"),
        "run",
        "--input", str(pdf),
        "--out", str(out_dir),
        "--mode", "auto",
        "--stop-after", "ingest",
    ]
    print(f"\n=== {subject}")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (proc.stdout or "")[-800:]
    print(tail)
    if proc.returncode != 0:
        print("STDERR:", (proc.stderr or "")[-1200:])
        return None
    dbs = list(out_dir.rglob("*.sqlite")) + list(out_dir.rglob("*.db"))
    return dbs[0] if dbs else None


def merge(dbs: list[tuple[str, Path]], target: Path) -> None:
    if target.exists():
        target.unlink()
    conn = sqlite3.connect(target)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY, subject TEXT, title TEXT, source TEXT);
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY, doc_id TEXT, subject TEXT,
            heading_path TEXT, page INTEGER, text TEXT, tokens TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            tokens, chunk_id UNINDEXED, doc_id UNINDEXED, subject UNINDEXED,
            tokenize='unicode61');
        """
    )
    for subject, db in dbs:
        src = sqlite3.connect(db)
        src.row_factory = sqlite3.Row
        docs = src.execute("SELECT * FROM chunks").fetchall()
        for row in docs:
            keys = row.keys()
            cid = row["chunk_id"] if "chunk_id" in keys else str(row[0])
            did = row["doc_id"] if "doc_id" in keys else ""
            text = row["text"] if "text" in keys else ""
            heading = row["heading_path"] if "heading_path" in keys else ""
            page = row["page"] if "page" in keys else None
            cur.execute(
                "INSERT OR IGNORE INTO chunks (chunk_id, doc_id, subject, heading_path, page, text, tokens)"
                " VALUES (?,?,?,?,?,?,?)",
                (f"{subject}:{cid}", did, subject, heading, page, text, ""),
            )
        src.close()
    conn.commit()
    conn.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    built = []
    for subject, name in TEXTBOOKS.items():
        pdf = BOOKS / name
        if not pdf.exists():
            print(f"MISSING {subject}: {pdf}")
            return 2
        db = build_one(subject, pdf)
        if db is None:
            print(f"FAILED {subject}")
            continue
        built.append((subject, db))
        print(f"{subject} -> {db}")

    print(f"\nbuilt {len(built)}/{len(TEXTBOOKS)}")
    for subject, db in built:
        conn = sqlite3.connect(db)
        try:
            n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        except sqlite3.Error as exc:
            n = f"err: {exc}"
        conn.close()
        print(f"  {subject}: {n} chunks  ({db})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
