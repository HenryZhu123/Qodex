"""Context-dependent repairs: l/1, 2O17, and code line numbers.

These are the ones that go wrong when applied blindly, so each rule carries a
guard: the l→1 rules skip code, and a leading number is only removed when three
or more lines look like a listing.
"""

from __future__ import annotations

import pytest

from textclean import looks_like_code, repair_numeric_ocr


def test_l_between_digits_becomes_one() -> None:
    assert repair_numeric_ocr("编号20l6")["text"] == "编号2016"
    assert repair_numeric_ocr("地址 13l2")["text"] == "地址 1312"


def test_formula_variable_is_left_alone() -> None:
    # "2l/R" is 2·L/R: the l is the packet length, not a mangled 1.
    text = "总时延是2l/R 。"
    assert repair_numeric_ocr(text)["text"] == text


def test_l_before_three_digits_becomes_one() -> None:
    assert repair_numeric_ocr("请求（l00KB）")["text"] == "请求（100KB）"
    result = repair_numeric_ocr("共l000次")
    assert result["text"] == "共1000次"
    assert result["counts"]["l→1 (before digits)"] == 1


def test_code_is_left_alone() -> None:
    code = "for(i=0;i<l000;i++) { sum+=a[i]; }"
    assert looks_like_code(code)
    assert repair_numeric_ocr(code)["text"] == code


def test_prose_with_one_code_word_still_counts_as_prose() -> None:
    prose = "该函数的返回值为整数，参数是数组下标。"
    assert not looks_like_code(prose)
    assert repair_numeric_ocr("长度是 l00 字节")["text"] == "长度是 100 字节"


def test_year_with_letter_o() -> None:
    assert repair_numeric_ocr("20l6 年提出")["text"] == "2016 年提出"
    assert repair_numeric_ocr("2O17 年的标准")["text"] == "2017 年的标准"


def test_single_leading_number_is_kept() -> None:
    text = "1   个数据块"
    assert repair_numeric_ocr(text)["text"] == text


def test_three_listing_lines_are_stripped() -> None:
    text = "1   int main()\n2   {\n3       return 0;\n"
    result = repair_numeric_ocr(text)
    assert "int main()" in result["text"]
    assert not result["text"].startswith("1")
    assert result["counts"]["code line numbers"] >= 3


def test_plain_percentage_is_untouched() -> None:
    text = "占用率达到 95 % 以上，延迟 20 ms。"
    assert repair_numeric_ocr(text)["text"] == text
