"""English name aliasing: OCR glue and spaced text must share a token.

The 8th edition prints "JamesF.Kurose" while a question writes "James F. Kurose".
Without an alias the query never matches, which is what happened to 2,466 Latin
runs in the corpus.
"""

from __future__ import annotations

import pytest

from utils import english_aliases, tokenize_for_fts


def test_glued_and_spaced_names_agree() -> None:
    glued = english_aliases("（JamesF.Kurose）")
    spaced = english_aliases("James F. Kurose")
    assert glued == spaced == ["jamesfkurose"]


def test_two_authors_are_two_aliases() -> None:
    aliases = english_aliases("James F. Kurose and Keith W. Ross")
    assert aliases == ["jamesfkurose", "keithwross"]


def test_slash_forms_collapse() -> None:
    assert "tcpip" in english_aliases("采用 TCP/IP 协议")
    assert "ieee80211" in english_aliases("IEEE 802.11 帧")


def test_plain_phrases_are_not_aliased() -> None:
    assert english_aliases("Eighth Edition of Computer Networking") == []
    assert english_aliases("操作系统是硬件之上的第一层软件。") == []


def test_short_fragments_are_ignored() -> None:
    assert english_aliases("a.b") == []
    assert english_aliases("x.y.z") == []


@pytest.mark.parametrize("text", ["JamesF.Kurose", "James F. Kurose", "James F.Kurose"])
def test_tokenizer_always_emits_the_alias(text: str) -> None:
    assert "jamesfkurose" in tokenize_for_fts(text).split()


def test_query_and_document_meet() -> None:
    doc_tokens = set(tokenize_for_fts("第1章 计算机网络 作者 JamesF.Kurose 著").split())
    query_tokens = set(tokenize_for_fts("James F. Kurose 写的那本书").split())
    assert doc_tokens & query_tokens >= {"jamesfkurose"}
