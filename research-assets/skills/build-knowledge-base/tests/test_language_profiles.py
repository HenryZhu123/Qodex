"""Language profiles: typography must not be hardcoded to Chinese.

The bug these tests lock down is silent: `is_stub` decides whether a chunk is a
fragment, and fragments are kept out of the index. With Chinese punctuation only,
every English paragraph under 120 characters counted as a fragment, so an English
medical or biology book would have lost most of its searchable content without an
error anywhere.
"""

from __future__ import annotations

import pytest

from chunker import _looks_like_title, build_sections, detect_heading_level
from profiles import get_profile
from store import is_stub
from utils import is_heading_line


# ----------------------------- fragments -----------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The transport layer provides logical communication between application processes.",
        "The cell is the basic unit of life.",
        "Mitochondria generate most of the cell's supply of adenosine triphosphate.",
    ],
)
def test_english_sentences_are_not_fragments(text: str) -> None:
    assert is_stub(text, "en") is False


@pytest.mark.parametrize(
    "text",
    ["Figure 3.2", "Table 4.1", "3.2.1", "H2SO4", "mg/kg"],
)
def test_english_labels_are_fragments(text: str) -> None:
    assert is_stub(text, "en") is True


def test_chinese_behaviour_is_unchanged() -> None:
    assert is_stub("虚拟存储器", "zh") is True
    assert is_stub("进程是程序的一次执行过程，它是系统进行资源分配和调度的一个独立单位。", "zh") is False


# ----------------------------- headings -----------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Chapter 3  Transport Layer",
        "Chapter 12: Pharmacokinetics of Monoclonal Antibodies in Pediatric Populations",
        "Part II  Mechanisms of Disease",
        "Section 4.2  Cellular Respiration",
        "Appendix A  Statistical Tables",
    ],
)
def test_english_headings_are_recognised(line: str) -> None:
    assert is_heading_line(line, "en") is True
    assert detect_heading_level(line, "en") is not None


def test_long_english_title_is_accepted_but_long_chinese_is_not() -> None:
    long_english = "Chapter 12: Pharmacokinetics of Monoclonal Antibodies in Pediatric Populations"
    assert _looks_like_title(long_english, "en") is True
    # The same character count is far too long for a Chinese heading.
    assert _looks_like_title("一" * 60, "zh") is False


def test_english_prose_is_not_a_heading() -> None:
    assert is_heading_line("The cell is the basic unit of life.", "en") is False
    assert detect_heading_level("The cell is the basic unit of life.", "en") is None


def test_chinese_headings_still_work() -> None:
    for line in ["第3章 传输层", "1.2 基本概念", "一、简答题"]:
        assert is_heading_line(line, "zh") is True
        assert detect_heading_level(line, "zh") is not None


# ----------------------------- structure -----------------------------


def test_english_sections_nest() -> None:
    paragraphs = [
        {"text": "Chapter 1  Introduction", "kind": "heading", "page_start": 1, "page_end": 1},
        {"text": "The cell is the basic unit of life.", "kind": "text", "page_start": 1, "page_end": 1},
        {"text": "Section 1.1  Scope", "kind": "heading", "page_start": 1, "page_end": 1},
        {"text": "This chapter explains the scope of the book.", "kind": "text", "page_start": 1, "page_end": 1},
    ]
    sections = build_sections(paragraphs, language="en")
    paths = [section["path"] for section in sections]
    # normalize_heading collapses the double space.
    assert ["Chapter 1 Introduction"] in paths
    assert ["Chapter 1 Introduction", "Section 1.1 Scope"] in paths


def test_profile_falls_back_to_chinese() -> None:
    assert get_profile(None).code == "zh"
    assert get_profile("unknown").code == "zh"
