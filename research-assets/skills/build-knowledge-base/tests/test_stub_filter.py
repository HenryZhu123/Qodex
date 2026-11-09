"""Fragment filter and heading stripping in the store layer.

Two related defects from the rebuilt corpus:

* short fragments (a page number, a figure caption) stayed in the FTS index,
  where BM25 rewards them for being short and can return them as evidence;
* roughly half the chunks repeat their own heading as the first line, which
  double-weighted the heading words in the token stream.
"""

from __future__ import annotations

import pytest

from store import is_stub, strip_leading_heading


@pytest.mark.parametrize(
    "body",
    [
        "虚拟存储器",
        "26",
        "图5.23　图5.19中树的二叉链表",
        "输入 / 输出",
        "",
        "   ",
    ],
)
def test_fragments_are_stubs(body: str) -> None:
    assert is_stub(body) is True


@pytest.mark.parametrize(
    "body",
    [
        "死锁是指一组进程中的每个进程都在等待另一个进程所占有的资源。",
        "进程调度的任务主要有三；①保存CPU现场信息。",
        "在树的第 i 层上至多有 2^(i-1) 个节点；这是二叉树的性质之一。",
    ],
)
def test_sentences_are_not_stubs(body: str) -> None:
    assert is_stub(body) is False


def test_short_but_punctuated_text_is_kept() -> None:
    # Short yet a complete statement: must still be searchable.
    assert is_stub("页表的作用是映射。") is False


def test_strips_first_line_when_it_equals_the_heading() -> None:
    content = "1.2 数据结构的基本概念和术语\n\n下列概念和术语将在后文中多次出现。"
    body = strip_leading_heading(content, ["第1章", "1.2 数据结构的基本概念和术语"])
    assert body.startswith("下列概念")
    assert "1.2 数据结构" not in body


def test_strips_heading_prefix_without_newline() -> None:
    content = "1.1 操作系统的目标 在计算机系统上配置OS，其主要目标是实现方便性。"
    body = strip_leading_heading(content, ["1.1 操作系统的目标"])
    assert body.startswith("在计算机系统上配置OS")


def test_keeps_body_when_first_line_differs() -> None:
    content = "死锁的四个必要条件如下。\n\n互斥条件、请求和保持条件……"
    body = strip_leading_heading(content, ["第3章", "3.5 死锁概述"])
    assert body.startswith("死锁的四个必要条件")


def test_strips_markdown_decorated_heading() -> None:
    content = "# 5.7.3 哈夫曼编码\n\n哈夫曼编码是最优前缀编码。"
    body = strip_leading_heading(content, ["5.7.3 哈夫曼编码"])
    assert body.startswith("哈夫曼编码是最优前缀编码")


def test_empty_heading_path_returns_unchanged() -> None:
    content = "第一行是正文。\n第二行。"
    assert strip_leading_heading(content, None) == content
    assert strip_leading_heading(content, []) == content
