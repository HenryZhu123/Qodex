"""End-to-end: the CLI chain must run from a raw file to a queryable index.

Unit tests prove the pieces; this proves they are wired together. Two scenarios:

* a small plain-text document taken through inventory -> parse -> sample ->
  chunk -> ingest -> verify, which must end with a working query;
* re-chunking an already parsed book twice, which must produce identical chunk
  hashes (idempotency) and the same index size as the shipped build.

The second scenario reads the real parsed artefacts. It is skipped when they are
absent so a fresh checkout still runs the rest of the suite.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "scripts"
PIPELINE = SCRIPTS / "kb_pipeline.py"
KB_BOOKS = Path(r"D:\Code\hku\LLM\kb_review\books")

SAMPLE_TEXT = "\n\n".join(
    [
        "第1章 操作系统引论",
        "1.1 操作系统的目标",
        "操作系统是配置在计算机硬件上的第一层软件，负责管理硬件设备并提高利用率，"
        "同时为用户和应用程序提供一个简单接口。它在计算机系统中占据着重要的地位。",
        "1.2 操作系统的作用",
        "操作系统通过进程管理、存储管理、文件管理和设备管理来实现对硬件资源的抽象，"
        "并为上层应用提供统一的服务接口，从而显著提高系统的资源利用率。",
        "第2章 进程管理",
        "2.1 进程的基本概念",
        "进程是程序在一个数据集合上运行的过程，它是系统进行资源分配和调度的一个独立单位。"
        "进程具有动态性、并发性和独立性等基本特征。",
        "2.2 进程的状态",
        "进程在运行过程中会经历就绪、运行和阻塞三种基本状态，状态之间按照调度与事件的发生相互转换。",
    ]
)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIPELINE), *args],
        cwd=SCRIPTS,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_small_document_reaches_a_queryable_index(tmp_dir: Path) -> None:
    source = tmp_dir / "sample.txt"
    source.write_text(SAMPLE_TEXT, encoding="utf-8")
    run_dir = tmp_dir / "run"

    for command in (
        ("inventory", "--input", str(source), "--out", str(run_dir)),
        ("parse", "--input", str(source), "--out", str(run_dir)),
        ("sample", "--out", str(run_dir)),
        ("chunk", "--out", str(run_dir)),
        ("ingest", "--out", str(run_dir)),
        ("verify", "--out", str(run_dir)),
    ):
        result = run_cli(*command)
        assert result.returncode == 0, f"{command[0]} failed:\n{result.stdout}\n{result.stderr}"

    db = run_dir / "kb.sqlite"
    assert db.is_file(), "ingest produced no database"

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        indexed = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    finally:
        conn.close()
    assert chunks > 0
    assert 0 < indexed <= chunks

    query = run_cli("query", "--db", str(db), "--q", "进程 调度", "--top-k", "3")
    assert query.returncode == 0
    assert "进程" in query.stdout


def test_chunking_the_same_input_twice_is_stable(tmp_dir: Path) -> None:
    source = tmp_dir / "sample.txt"
    source.write_text(SAMPLE_TEXT, encoding="utf-8")
    run_dir = tmp_dir / "run"
    run_cli("inventory", "--input", str(source), "--out", str(run_dir))
    run_cli("parse", "--input", str(source), "--out", str(run_dir))
    run_cli("sample", "--out", str(run_dir))

    hashes: list[list[str]] = []
    for _ in range(2):
        result = run_cli("chunk", "--out", str(run_dir))
        assert result.returncode == 0, result.stderr
        lines = (run_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines if line.strip()]
        hashes.append(sorted(row["content_hash"] for row in rows))
    assert hashes[0] == hashes[1]


@pytest.mark.skipif(
    not (KB_BOOKS / "data_structure" / "parsed").is_dir(),
    reason="parsed artefacts of the shipped books are not available",
)
def test_rebuild_of_a_parsed_book_keeps_the_golden_shape(tmp_dir: Path) -> None:
    source_dir = KB_BOOKS / "data_structure"
    run_dir = tmp_dir / "ds"
    run_dir.mkdir()
    for item in source_dir.iterdir():
        if item.name.startswith("kb"):
            continue
        target = run_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    result = run_cli("chunk", "--out", str(run_dir))
    assert result.returncode == 0, result.stderr
    lines = (run_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    assert 400 <= len(rows) <= 425, f"expected ~411 chunks, got {len(rows)}"

    result = run_cli("ingest", "--out", str(run_dir), "--db", str(run_dir / "kb.sqlite"))
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(f"file:{run_dir / 'kb.sqlite'}?mode=ro", uri=True)
    try:
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        indexed = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        headings = [row[0] for row in conn.execute("SELECT heading_path FROM chunks")]
    finally:
        conn.close()

    assert chunks == len(rows)
    assert indexed < chunks, "fragments must be kept out of the index"
    assert not any("#" in (heading or "") for heading in headings)
