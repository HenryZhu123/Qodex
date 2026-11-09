#!/usr/bin/env python3
"""Package the SQLite knowledge base with a manifest and zip it.

Copies the five indexes, the cross-edition relations and the optional dedup
registry into dist/<name>/, writes MANIFEST.json with sha256 and row counts,
then produces dist/<name>.zip. Run from the workspace root.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM")
KB = ROOT / "kb_review"
NAME = "qodex-kb-sqlite-2026.11.1"
DIST = ROOT / "dist"
STAGE = DIST / NAME

FILES = [
    ("books/data_structure/kb.sqlite", "books/data_structure/kb.sqlite"),
    ("books/computer_organization/kb.sqlite", "books/computer_organization/kb.sqlite"),
    ("books/operating_system/kb.sqlite", "books/operating_system/kb.sqlite"),
    ("books/computer_network/kb.sqlite", "books/computer_network/kb.sqlite"),
    ("books/computer_network/kb_8th.sqlite", "books/computer_network/kb_8th.sqlite"),
    ("books/computer_network/relations.json", "books/computer_network/relations.json"),
    ("registry.sqlite", "registry.sqlite"),
]

README = ROOT / "hku_agent/research-assets/review_eval/kb_package/README.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def counts(path: Path) -> dict:
    if path.suffix != ".sqlite":
        return {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        info = {}
        if "chunks" in tables:
            info["chunks"] = conn.execute("select count(*) from chunks").fetchone()[0]
            info["chars"] = conn.execute("select coalesce(sum(length(content)),0) from chunks").fetchone()[0]
        if "documents" in tables:
            info["documents"] = conn.execute("select count(*) from documents").fetchone()[0]
        if "chunk_registry" in tables:
            info["chunk_registry"] = conn.execute("select count(*) from chunk_registry").fetchone()[0]
        return info
    finally:
        conn.close()


def main() -> int:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True, exist_ok=True)
    (STAGE / "books").mkdir(exist_ok=True)

    entries = []
    total_chunks = 0
    total_chars = 0
    for src_rel, dst_rel in FILES:
        src = KB / src_rel
        if not src.is_file():
            raise SystemExit(f"missing source: {src}")
        dst = STAGE / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        rows = counts(dst)
        total_chunks += rows.get("chunks", 0)
        total_chars += rows.get("chars", 0)
        entries.append({
            "path": dst_rel,
            "bytes": dst.stat().st_size,
            "sha256": sha256(dst),
            **rows,
        })

    manifest = {
        "name": NAME,
        "version": "2026.11.1",
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total_chunks": total_chunks,
        "total_chars": total_chars,
        "files": entries,
        "notes": [
            "kb_8th.sqlite is an incremental index: only passages unique to the 8th edition",
            "relations.json maps equivalent and conflicting passages between the two editions",
            "registry.sqlite is optional and only needed when ingesting new books",
        ],
    }
    (STAGE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.copy2(README, STAGE / "README.md")

    # Opening a WAL-mode database creates -shm/-wal sidecars; they are not data.
    for sidecar in list(STAGE.rglob("*-wal")) + list(STAGE.rglob("*-shm")):
        sidecar.unlink()

    zip_path = DIST / f"{NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                zf.write(path, Path(NAME) / path.relative_to(STAGE))

    print(json.dumps({
        "stage": str(STAGE),
        "zip": str(zip_path),
        "zip_mb": round(zip_path.stat().st_size / 1048576, 2),
        "total_chunks": total_chunks,
        "total_chars": total_chars,
        "files": len(entries),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
