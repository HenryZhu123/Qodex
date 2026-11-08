#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ingest reference questions into SQLite and export JSONL.

Schema (one row per question):
  reference_questions   question-level record with answer, explanation, anchors
  reference_questions_fts  FTS5 index for stem + explanation search

Records are produced by scripts/refq/parse_408.py (reference_questions.jsonl).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import sanitize_obj, tokenize_for_fts  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_questions (
    record_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    year INTEGER,
    exam_title TEXT,
    question_no INTEGER,
    subject TEXT,
    question_type TEXT,
    stem TEXT NOT NULL,
    stem_norm TEXT,
    options_json TEXT,
    options_complete INTEGER,
    standard_answer TEXT,
    answer_available INTEGER,
    explanation TEXT,
    answer_method TEXT,
    trust_level TEXT,
    knowledge_points_json TEXT,
    anchors_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_refq_year ON reference_questions(year);
CREATE INDEX IF NOT EXISTS idx_refq_subject ON reference_questions(subject);
CREATE INDEX IF NOT EXISTS idx_refq_answer ON reference_questions(standard_answer);
CREATE INDEX IF NOT EXISTS idx_refq_stem_norm ON reference_questions(stem_norm);

CREATE VIRTUAL TABLE IF NOT EXISTS reference_questions_fts USING fts5(
    stem_tokens,
    explanation_tokens,
    record_id UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
"""


def load_records(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def insert_records(conn: sqlite3.Connection, records: list[dict]) -> int:
    count = 0
    for rec in records:
        rec = sanitize_obj(rec)
        conn.execute(
            """
            INSERT OR REPLACE INTO reference_questions (
                record_id, source, year, exam_title, question_no, subject,
                question_type, stem, stem_norm, options_json, options_complete,
                standard_answer, answer_available, explanation, answer_method,
                trust_level, knowledge_points_json, anchors_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec["record_id"],
                rec["source"],
                rec.get("year"),
                rec.get("exam_title"),
                rec.get("question_no"),
                rec.get("subject"),
                rec.get("question_type"),
                rec.get("stem", ""),
                rec.get("stem_norm"),
                json.dumps(rec.get("options", {}), ensure_ascii=False),
                1 if rec.get("options_complete") else 0,
                rec.get("standard_answer"),
                1 if rec.get("answer_available") else 0,
                rec.get("explanation"),
                rec.get("answer_method"),
                rec.get("trust_level"),
                json.dumps(rec.get("knowledge_points", []), ensure_ascii=False),
                json.dumps(rec.get("anchors", {}), ensure_ascii=False),
            ),
        )
        conn.execute(
            "DELETE FROM reference_questions_fts WHERE record_id = ?",
            (rec["record_id"],),
        )
        conn.execute(
            "INSERT INTO reference_questions_fts (stem_tokens, explanation_tokens, record_id) "
            "VALUES (?, ?, ?)",
            (
                tokenize_for_fts(rec.get("stem", "")),
                tokenize_for_fts(rec.get("explanation") or ""),
                rec["record_id"],
            ),
        )
        count += 1
    conn.commit()
    return count


def stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM reference_questions").fetchone()[0]
    with_answer = conn.execute(
        "SELECT COUNT(*) FROM reference_questions WHERE answer_available = 1"
    ).fetchone()[0]
    complete = conn.execute(
        "SELECT COUNT(*) FROM reference_questions WHERE options_complete = 1"
    ).fetchone()[0]
    by_year = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT year, COUNT(*) FROM reference_questions GROUP BY year ORDER BY year"
        ).fetchall()
    }
    by_subject = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT subject, COUNT(*) FROM reference_questions GROUP BY subject"
        ).fetchall()
    }
    return {
        "total": total,
        "with_answer": with_answer,
        "options_complete": complete,
        "by_year": by_year,
        "by_subject": by_subject,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest reference questions.")
    parser.add_argument("--records", required=True, help="reference_questions.jsonl")
    parser.add_argument("--db", required=True, help="target sqlite file")
    parser.add_argument("--out", default=None, help="optional export dir for jsonl copy")
    args = parser.parse_args()

    records_path = Path(args.records)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    records = load_records(records_path)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    inserted = insert_records(conn, records)
    report = stats(conn)
    conn.close()

    print(json.dumps({"inserted": inserted, **report}, ensure_ascii=False, indent=2))

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "reference_questions.jsonl").write_text(
            records_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (out_dir / "reference_questions_stats.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
