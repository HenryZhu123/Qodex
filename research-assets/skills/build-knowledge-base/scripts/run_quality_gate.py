#!/usr/bin/env python3
"""Quality gate for a built knowledge base.

Runs the measurable checks on real indexes and prints one PASS/FAIL per gate plus
a final verdict. Intended to be run after any rebuild; it reads the databases in
place and never writes to them.

Gates:
  G1 index consistency   fts rows == chunks - fragments
  G2 heading hygiene     no heading segment that is really body text
  G3 heading duplication heading words must not lead the token stream
  G4 text hygiene        mojibake and running-watermark leakage
  G5 coverage            per-book chunk counts stay near the golden values
  G6 retrieval quality   recall@2 on the labelled query set (optional, slower)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from store import is_stub, strip_leading_heading  # noqa: E402

KB_ROOT = Path(r"D:\Code\hku\LLM\kb_review\books")
EVAL_DIR = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\retrieval_eval")

GOLDEN_CHUNKS = {
    ("data_structure", "kb.sqlite"): 411,
    ("computer_organization", "kb.sqlite"): 554,
    ("operating_system", "kb.sqlite"): 591,
    ("computer_network", "kb.sqlite"): 796,
    ("computer_network", "kb_8th.sqlite"): 204,
}

BODY_PUNCT = re.compile(r"[。，；！？]")
CODE_MARK = re.compile(r"(/\*|//|#include|wake_up|__)")
BINARY = re.compile(r"^[01\s]{8,}$")
NUMERIC_ONLY = re.compile(r"^[\d\s.]+$")
MOJIBAKE = ["锟斤拷", "烫烫烫", "屯屯屯", "Ã", "Â", "â€", "\ufffd"]
# Running watermarks and scanner stamps only. Common Chinese words such as 仅供
# appear in ordinary prose and must not be counted.
WATERMARK = ["z-library", "1lib.sk", "z-lib.sk", "扫描全能王", "CS 扫描全能王"]

SEGMENT_MAX = 48
# Strict hand labels measured 0.8182 on the 2026.11.1 build; the floor sits one
# step below so a regression shows up without failing on ordinary rebuild noise.
RECALL_FLOOR = 0.78


def bad_segment(segment: str) -> bool:
    s = segment.strip()
    if not s:
        return False
    if len(s) > SEGMENT_MAX or BODY_PUNCT.search(s) or CODE_MARK.search(s):
        return True
    return bool(BINARY.match(s) or NUMERIC_ONLY.match(s))


def indexed_dbs() -> list[Path]:
    return sorted(KB_ROOT.rglob("kb*.sqlite"))


def gate_index_consistency(dbs: list[Path]) -> dict:
    total_chunks = total_indexed = expected = 0
    detail = {}
    for db in dbs:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT c.content, c.heading_path, COALESCE(d.language, 'zh') AS language "
                "FROM chunks c LEFT JOIN documents d ON d.doc_id = c.doc_id"
            ).fetchall()
            indexed = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        finally:
            conn.close()
        fragments = 0
        for content, heading, language in rows:
            path = [p.strip() for p in (heading or "").split(">") if p.strip()]
            if is_stub(strip_leading_heading(content or "", path), language):
                fragments += 1
        total_chunks += len(rows)
        total_indexed += indexed
        expected += len(rows) - fragments
        detail[db.parent.name] = {
            "chunks": len(rows),
            "indexed": indexed,
            "fragments": fragments,
            "mismatch": (len(rows) - fragments) - indexed,
        }
    return {
        "pass": total_indexed == expected,
        "chunks": total_chunks,
        "indexed": total_indexed,
        "expected_indexed": expected,
        "detail": detail,
    }


def gate_heading_hygiene(dbs: list[Path]) -> dict:
    total = bad = 0
    samples: list[str] = []
    for db in dbs:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT heading_path FROM chunks").fetchall()
        finally:
            conn.close()
        for (heading,) in rows:
            total += 1
            segments = [s for s in (heading or "").split(">") if s.strip()]
            if any(bad_segment(s) for s in segments):
                bad += 1
                if len(samples) < 3:
                    samples.append(max(segments, key=len)[:70])
    ratio = bad / max(1, total)
    return {"pass": ratio <= 0.005, "chunks": total, "bad": bad,
            "ratio": round(ratio, 4), "samples": samples}


def gate_heading_duplication(dbs: list[Path], sample_size: int = 300) -> dict:
    conn = sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True)
    checked = duplicated = 0
    samples: list[str] = []
    try:
        for db in dbs:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = c.execute(
                    """SELECT c.content, c.heading_path, f.content_tokens
                       FROM chunks c JOIN chunks_fts f ON f.chunk_id = c.chunk_id
                       LIMIT ?""",
                    (sample_size,),
                ).fetchall()
            finally:
                c.close()
            for content, heading, tokens in rows:
                path = [p.strip() for p in (heading or "").split(">") if p.strip()]
                if not path or not tokens:
                    continue
                checked += 1
                title = path[-1].lstrip("#").strip()
                head = (content or "").split("\n", 1)[0].strip()
                if head == title and tokens.startswith(title.split()[0] if title.split() else title):
                    duplicated += 1
                    if len(samples) < 3:
                        samples.append(title[:60])
    finally:
        conn.close()
    ratio = duplicated / max(1, checked)
    return {"pass": ratio <= 0.02, "checked": checked, "duplicated": duplicated,
            "ratio": round(ratio, 4), "samples": samples}


def gate_text_hygiene(dbs: list[Path]) -> dict:
    total_chars = mojibake = watermark = 0
    samples: list[str] = []
    for db in dbs:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT content FROM chunks").fetchall()
        finally:
            conn.close()
        for (content,) in rows:
            text = content or ""
            total_chars += len(text)
            hits = sum(text.count(pattern) for pattern in MOJIBAKE)
            mojibake += hits
            wm = sum(text.count(pattern) for pattern in WATERMARK)
            watermark += wm
            if (hits or wm) and len(samples) < 3:
                samples.append(text[:70].replace("\n", " "))
    moji_ratio = mojibake / max(1, total_chars) * 1000
    return {
        "pass": moji_ratio <= 0.5 and watermark == 0,
        "chars": total_chars,
        "mojibake_hits": mojibake,
        "mojibake_per_1k_chars": round(moji_ratio, 3),
        "watermark_hits": watermark,
        "samples": samples,
    }


def gate_coverage(dbs: list[Path]) -> dict:
    counts: dict[str, int] = {}
    deviations: dict[str, float] = {}
    ok = True
    for db in dbs:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        finally:
            conn.close()
        key = (db.parent.name, db.name)
        label = f"{db.parent.name}/{db.name}"
        counts[label] = n
        golden = GOLDEN_CHUNKS.get(key)
        if golden is None:
            continue
        delta = abs(n - golden) / golden
        deviations[label] = round(delta, 4)
        ok = ok and delta <= 0.05
    return {"pass": ok, "counts": counts, "deviation": deviations}


def gate_retrieval() -> dict:
    # Strict labels: every top-2 candidate was read and judged against the query.
    # The older metrics.json inferred relevance from rank, which overstates recall.
    script = EVAL_DIR / "score_v3.py"
    if not script.is_file():
        return {"pass": None, "reason": "strict evaluator not found"}
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        return {"pass": False, "reason": "evaluator failed", "stderr": proc.stderr[-300:]}
    metrics = json.loads((EVAL_DIR / "metrics_v3.json").read_text(encoding="utf-8"))
    recall = metrics["recall@2"]
    return {
        "pass": recall >= RECALL_FLOOR,
        "recall@1": metrics["recall@1"],
        "recall@2": recall,
        "negative_hits@2": metrics["negative_hits@2"],
        "floor": RECALL_FLOOR,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-retrieval", action="store_true")
    args = parser.parse_args()

    dbs = indexed_dbs()
    if not dbs:
        print("no indexes found", file=sys.stderr)
        return 2

    gates = {
        "G1_index_consistency": gate_index_consistency(dbs),
        "G2_heading_hygiene": gate_heading_hygiene(dbs),
        "G3_heading_duplication": gate_heading_duplication(dbs),
        "G4_text_hygiene": gate_text_hygiene(dbs),
        "G5_coverage": gate_coverage(dbs),
    }
    if not args.skip_retrieval:
        gates["G6_retrieval_quality"] = gate_retrieval()

    failed = [name for name, result in gates.items() if result.get("pass") is False]
    print(json.dumps({"gates": gates, "failed": failed, "verdict": "PASS" if not failed else "FAIL"},
                     ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
