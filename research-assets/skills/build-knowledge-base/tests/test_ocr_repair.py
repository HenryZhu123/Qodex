"""OCR repairs: fix shape-unique errors and leave legitimate text alone.

The distinction matters: 千 appears 519 times in the corpus but is wrong only in a
few collocations, so the rules are written as fixed bigrams rather than character
substitutions.
"""

from __future__ import annotations

import pytest

from textclean import repair_ocr

FIXED = [
    ("对千许多不同类型的攻击", "对于许多不同类型的攻击"),
    ("由千这种设计", "由于这种设计"),
    ("关千这个问题", "关于这个问题"),
    ("至千是否可行", "至于是否可行"),
    ("千是我们就", "于是我们就"),
    ("巳经完成", "已经完成"),
    ("而巳。", "而已。"),
    ("在某个阙值之上", "在某个阈值之上"),
    ("阔值为一半", "阈值为一半"),
    ("主流橾作系统", "主流操作系统"),
    ("中｀在接下来", "中在接下来"),
    ("<!-- image-->正文开始", "正文开始"),
    ("&lt;gel-config&gt;", "<gel-config>"),
    ("••••••", ""),
]

UNTOUCHED = [
    "以千计的成本",
    "成千上万的用户",
    "数千个分组",
    "开阔的视野",
    "宫阙",
    "TCP/IP 协议",
]


@pytest.mark.parametrize(("before", "after"), FIXED)
def test_repairs(before: str, after: str) -> None:
    assert repair_ocr(before)["text"] == after


@pytest.mark.parametrize("text", UNTOUCHED)
def test_leaves_legitimate_text_alone(text: str) -> None:
    assert repair_ocr(text)["text"] == text


def test_reports_what_changed() -> None:
    result = repair_ocr("对千这｀种情况")
    assert result["counts"]["对千→对于"] == 1
    assert result["counts"]["noise_chars"] == 1


def test_no_change_returns_empty_counts() -> None:
    result = repair_ocr("操作系统是硬件之上的第一层软件。")
    assert result["counts"] == {}
    assert result["text"] == "操作系统是硬件之上的第一层软件。"


# ----------------------- database audit path -----------------------


def make_db(path):
    import sqlite3

    from store import init_db, insert_chunks, insert_document

    conn = init_db(path)
    insert_document(
        conn,
        {
            "doc_id": "d1",
            "source_path": "t.pdf",
            "source_hash": "h",
            "title": "t",
            "format": "pdf",
            "parse_method": "pymupdf",
            "unit_type": "page",
            "unit_count": 1,
            "char_count": 100,
            "language": "zh",
            "metadata": {},
        },
    )
    insert_chunks(
        conn,
        [
            {
                "chunk_id": "d1:00001",
                "doc_id": "d1",
                "chunk_index": 1,
                "content": "系统对千这种请求会立即响应。",
                "content_hash": "old",
                "char_count": 16,
                "chunk_type": "hierarchical",
                "heading_path": ["第1章"],
                "page_start": 1,
                "page_end": 1,
                "metadata": {},
            }
        ],
    )
    return conn


def test_dry_run_reports_without_writing(tmp_dir) -> None:
    import sqlite3

    from textclean import audit_databases

    db = tmp_dir / "kb.sqlite"
    make_db(db).close()
    assert audit_databases([str(db)], apply=False) == 0

    conn = sqlite3.connect(db)
    content = conn.execute("SELECT content FROM chunks").fetchone()[0]
    conn.close()
    assert "对千" in content, "a dry run must not modify the database"


def test_apply_rewrites_content_and_hash(tmp_dir) -> None:
    import sqlite3

    from textclean import audit_databases

    db = tmp_dir / "kb.sqlite"
    make_db(db).close()
    assert audit_databases([str(db)], apply=True) == 0

    conn = sqlite3.connect(db)
    content, digest, length = conn.execute(
        "SELECT content, content_hash, char_count FROM chunks"
    ).fetchone()
    conn.close()
    assert "对于" in content
    assert digest != "old"
    assert length == len(content)
