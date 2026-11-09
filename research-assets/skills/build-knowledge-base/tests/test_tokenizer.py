"""Tokenizer and hash stability.

The FTS index stores jieba tokens; queries must be produced by the same function
or they never match. A mismatch here caused every multi-character term lookup
(突发传输, 首地址, 森林 二叉树) to return zero hits.
"""

from __future__ import annotations

from kb_registry import chunk_sha256
from utils import tokenize_for_fts


def test_tokenizes_multi_character_terms_into_parts() -> None:
    # Pins the actual behaviour: a four-character term must be split, otherwise
    # the FTS index (built from jieba) never matches a whole-term query.
    tokens = tokenize_for_fts("突发传输").split()
    assert "突发" in tokens
    assert "传输" in tokens


def test_same_text_same_tokens() -> None:
    text = "TCP 拥塞窗口 ssthresh 设置为 cwnd 的一半。"
    assert tokenize_for_fts(text) == tokenize_for_fts(text)


def test_empty_text_yields_empty_tokens() -> None:
    assert tokenize_for_fts("") == ""


def test_ascii_terms_survive_lowercased() -> None:
    tokens = tokenize_for_fts("TCP ssthresh MIPS").split()
    assert "tcp" in tokens
    assert "ssthresh" in tokens


def test_chunk_hash_is_content_addressable() -> None:
    a = "页表把逻辑地址映射为物理地址。"
    b = "页表把逻辑地址映射到物理地址。"
    assert chunk_sha256(a) == chunk_sha256(a)
    assert chunk_sha256(a) != chunk_sha256(b)


def test_chunk_hash_ignores_punctuation_by_design() -> None:
    # OCR drifts punctuation; treating it as noise keeps dedup stable.
    assert chunk_sha256("进程是一个执行过程。") == chunk_sha256("进程是一个执行过程！")


def test_chunk_hash_ignores_surrounding_whitespace() -> None:
    assert chunk_sha256("  进程是一个执行过程。  ") == chunk_sha256("进程是一个执行过程。")
