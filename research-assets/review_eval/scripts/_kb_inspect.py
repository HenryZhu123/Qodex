"""Ad-hoc read-only inspection of the local knowledge base."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\kb_review\books")


def main() -> None:
    for subject in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        print(f"=== {subject.name}")
        db = subject / "kb.sqlite"
        if db.exists():
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cursor = conn.cursor()
            tables = [r[0] for r in cursor.execute("select name from sqlite_master where type='table'")]
            print(f"  db tables: {tables}")
            for table in tables:
                count = cursor.execute(f"select count(*) from {table}").fetchone()[0]
                print(f"    {table}: {count} rows")
                cols = [c[1] for c in cursor.execute(f"pragma table_info({table})")]
                print(f"      cols: {cols[:12]}")
                for row in cursor.execute(f"select * from {table} limit 1"):
                    preview = [str(v)[:90] for v in row]
                    print(f"      sample: {preview}")
            conn.close()
        chunks = subject / "chunks.jsonl"
        if chunks.exists():
            lines = chunks.read_text(encoding="utf-8").splitlines()
            first = json.loads(lines[0]) if lines else {}
            print(f"  chunks: {len(lines)} rows, fields={list(first.keys())}")
        manifest = subject / "manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            print(f"  manifest keys: {list(data.keys())[:10]}")
            print(f"  manifest: {json.dumps(data, ensure_ascii=False)[:600]}")


if __name__ == "__main__":
    main()
