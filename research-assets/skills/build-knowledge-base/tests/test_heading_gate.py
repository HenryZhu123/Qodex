"""Heading detection must accept section titles and reject body lines.

Regression context: the first version treated any line starting with digits as a
section number, so lines such as "100 个数据中心分布于…" or "1110 1101 1100 1011…"
became heading_path segments in 902 of 2,698 chunks. These cases are lifted from
the real corpus.
"""

from __future__ import annotations

import pytest

from chunker import _looks_like_title, detect_heading_level

ACCEPTED = [
    ("第7章", 1),
    ("第 7 章", 1),
    ("第1章导读", 1),
    ("1.2 数据结构的基本概念和术语", 2),
    ("1.2.1 数据、数据元素、数据项和数据对象", 3),
    ("三、综合应用题", 2),
    ("（一）选择题", 3),
]

REJECTED = [
    # body lines that begin with a number
    "100 个数据中心分布于北美、欧洲、亚洲、南美和澳大利亚。其中的某些数据中心容纳了",
    "1 173单元中的140个字符、5 830～5 889单元中的60个字符写成一个记录；第4条指令单独写一个",
    "4 096GB个页表项，要占用16 384GB的连续内存空间。这样的结果显然是不能令人接受的。因",
    "第6章介绍的MIPS 处理器实现方案都是采用串行执行指令的方法，同一时刻CPU 中只有一",
    # binary strings and numeric rows
    "1110 1101 1100 1011 1010 1001 0000",
    "0110 1100",
    # code
    "1 /* 定义并声明一个信号量，名字为mr_sem，用于信号量计数 */",
    "16 wake_up_interruptible(&short_queue); /* 唤醒所有的读进程 */",
    "#include <stdio.h>",
]


@pytest.mark.parametrize(("text", "level"), ACCEPTED)
def test_accepts_section_titles(text: str, level: int) -> None:
    assert _looks_like_title(text) is True
    assert detect_heading_level(text) == level


@pytest.mark.parametrize("text", REJECTED)
def test_rejects_body_lines(text: str) -> None:
    assert _looks_like_title(text) is False
    assert detect_heading_level(text) is None


def test_markdown_heading_needs_a_title_shape() -> None:
    assert detect_heading_level("# 1.2 基本概念") == 1
    assert detect_heading_level("# 注意这里x86 汇编语言为at&t 格式，操作符后缀b 表示单字节操作") is None


def test_overlong_title_is_rejected() -> None:
    long_title = "1.2 " + "很长的标题" * 12
    assert detect_heading_level(long_title) is None


def test_level_follows_the_number_of_dots() -> None:
    # The section stack nests to whatever depth the numbering declares.
    assert detect_heading_level("1.2.3.4 深层小节") == 4
