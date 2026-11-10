#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic rule-based pre-checker for format and structure errors.

Catches:
1. option_structure: irregular option prefixes (A), A、, ①, lower-case a.), duplicate prefixes,
   missing options, out-of-range options (E/F), and trailing boundary punctuation.
2. type_mismatch: non-choice answer instructions inside single-choice questions
   (e.g., '判断对错', '请证明', '多选', '写出推导过程', '全选才得分').
"""

from __future__ import annotations

import re
from typing import Any

from ..domain.models import ReviewError, SpecialistReviewResult

MISMATCH_PATTERNS = [
    (r"（(?:判断[对错正误]|判断对错)[^）]*）", "单选题要求按判断题形式作答，与四选一单选题型冲突"),
    (r"（(?:请证明|证明你的结论)[^）]*）", "单选题要求给出证明，属于证明题的作答形式"),
    (r"（(?:请写出完整转换过程|写出你的推导|请写出推导过程|写出计算过程)[^）]*）", "单选题要求写出推导/计算过程，超出选择题作答形式"),
    (r"，(?:并写出计算过程|并画出时序图|写出推导过程)", "单选题附带计算或绘图作答指令，属于解答题作答形式"),
    (r"（(?:请说明|说明计算依据|如无合适选项请说明理由|请说明理由)[^）]*）", "单选题附加说明理由等主观问答要求"),
    (r"个，请说明计算依据", "单选题被改写为填空并附带说明要求"),
    (r"（(?:全选才得分|至少选两项|多选|可多选[^）]*|选出所有正确选项)[^）]*）", "单选题附带多选评分或作答指令，与单选题冲突"),
    (r"（(?:请列出全部子功能的时间|请给出完整安全序列|请给出哈夫曼树)[^）]*）", "单选题要求给出完整中间结构或序列，超出选项容量"),
    (r"（(?:请用英文作答|用十进制写出|结果保留两位小数)[^）]*）", "单选题附加与选项形式冲突的作答格式要求"),
]

OPTION_PREFIX_ANOMALIES = [
    (r"(?:^|\n)\s*([A-D])、", "选项标号使用顿号「{0}、」，未按标准句点「{0}.」规范排版"),
    (r"(?:^|\n)\s*([A-D])\)", "选项标号使用右括号「{0})」，全题标号符号不统一"),
    (r"(?:^|\n)\s*([A-D])\uff0e", "选项标号使用全角句点「{0}．」，全题标号符号不统一"),
    (r"(?:^|\n)\s*([a-d])\.", "选项标号使用小写字母「{0}.」，与大写标号不统一"),
    (r"(?:^|\n)\s*[①②③④⑤]", "选项标号使用圆圈数字，全题标号体系不统一"),
    (r"(?:^|\n)\s*([EFGHJKMNPQRSTUWYZ])[\.．、\)]", "选项标号使用「{0}」，超出单选题 A-D 的标准选项范围"),
]


def check_deterministic_rules(full_text: str) -> SpecialistReviewResult | None:
    """Run fast deterministic checks before calling LLM."""
    if not full_text:
        return None

    # 1. Check type mismatch
    for pat, desc in MISMATCH_PATTERNS:
        m = re.search(pat, full_text)
        if m:
            matched_span = m.group(0)
            err = ReviewError(
                error_type="题目与题型不一致",
                position="题干末尾作答指令",
                original_text=matched_span,
                anchor_text=matched_span,
                correction="",
                description=desc,
                suggestion=f"删除冲突的作答指令「{matched_span}」",
                severity="严重",
            )
            return SpecialistReviewResult(
                reason=f"发现题型冲突：{desc}",
                has_error=True,
                total_errors=1,
                errors=[err],
            )

    # 2. Check option structure
    # Split stem and options area: find where option A starts
    opt_match = re.search(r"(?:\n|^)\s*(?:[A-D]|①|[a-d])[\.．、\)]", full_text)
    if opt_match:
        opts_text = full_text[opt_match.start():]
        # Check prefix anomalies
        for pat, desc_tmpl in OPTION_PREFIX_ANOMALIES:
            m = re.search(pat, opts_text)
            if m:
                span = m.group(0).strip()
                char_val = m.group(1) if m.groups() else span
                desc = desc_tmpl.format(char_val)
                err = ReviewError(
                    error_type="选项错误",
                    position="选项标号",
                    original_text=span,
                    anchor_text=span,
                    correction=f"{char_val.upper()}." if char_val in "abcdABCD" else "D.",
                    description=desc,
                    suggestion=f"修正不规则选项标号「{span}」",
                    severity="中等",
                )
                return SpecialistReviewResult(
                    reason=f"发现选项结构错误：{desc}",
                    has_error=True,
                    total_errors=1,
                    errors=[err],
                )

        # Check duplicate option letter prefixes (e.g. C. appearing twice, or C. C. inline)
        # 1. Inline repeat: e.g. "C.  C." or "B. B."
        m_inline_dup = re.search(r"([A-D][\.．]\s*){2,}", opts_text)
        if m_inline_dup:
            dup_span = m_inline_dup.group(0).strip()
            err = ReviewError(
                error_type="选项错误",
                position="选项标号",
                original_text=dup_span,
                anchor_text=dup_span,
                correction=dup_span[:2],
                description=f"选项标号「{dup_span}」重复排版",
                suggestion=f"删除冗余的重复标号「{dup_span}」",
                severity="严重",
            )
            return SpecialistReviewResult(
                reason=f"发现重复选项标号：{dup_span}",
                has_error=True,
                total_errors=1,
                errors=[err],
            )

        # 2. Check no space after dot: e.g. "D.110"
        m_no_space = re.search(r"(?:^|\n)\s*([A-D])\.([^\s\n])", opts_text)
        if m_no_space:
            lt = m_no_space.group(1)
            nxt = m_no_space.group(2)
            span = f"{lt}.{nxt}"
            err = ReviewError(
                error_type="选项错误",
                position="选项标号",
                original_text=f"{lt}.",
                anchor_text=span,
                correction=f"{lt}. ",
                description="标号与选项正文之间缺少空格，选项边界不清",
                suggestion=f"在标号「{lt}.」后增加空格",
                severity="轻微",
            )
            return SpecialistReviewResult(
                reason=f"标号与内容粘连：{lt}.",
                has_error=True,
                total_errors=1,
                errors=[err],
            )

        # 3. Check duplicate internal punctuation like 、、
        m_dup_punc = re.search(r"[、，；,;]{2,}", opts_text)
        if m_dup_punc:
            span = m_dup_punc.group(0)
            err = ReviewError(
                error_type="选项错误",
                position="选项内容",
                original_text=span,
                anchor_text=span,
                correction=span[0],
                description="选项文本中出现连续重复标点符号",
                suggestion=f"将「{span}」替换为单个符号「{span[0]}」",
                severity="轻微",
            )
            return SpecialistReviewResult(
                reason=f"选项内存在重复标点：{span}",
                has_error=True,
                total_errors=1,
                errors=[err],
            )

        # 4. Check missing Option A (e.g. B. appears at beginning of options without A.)
        if re.search(r"(?:^|\n)\s*B[\.．]", opts_text) and not re.search(r"(?:^|\n)\s*A[\.．]", opts_text):
            err = ReviewError(
                error_type="选项错误",
                position="选项起始",
                original_text="B.",
                anchor_text="B.",
                correction="A.",
                description="第一个选项缺少标号 A.，直接以 B. 开始或标号缺失",
                suggestion="为第一个选项补充标号 A.",
                severity="严重",
            )
            return SpecialistReviewResult(
                reason="第一个选项缺少标号 A.",
                has_error=True,
                total_errors=1,
                errors=[err],
            )

        # Check duplicate option letter prefixes (e.g. C. appearing twice in options)
        # Look for option prefixes at line beginnings
        letters_found = re.findall(r"(?:^|\n)\s*([A-D])[\.．]", opts_text)
        seen_letters = set()
        for lt in letters_found:
            if lt in seen_letters:
                dup_span = f"{lt}."
                err = ReviewError(
                    error_type="选项错误",
                    position="选项标号",
                    original_text=dup_span,
                    anchor_text=dup_span,
                    correction="",
                    description=f"选项标号「{lt}.」重复出现多次",
                    suggestion=f"删除或重命名重复的选项标号「{lt}.」",
                    severity="严重",
                )
                return SpecialistReviewResult(
                    reason=f"发现重复选项标号：{lt}.",
                    has_error=True,
                    total_errors=1,
                    errors=[err],
                )
            seen_letters.add(lt)

        # Check dangling trailing punctuation at ends of option lines
        for line in opts_text.splitlines():
            line_str = line.strip()
            # Must look like an option line (starts with A-D.)
            if re.match(r"^[A-D][\.．]", line_str) and re.search(r"[、；，,]$", line_str):
                dangling = line_str[-1]
                err = ReviewError(
                    error_type="选项错误",
                    position="选项结尾",
                    original_text=dangling,
                    anchor_text=line_str[-10:],
                    correction="",
                    description=f"选项末尾多出未完结符号「{dangling}」",
                    suggestion=f"删除选项末尾多余的符号「{dangling}」",
                    severity="轻微",
                )
                return SpecialistReviewResult(
                    reason=f"选项结尾存在多余标点：{dangling}",
                    has_error=True,
                    total_errors=1,
                    errors=[err],
                )

    return None
