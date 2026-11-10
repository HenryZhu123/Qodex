#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic guard for protocol, physical, and numeric contradictions.

Catches:
1. Protocol window violations: '停止-等待协议' paired with send window > 1 (e.g. 1000).
2. Congestion window zero violation: TCP initial cwnd / window set to 0 bytes / 0B.
3. Concurrency semantic conflicts: claiming both processes increment, but providing decrement instructions.
4. Peterson/mutex semantic conflicts: claiming '不加同步' while providing Peterson mutual exclusion logic.
5. Cross-field numeric invariants such as address width/capacity, CPI, and
   modulation order.  These checks complement retrieval: no textbook passage
   is needed to prove an arithmetic contradiction already present in the stem.
"""

from __future__ import annotations

import re
from math import log2

from ..domain.models import ReviewError, SpecialistReviewResult


def _result(
    *,
    reason: str,
    position: str,
    original_text: str,
    correction: str,
    description: str,
    suggestion: str,
) -> SpecialistReviewResult:
    return SpecialistReviewResult(
        reason=reason,
        has_error=True,
        total_errors=1,
        errors=[
            ReviewError(
                error_type="事实/逻辑错误",
                position=position,
                original_text=original_text,
                anchor_text=original_text,
                correction=correction,
                description=description,
                suggestion=suggestion,
                severity="严重",
            )
        ],
    )


def _numeric_invariant_guard(full_text: str) -> SpecialistReviewResult | None:
    # An n-bit byte address space cannot contain an explicitly larger cache or
    # block. This catches cross-field contradictions without relying on memory.
    address = re.search(r"主存地址为\s*(\d+)\s*位", full_text)
    cache = re.search(
        r"Cache\s*数据区大小为\s*(\d+(?:\.\d+)?)\s*(KB|MB|B)",
        full_text,
        re.IGNORECASE,
    )
    block = re.search(
        r"主存块大小为\s*(\d+(?:\.\d+)?)\s*(KB|MB|B)",
        full_text,
        re.IGNORECASE,
    )
    if address and (cache or block):
        address_bits = int(address.group(1))
        addressable_bytes = 2**address_bits

        def to_bytes(match: re.Match[str]) -> float:
            scale = {"B": 1, "KB": 1024, "MB": 1024 * 1024}[match.group(2).upper()]
            return float(match.group(1)) * scale

        largest = max(
            to_bytes(match) for match in (cache, block) if match is not None
        )
        if largest > addressable_bytes:
            span = address.group(0)
            minimum_bits = max(1, int(log2(largest - 1)) + 1)
            return _result(
                reason="主存地址位宽与题面容量互相矛盾",
                position="题干地址参数",
                original_text=span,
                correction=f"主存地址为至少{minimum_bits}位",
                description=(
                    f"{address_bits}位按字节编址最多覆盖{addressable_bytes}B，"
                    f"小于题面给出的{largest:g}B存储结构"
                ),
                suggestion=f"将地址位宽修正为至少{minimum_bits}位，或同步缩小容量参数",
            )

    cpi = re.search(r"平均\s*CPI\s*为\s*(\d+(?:\.\d+)?)", full_text, re.IGNORECASE)
    cycles = re.search(r"每条指令平均需要\s*(\d+(?:\.\d+)?)\s*个时钟周期", full_text)
    if cpi and cycles:
        cpi_value = float(cpi.group(1))
        cycle_value = float(cycles.group(1))
        if abs(cpi_value - cycle_value) > 1e-9:
            span = full_text[cpi.start():cycles.end()]
            return _result(
                reason="CPI与每条指令平均时钟周期数定义冲突",
                position="题干性能参数",
                original_text=span,
                correction=f"平均CPI为{cycle_value:g}",
                description="CPI按定义就是每条指令平均消耗的时钟周期数，两者必须相等",
                suggestion="统一CPI与每条指令平均时钟周期数",
            )

    modulation = re.search(
        r"采用\s*(\d+)\s*个幅值的\s*(?:ASK|QAM|PSK)\s*调制[^。；，]{0,30}?每个符号携带\s*(\d+)\s*个比特",
        full_text,
        re.IGNORECASE,
    )
    if modulation:
        order = int(modulation.group(1))
        claimed_bits = int(modulation.group(2))
        if order > 0 and order & (order - 1) == 0:
            expected_bits = int(log2(order))
            if claimed_bits != expected_bits:
                span = modulation.group(0)
                return _result(
                    reason="调制阶数与每符号比特数矛盾",
                    position="题干调制参数",
                    original_text=span,
                    correction=f"每个符号携带{expected_bits}个比特",
                    description=f"{order}种可区分状态每个符号只能编码log2({order})={expected_bits}比特",
                    suggestion=f"将每符号比特数改为{expected_bits}，或调整调制阶数",
                )

    heap = re.search(
        r"关键字序列\s*([\d\s,，、-]+?)\s*是\s*(小根堆|最小堆|大根堆|最大堆)",
        full_text,
    )
    if heap:
        values = [int(value) for value in re.findall(r"-?\d+", heap.group(1))]
        heap_kind = heap.group(2)
        is_min = heap_kind in {"小根堆", "最小堆"}
        violation: tuple[int, int] | None = None
        for child_index in range(1, len(values)):
            parent = values[(child_index - 1) // 2]
            child = values[child_index]
            if (is_min and parent > child) or (not is_min and parent < child):
                violation = parent, child
                break
        if violation is not None:
            parent, child = violation
            opposite = "大根堆" if is_min else "小根堆"
            span = heap.group(0)
            relation = "不大于" if is_min else "不小于"
            return _result(
                reason=f"给定序列不满足{heap_kind}的父子顺序不变量",
                position="题干堆定义",
                original_text=span,
                correction=span.rsplit(heap_kind, 1)[0] + opposite,
                description=f"{heap_kind}要求父结点{relation}子结点，但出现父结点{parent}与子结点{child}",
                suggestion=f"修正关键字序列，或将堆类型改为{opposite}",
            )

    return None


def _protocol_invariant_guard(full_text: str) -> SpecialistReviewResult | None:
    syn_free = re.search(r"SYN\s*段不占用序列号", full_text, re.IGNORECASE)
    if syn_free:
        span = syn_free.group(0)
        return _result(
            reason="TCP SYN段序列号规则被反转",
            position="题干TCP握手条件",
            original_text=span,
            correction="SYN段占用一个序列号",
            description="TCP中SYN标志段会消耗一个序列号",
            suggestion="将不占用序列号修正为占用一个序列号",
        )

    timeout_unchanged = re.search(
        r"(?:超时|计时器发生了超时)[^。；]{0,40}(?:拥塞窗口|cwnd)[^。；]{0,30}(?:慢开始门限|ssthresh)[^。；]{0,30}(?:均|都)?保持不变",
        full_text,
        re.IGNORECASE,
    )
    if timeout_unchanged:
        span = timeout_unchanged.group(0)
        return _result(
            reason="TCP超时后的拥塞控制状态不可能保持不变",
            position="题干拥塞控制条件",
            original_text=span,
            correction="超时后重设拥塞窗口，并按算法更新慢开始门限",
            description="TCP发生重传超时会触发拥塞控制，cwnd与ssthresh不能同时保持不变",
            suggestion="按题目采用的TCP拥塞控制版本修正超时后的cwnd和ssthresh",
        )
    return None


def check_factual_guards(full_text: str) -> SpecialistReviewResult | None:
    if not full_text:
        return None

    numeric = _numeric_invariant_guard(full_text)
    if numeric is not None:
        return numeric

    protocol = _protocol_invariant_guard(full_text)
    if protocol is not None:
        return protocol

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
