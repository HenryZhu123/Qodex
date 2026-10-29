#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic guard for blatant protocol and physical contradictions.

Catches:
1. Protocol window violations: '停止-等待协议' paired with send window > 1 (e.g. 1000).
2. Congestion window zero violation: TCP initial cwnd / window set to 0 bytes / 0B.
3. Concurrency semantic conflicts: claiming both processes increment, but providing decrement instructions.
4. Peterson/mutex semantic conflicts: claiming '不加同步' while providing Peterson mutual exclusion logic.
"""

from __future__ import annotations

import re
from ..domain.models import ReviewError, SpecialistReviewResult


def check_factual_guards(full_text: str) -> SpecialistReviewResult | None:
    if not full_text:
        return None

    # 1. Stop-and-Wait protocol window > 1
    if "停止-等待" in full_text:
        m_win = re.search(r"(?:发送窗口|滑动窗口|窗口大小)[^\d]{0,10}([2-9]\d*|1\d+)", full_text)
        if m_win:
            span = m_win.group(0)
            err = ReviewError(
                error_type="事实/逻辑错误",
                position="题干协议参数描述",
                original_text="停止-等待协议",
                anchor_text=span,
                correction="后退N帧协议（GBN）或选择重传协议（SR）",
                description=f"停止-等待协议的发送窗口大小严格等于1，题干设定为「{span}」，违反协议规范",
                suggestion="将「停止-等待协议」更正为支持多帧发送的「后退N帧协议（GBN）」或「选择重传协议（SR）」",
                severity="严重",
            )
            return SpecialistReviewResult(
                reason=f"停止-等待协议与窗口大小冲突：{span}",
                has_error=True,
                total_errors=1,
                errors=[err],
            )

    # 2. TCP cwnd = 0
    m_cwnd0 = re.search(r"(?:当前|初始)?\s*拥塞\s*窗口[^\d]{0,15}0\s*(?:字节|B|个MSS)", full_text, re.IGNORECASE)
    if m_cwnd0:
        span = m_cwnd0.group(0).strip()
        err = ReviewError(
            error_type="事实/逻辑错误",
            position="题干网络参数",
            original_text=span,
            anchor_text=span,
            correction="拥塞窗口为4000B",
            description=f"TCP 拥塞窗口不能为 0B，否则发送方无法连续发送两个最大段，题干条件与发送行为矛盾",
            suggestion=f"将「{span}」修改为符合规范的数值，例如「当前拥塞窗口为4000B」",
            severity="严重",
        )
        return SpecialistReviewResult(
            reason=f"TCP拥塞窗口为0异常：{span}",
            has_error=True,
            total_errors=1,
            errors=[err],
        )

    # 3. Concurrency action contradiction (both increment vs decrement)
    has_both_inc = re.search(r"(?:两个进程.*?(?:均|都).*?加\s*1|P1[^\n]*?加\s*1[^\n]*?P2[^\n]*?加\s*1)", full_text)
    if has_both_inc and re.search(r"减\s*1|sub|dec", full_text, re.IGNORECASE):
        span = has_both_inc.group(0).strip()
        err = ReviewError(
            error_type="事实/逻辑错误",
            position="题干进程操作描述",
            original_text=span,
            anchor_text=span,
            correction="P1对x加1，P2对x减1",
            description="题干声称两进程均执行加1操作，但随后却给出加1和减1两条指令序列，操作主体与指令语义直接矛盾",
            suggestion="将题干中的两进程操作修正为「一个加1、一个减1」以与指令序列保持一致",
            severity="严重",
        )
        return SpecialistReviewResult(
            reason=f"并发操作与指令序列矛盾：{span}",
            has_error=True,
            total_errors=1,
            errors=[err],
        )

    # 4. Peterson algorithm with "不加同步"
    if "不加同步" in full_text and ("Peterson" in full_text or "enter_region" in full_text or "flag[" in full_text or "turn" in full_text):
        span = "不加同步地访问临界资源"
        if span not in full_text:
            span = "不加同步"
        err = ReviewError(
            error_type="事实/逻辑错误",
            position="题干前提描述",
            original_text=span,
            anchor_text=span,
            correction="访问临界资源",
            description="题干声称「不加同步」，但后文给出的是经典的 Peterson 互斥同步算法实现，文字陈述与代码逻辑完全相反",
            suggestion=f"删除冲突的前提修饰词「{span}」",
            severity="严重",
        )
        return SpecialistReviewResult(
            reason=f"题干前提与算法代码矛盾：{span}",
            has_error=True,
            total_errors=1,
            errors=[err],
        )

    # 5. Non-positive RTT / delay
    m_rtt0 = re.search(r"(?:往返时间|往返时延|RTT)[^\d]{0,10}0\s*(?:ms|毫秒|s|秒)", full_text, re.IGNORECASE)
    if m_rtt0:
        span = m_rtt0.group(0)
        err = ReviewError(
            error_type="事实/逻辑错误",
            position="题干网络物理参数",
            original_text=span,
            anchor_text=span,
            correction="往返时间 RTT=10ms",
            description=f"物理网络传输必然存在传播与排队时延，RTT 不能为 0",
            suggestion=f"将「{span}」更正为正常的物理时延数值（如 10ms 或 20ms）",
            severity="严重",
        )
        return SpecialistReviewResult(
            reason=f"网络往返时延违背物理常理：{span}",
            has_error=True,
            total_errors=1,
            errors=[err],
        )

    return None
