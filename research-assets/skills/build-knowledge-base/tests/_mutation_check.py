"""Mutation check: break each fix and confirm the tests notice.

A test that passes both with and without the fix is not a test. Each mutation
below restores the pre-fix behaviour; the expected outcome is a non-zero pytest
exit with failures inside the named file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\skills\build-knowledge-base")
SCRIPTS = ROOT / "scripts"

MUTATIONS = [
    (
        "heading gate disabled",
        SCRIPTS / "chunker.py",
        "    s = text.strip()\n    if not s or len(s) > _TITLE_MAX_CHARS:",
        "    s = text.strip()\n    return True\n    if not s or len(s) > _TITLE_MAX_CHARS:",
        "tests/test_heading_gate.py",
    ),
    (
        "fragment filter disabled",
        SCRIPTS / "store.py",
        '    text = (body or "").strip()\n    return len(text) < STUB_MAX_CHARS and not SENTENCE_PUNCT.search(text)',
        '    text = (body or "").strip()\n    return False',
        "tests/test_stub_filter.py",
    ),
    (
        "heading stripping disabled",
        SCRIPTS / "store.py",
        '    text = (content or "").lstrip()\n    if not heading_path:',
        '    return (content or "").lstrip()\n    if not heading_path:',
        "tests/test_stub_filter.py",
    ),
    (
        "ingest stops skipping fragments",
        SCRIPTS / "store.py",
        "            if is_stub(body):\n                # Page numbers, figure captions and bare labels rank high because\n                # BM25 rewards short documents. Keep the row, leave it out of the\n                # index so it can never be returned as evidence.\n                skipped += 1\n                continue",
        "            if False:\n                skipped += 1\n                continue",
        "tests/test_store_contract.py",
    ),
    (
        "re-ingest stops replacing rows",
        SCRIPTS / "store.py",
        "            INSERT OR REPLACE INTO chunks",
        "            INSERT INTO chunks",
        "tests/test_store_contract.py",
    ),
    (
        "heading path no longer joined",
        SCRIPTS / "store.py",
        '                " > ".join(ch.get("heading_path") or []),',
        '                "".join(ch.get("heading_path") or []),',
        "tests/test_store_contract.py",
    ),
    (
        "rebuild ignores the fragment rule",
        SCRIPTS / "store.py",
        "        body = strip_leading_heading(row[\"content\"], heading)\n        if is_stub(body):\n            continue",
        "        body = strip_leading_heading(row[\"content\"], heading)",
        "tests/test_rebuild_contract.py",
    ),
    (
        "dedup stops checking the file hash",
        SCRIPTS / "kb_registry.py",
        '    row = conn.execute(\n        "SELECT doc_id, subject, title, added_at FROM documents WHERE file_sha256 = ?",\n        (file_hash,),\n    ).fetchone()',
        "    row = None",
        "tests/test_registry_dedup.py",
    ),
    (
        "unreadable pdf is not guarded",
        SCRIPTS / "kb_registry.py",
        "        except Exception as exc:  # corrupt file, encrypted PDF, missing text layer",
        "        except ZeroDivisionError as exc:  # corrupt file, encrypted PDF, missing text layer",
        "tests/test_registry_dedup.py",
    ),
    (
        "packing ignores max_chars",
        SCRIPTS / "chunker.py",
        '    max_chars = plan["max_chars"]',
        '    max_chars = plan["max_chars"] * 10',
        "tests/test_chunk_packing.py",
    ),
    (
        "e2e catches fragments reaching the index",
        SCRIPTS / "store.py",
        "            if is_stub(body):\n                # Page numbers, figure captions and bare labels rank high because\n                # BM25 rewards short documents. Keep the row, leave it out of the\n                # index so it can never be returned as evidence.\n                skipped += 1\n                continue",
        "            if False:\n                skipped += 1\n                continue",
        "tests/test_pipeline_e2e.py",
    ),
    (
        "chunking is no longer deterministic",
        SCRIPTS / "chunker.py",
        '        "content_hash": sha256_text(content),',
        '        "content_hash": sha256_text(content + str(__import__("random").random())),',
        "tests/test_pipeline_e2e.py",
    ),
    (
        "inventory drops the unsupported list",
        SCRIPTS / "kb_pipeline.py",
        "            unsupported.append({\"path\": str(p), \"suffix\": suffix, \"size_bytes\": p.stat().st_size})",
        "            pass",
        "tests/test_ingest_stages.py",
    ),
    (
        "pdf parsing yields no page units",
        SCRIPTS / "parsers.py",
        "    doc = fitz.open(str(path))",
        "    doc = fitz.open(str(path))\n    return ParsedDocument(doc_id=\"x\", source_path=str(path), text=\"\", units=[], unit_type=\"page\")",
        "tests/test_ingest_stages.py",
    ),
]


def main() -> int:
    results = []
    for name, path, old, new, target in MUTATIONS:
        original = path.read_text(encoding="utf-8")
        if old not in original:
            results.append((name, "SKIP: anchor not found", 0))
            continue
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", target, "-q", "-p", "no:cacheprovider"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            failed = "failed" in (proc.stdout or "")
            summary = [l for l in (proc.stdout or "").splitlines() if "passed" in l or "failed" in l]
            results.append((name, summary[-1] if summary else "(no summary)", proc.returncode))
        finally:
            path.write_text(original, encoding="utf-8")
    for name, summary, code in results:
        verdict = "CAUGHT" if code != 0 else "NOT CAUGHT"
        print(f"{verdict:11s} {name:32s} rc={code}  {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
