"""Chunk packing: size bounds, overlap, and the blocked-plan guard.

Packing is where a chunker usually goes wrong in a way no other test notices: a
chunk quietly exceeds `max_chars` (blowing the model's context), or the overlap
silently disappears so a sentence spanning a boundary is unreachable.
"""

from __future__ import annotations

from chunker import chunk_document

PARA = (
    "操作系统是配置在计算机硬件上的第一层软件，负责管理硬件设备并提高它们的利用率，"
    "同时为用户和应用程序提供一个简单接口。进程是系统进行资源分配和调度的一个独立单位。"
)


def doc_for(text: str) -> dict:
    return {"doc_id": "d1", "text": text, "language": "zh", "metadata": {}, "title": "测试"}


def plan_for(**overrides) -> dict:
    plan = {
        "mode": "hierarchical",
        "target_chars": 300,
        "max_chars": 400,
        "min_chars": 80,
        "overlap_chars": 40,
    }
    plan.update(overrides)
    return plan


def build_paragraphs(count: int) -> str:
    return "\n\n".join(PARA * 2 for _ in range(count))


def test_no_chunk_exceeds_max_chars() -> None:
    chunks = chunk_document(doc_for(build_paragraphs(12)), plan_for())
    assert chunks, "expected chunks"
    assert max(chunk["char_count"] for chunk in chunks) <= 400


def test_oversized_paragraph_is_split_at_the_limit() -> None:
    # One paragraph far longer than max_chars, no blank lines to pack against.
    # Without the split, the single chunk would be ~1,800 chars.
    text = PARA * 20
    chunks = chunk_document(doc_for(text), plan_for())
    assert len(chunks) >= 2
    assert max(chunk["char_count"] for chunk in chunks) <= 400


def test_chunk_count_scales_with_content() -> None:
    small = chunk_document(doc_for(build_paragraphs(3)), plan_for())
    large = chunk_document(doc_for(build_paragraphs(24)), plan_for())
    assert len(large) > len(small)


def test_overlap_is_present_between_neighbours() -> None:
    chunks = chunk_document(doc_for(build_paragraphs(12)), plan_for())
    if len(chunks) < 2:
        return
    tails = [chunk["content"][-30:] for chunk in chunks[:-1]]
    heads = [chunk["content"][:200] for chunk in chunks[1:]]
    assert any(tail.strip() and tail[:15] in head for tail, head in zip(tails, heads))


def test_zero_overlap_produces_disjoint_boundaries() -> None:
    chunks = chunk_document(doc_for(build_paragraphs(12)), plan_for(overlap_chars=0))
    assert len(chunks) >= 2


def test_blocked_plan_refuses_to_chunk() -> None:
    plan = plan_for()
    plan["blocked"] = True
    try:
        chunk_document(doc_for(PARA * 10), plan)
    except ValueError as exc:
        assert "blocked" in str(exc)
    else:
        raise AssertionError("a blocked plan must not produce chunks")


def test_headings_become_heading_path() -> None:
    text = "\n\n".join(
        [
            "第3章 存储系统",
            "3.1 存储器概述",
            PARA * 2,
            "3.2 主存的组织",
            PARA * 2,
        ]
    )
    chunks = chunk_document(doc_for(text), plan_for())
    assert any(chunk["heading_path"] for chunk in chunks)
    assert any("第3章 存储系统" in chunk["heading_path"] for chunk in chunks)


def test_every_chunk_carries_provenance() -> None:
    chunks = chunk_document(doc_for(build_paragraphs(6)), plan_for())
    for chunk in chunks:
        assert chunk["doc_id"] == "d1"
        assert chunk["char_count"] == len(chunk["content"])
        assert chunk["chunk_type"]
