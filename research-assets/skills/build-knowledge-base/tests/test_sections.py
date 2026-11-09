"""Section building: the consumer of the heading gate.

`detect_heading_level` only classifies a single line. `build_sections` is what
actually produces `heading_path`, so nesting mistakes live here: a level-1
"1. 方便性" inside a chapter is an enumerated point, not a new chapter, and a
heading is kept as the section's first paragraph.
"""

from __future__ import annotations

from chunker import build_sections


def para(text: str, kind: str = "text", page: int = 1) -> dict:
    return {"text": text, "kind": kind, "page_start": page, "page_end": page}


def paths(sections: list[dict]) -> list[list[str]]:
    return [section["path"] for section in sections]


def test_nested_headings_build_a_path() -> None:
    sections = build_sections(
        [
            para("第1章 绪论", "heading"),
            para("正文一。"),
            para("1.1 基本概念", "heading"),
            para("正文二。"),
            para("1.1.1 定义", "heading"),
            para("正文三。"),
        ]
    )
    assert ["第1章 绪论"] in paths(sections)
    assert ["第1章 绪论", "1.1 基本概念"] in paths(sections)
    assert ["第1章 绪论", "1.1 基本概念", "1.1.1 定义"] in paths(sections)


def test_sibling_heading_replaces_the_previous_one() -> None:
    sections = build_sections(
        [
            para("第2章 进程", "heading"),
            para("2.1 概念", "heading"),
            para("正文。"),
            para("2.2 状态", "heading"),
            para("正文。"),
        ]
    )
    assert ["第2章 进程", "2.2 状态"] in paths(sections)
    assert not any(path[-1] == "2.1 概念" and len(path) > 2 for path in paths(sections))


def test_heading_is_kept_as_the_first_paragraph() -> None:
    sections = build_sections([para("1.1 目标", "heading"), para("正文。")])
    first = sections[0]["paragraphs"][0]
    assert first["kind"] == "heading"
    assert first["text"] == "1.1 目标"


def test_enumerated_point_stays_inside_the_chapter() -> None:
    # "1. 方便性" looks like a level-1 heading but is a numbered point in a list.
    sections = build_sections(
        [
            para("第1章 绪论", "heading"),
            para("1. 方便性", "heading"),
            para("正文。"),
        ]
    )
    assert len(sections) == 1
    assert [p["text"] for p in sections[0]["paragraphs"]].count("1. 方便性") == 1


def test_body_line_starting_with_digits_does_not_start_a_section() -> None:
    sections = build_sections(
        [
            para("第3章 存储", "heading"),
            para("100 个数据中心分布于北美、欧洲、亚洲、南美和澳大利亚。", "heading"),
            para("正文。"),
        ]
    )
    assert len(sections) == 1
    assert sections[0]["path"] == ["第3章 存储"]
