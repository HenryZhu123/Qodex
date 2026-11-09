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
