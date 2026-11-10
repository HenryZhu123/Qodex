"""Rebuild every knowledge-base index from the parsed artefacts.

Copies each book directory into kb_rebuild/, re-chunks with the tightened heading
detector, and ingests into a fresh database. The shipped indexes are untouched.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM")
SRC = ROOT / "kb_review" / "books"
DST = ROOT / "kb_rebuild"
SCRIPTS = ROOT / "hku_agent" / "research-assets" / "skills" / "build-knowledge-base" / "scripts"

TARGETS = [
    ("data_structure", "kb.sqlite"),
    ("computer_organization", "kb.sqlite"),
    ("operating_system", "kb.sqlite"),
    ("computer_network", "kb.sqlite"),
    # The 8th edition is an incremental index built by build_phase6_index.py from
    # the Phase 6 delta, not by this pipeline. Rebuilding it here would overwrite
    # it with a second copy of the 7th edition.
]


def main() -> int:
    for subject, db_name in TARGETS:
        src_dir = SRC / subject
        dst_dir = DST / subject
        dst_dir.mkdir(parents=True, exist_ok=True)
        for item in src_dir.iterdir():
            if item.name.startswith(db_name):
                continue
            target = dst_dir / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            elif item.is_file() and not target.exists():
                shutil.copy2(item, target)

        label = f"{subject}/{db_name}"
        chunk_cmd = [sys.executable, "kb_pipeline.py", "chunk", "--out", str(dst_dir)]
        ingest_cmd = [sys.executable, "kb_pipeline.py", "ingest", "--out", str(dst_dir),
                      "--db", str(dst_dir / "kb_new.sqlite")]
        chunk = subprocess.run(chunk_cmd, cwd=SCRIPTS, capture_output=True, text=True, encoding="utf-8")
        print(f"[{label}] chunk rc={chunk.returncode} {(chunk.stdout or '').strip().splitlines()[-1:]}")
        if chunk.returncode != 0:
            print((chunk.stderr or "")[-400:])
            continue
        ingest = subprocess.run(ingest_cmd, cwd=SCRIPTS, capture_output=True, text=True, encoding="utf-8")
        tail = [l for l in (ingest.stdout or "").splitlines() if l.strip()][-1:]
        err = [l for l in (ingest.stderr or "").splitlines() if "fragment" in l]
        print(f"[{label}] ingest rc={ingest.returncode} {tail} {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
