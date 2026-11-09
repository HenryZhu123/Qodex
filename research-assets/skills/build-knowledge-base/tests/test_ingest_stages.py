"""Stage contracts for inventory, parse and verify.

The PDF case generates its own two-page file with PyMuPDF at test time. Committing
a binary fixture is not an option (``*.pdf`` is ignored) and a generated file
keeps the text, page count and encoding under the test's control.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from kb_pipeline import inventory, verify
from parsers import UnsupportedFormatError, parse_document

PAGE_ONE = (
    "第1章 操作系统引论\n\n1.1 操作系统的目标\n\n"
    "操作系统是配置在计算机硬件上的第一层软件，负责管理硬件设备并提高它们的利用率，"
    "同时为用户和应用程序提供一个简单接口。"
)
PAGE_TWO = (
    "第2章 进程管理\n\n2.1 进程的基本概念\n\n"
    "进程是程序在一个数据集合上运行的过程，它是系统进行资源分配和调度的一个独立单位。"
)


def make_pdf(path: Path) -> Path:
    import fitz

    doc = fitz.open()
    for text in (PAGE_ONE, PAGE_TWO):
        page = doc.new_page()
        page.insert_text((72, 96), text, fontname="china-s", fontsize=11)
    doc.save(path)
    doc.close()
    return path


# ----------------------------- inventory -----------------------------


def test_inventory_lists_supported_files(tmp_dir: Path) -> None:
    (tmp_dir / "a.txt").write_text("正文。" * 50, encoding="utf-8")
    make_pdf(tmp_dir / "b.pdf")
    (tmp_dir / "skip.bin").write_bytes(b"\x00\x01")

    manifest = inventory(tmp_dir, tmp_dir / "run")
    formats = {entry["format"] for entry in manifest["documents"]}
    assert formats == {"txt", "pdf"}
    assert len(manifest["documents"]) == 2
    assert manifest["unsupported"], "unsupported files are recorded, not silently dropped"
    for entry in manifest["documents"]:
        assert entry["doc_id"] and entry["source_hash"] and entry["size_bytes"] > 0


def test_inventory_rejects_a_missing_input(tmp_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        inventory(tmp_dir / "nope.txt", tmp_dir / "run")


# ----------------------------- parse -----------------------------


def test_parse_pdf_produces_page_units(tmp_dir: Path) -> None:
    pdf = make_pdf(tmp_dir / "sample.pdf")
    parsed = parse_document(pdf)
    assert parsed.unit_type == "page"
    assert len(parsed.units) == 2
    assert "操作系统" in parsed.text
    assert "进程" in parsed.text
    payload = parsed.to_dict()
    assert payload["doc_id"]
    assert payload["unit_count"] == 2


def test_parse_text_counts_lines(tmp_dir: Path) -> None:
    source = tmp_dir / "note.txt"
    source.write_text("\n".join(f"第{i}行 内容" for i in range(1, 21)), encoding="utf-8")
    parsed = parse_document(source)
    assert parsed.unit_type == "line"
    assert len(parsed.units) == 20


def test_parse_rejects_unknown_suffix(tmp_dir: Path) -> None:
    bad = tmp_dir / "x.bin"
    bad.write_bytes(b"\x00")
    with pytest.raises(UnsupportedFormatError):
        parse_document(bad)


# ----------------------------- verify -----------------------------


def build_index(tmp_dir: Path) -> Path:
    """Create a minimal ingested run directory without invoking the CLI."""
    from chunker import chunk_document
    from store import init_db, insert_chunks, insert_document

    run_dir = tmp_dir / "run"
    run_dir.mkdir()
    text = PAGE_ONE + "\n\n" + PAGE_TWO
    doc = {"doc_id": "d1", "text": text, "language": "zh", "metadata": {}, "title": "样例"}
    plan = {
        "mode": "hierarchical",
        "target_chars": 200,
        "max_chars": 300,
        "min_chars": 50,
        "overlap_chars": 20,
    }
    chunks = chunk_document(doc, plan)
    conn = init_db(run_dir / "kb.sqlite")
    insert_document(
        conn,
        {
            "doc_id": "d1",
            "source_path": "sample.pdf",
            "source_hash": "abc",
            "title": "样例",
            "format": "pdf",
            "parse_method": "pymupdf",
            "unit_type": "page",
            "unit_count": 2,
            "char_count": len(text),
            "language": "zh",
            "metadata": {},
        },
    )
    insert_chunks(conn, chunks)
    conn.close()
    return run_dir


def test_verify_reports_stats_and_probes(tmp_dir: Path) -> None:
    run_dir = build_index(tmp_dir)
    report = verify(run_dir, top_k=2)

    assert report["stats"]["chunks"] > 0
    assert report["probes"], "verify must probe real queries"
    assert any(probe["hits"] > 0 for probe in report["probes"])

    written = json.loads((run_dir / "verification_report.json").read_text(encoding="utf-8"))
    assert written["stats"]["chunks"] == report["stats"]["chunks"]
    assert (run_dir / "verification_report.md").is_file()


def test_verify_without_database_raises(tmp_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify(tmp_dir / "empty-run")


def test_verify_stats_match_the_tables(tmp_dir: Path) -> None:
    run_dir = build_index(tmp_dir)
    report = verify(run_dir)
    conn = sqlite3.connect(f"file:{run_dir / 'kb.sqlite'}?mode=ro", uri=True)
    try:
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        indexed = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    finally:
        conn.close()
    assert report["stats"]["chunks"] == chunks
    assert indexed <= chunks
