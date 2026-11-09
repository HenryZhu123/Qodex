"""Chunk size must respect the hard limit even when a "sentence" is huge.

A table row or a code line can be thousands of characters with no sentence
punctuation, so splitting on sentences alone never brings it under the limit.
"""

from __future__ import annotations

from chunker import chunk_document

PLAN = {
    "mode": "hierarchical",
    "target_chars": 300,
    "max_chars": 400,
    "min_chars": 80,
    "overlap_chars": 40,
}


def doc_for(text: str) -> dict:
    return {"doc_id": "d1", "text": text, "language": "zh", "metadata": {}, "title": "测试"}


def test_single_giant_sentence_is_split() -> None:
    # No sentence break at all, far beyond max_chars.
    text = "操作系统管理硬件资源并为应用提供服务" * 300
    assert len(text) > 5000
    chunks = chunk_document(doc_for(text), PLAN)
    assert len(chunks) >= 8
    assert max(chunk["char_count"] for chunk in chunks) <= PLAN["max_chars"]


def test_long_table_row_is_split() -> None:
    row = "|".join(f"第{i}行数据" * 20 for i in range(1, 40))
    chunks = chunk_document(doc_for(row), PLAN)
    assert max(chunk["char_count"] for chunk in chunks) <= PLAN["max_chars"]


def test_normal_paragraphs_are_not_over_split() -> None:
    text = "\n\n".join("这是正常长度的段落，包含若干句子。它应当在目标长度附近被合并。" for _ in range(6))
    chunks = chunk_document(doc_for(text), PLAN)
    assert 1 <= len(chunks) <= 6


def test_split_pieces_keep_provenance() -> None:
    text = "很长的无标点文本" * 400
    chunks = chunk_document(doc_for(text), PLAN)
    for chunk in chunks:
        assert chunk["doc_id"] == "d1"
        assert chunk["chunk_id"].startswith("d1:")
        assert chunk["char_count"] == len(chunk["content"])


def test_overlap_cannot_push_a_chunk_over_the_limit() -> None:
    # Regression: emit() keeps the last paragraph for overlap, then the next
    # paragraph was appended without re-checking, so chunks reached max + overlap.
    plan = dict(PLAN, target_chars=1500, max_chars=1540, min_chars=200, overlap_chars=100)
    paragraph = "这是接近上限的段落，用来触发边界情况。" * 60  # ~1,080 chars
    text = "\n\n".join([paragraph] * 12)
    chunks = chunk_document(doc_for(text), plan)
    assert chunks
    assert max(chunk["char_count"] for chunk in chunks) <= plan["max_chars"]
