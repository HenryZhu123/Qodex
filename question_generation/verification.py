"""Evaluate typed numerical witnesses; never execute model-produced code.

Witnesses establish numerical consistency, not correspondence with prose.
The blind reader separately checks that correspondence.
"""
from __future__ import annotations

import ipaddress
import re

# Model-authored witnesses often write addresses as text ("0x0B7C", "0B7CH", "2940").
INTEGER_TEXT = re.compile(r"^[+-]?(?:0[xX][0-9a-fA-F]+|[0-9a-fA-F]+[hH]|[0-9]+)$")


def _text_integer(value):
    text = value.strip()
    if not INTEGER_TEXT.fullmatch(text):
        raise ValueError("数值见证的整数超出允许范围。")
    sign = -1 if text[0] == "-" else 1
    body = text.lstrip("+-")
    if body[:2].lower() == "0x":
        return sign * int(body[2:], 16)
    if body[-1] in "hH":
        return sign * int(body[:-1], 16)
    return sign * int(body)


def integer(value, low, high):
    """Accept ints and exact integer strings (decimal or hexadecimal)."""
    if isinstance(value, bool):
        raise ValueError("数值见证的整数超出允许范围。")
    if isinstance(value, str):
        value = _text_integer(value)
    if type(value) is not int or not low <= value <= high:
        raise ValueError("数值见证的整数超出允许范围。")
    return value


def power(value, low, high):
    value = integer(value, low, high)
    if value & (value - 1):
        raise ValueError("大小须为 2 的幂。")
    return value


def solve(kind, inputs):
    if not isinstance(inputs, dict):
        raise ValueError("数值见证 inputs 必须是对象。")
    if kind == "finite_domain":
        from .finite_verification import solve_finite
        return solve_finite(inputs)
    if kind == "paging" and inputs.keys() == {"page_size", "address", "page_table"}:
        size = power(inputs["page_size"], 2, 65536)
        address = integer(inputs["address"], 0, 2**32 - 1)
        table = inputs["page_table"]
        if not isinstance(table, dict) or not 1 <= len(table) <= 64:
            raise ValueError("页表无效。")
        for key, value in table.items():
            if not isinstance(key, str) or not key.isdigit() or str(int(key)) != key:
                raise ValueError("虚页号须为规范十进制字符串。")
            integer(value, 0, 2**24 - 1)
        bits = size.bit_length() - 1
        page, offset = address >> bits, address & (size - 1)
        if str(page) not in table:
            raise ValueError("所访问的虚页没有有效映射。")
        frame = integer(table[str(page)], 0, 2**24 - 1)
        return {"page": page, "offset": offset, "frame": frame, "physical_address": (frame << bits) | offset}
    if kind == "cache" and inputs.keys() == {"cache_size", "block_size", "address"}:
        size, block = power(inputs["cache_size"], 16, 4096), power(inputs["block_size"], 4, 256)
        address = integer(inputs["address"], 0, 65535)
        if block >= size:
            raise ValueError("Cache 至少容纳两块。")
        bits, shift = block.bit_length() - 1, size.bit_length() - 1
        return {"tag": address >> shift, "index": (address >> bits) & (size // block - 1),
                "offset": address & (block - 1)}
    if kind == "stack" and inputs.keys() == {"output"}:
        output = inputs["output"]
        if not isinstance(output, list) or not 2 <= len(output) <= 8 or any(type(v) is not int for v in output):
            raise ValueError("栈序列长度须为 2 至 8。")
        if sorted(output) != list(range(1, len(output) + 1)):
            raise ValueError("栈输出须为 1 至 n 的排列。")
        stack, next_value, peak = [], 1, 0
        for step, value in enumerate(output, 1):
            while (not stack or stack[-1] != value) and next_value <= len(output):
                stack.append(next_value)
                next_value += 1
                peak = max(peak, len(stack))
            if not stack or stack[-1] != value:
                return {"reachable": False, "first_blocked_step": step, "minimum_capacity": None}
            stack.pop()
        return {"reachable": True, "first_blocked_step": None, "minimum_capacity": peak}
    if kind == "subnet" and inputs.keys() == {"address", "prefix"}:
        prefix = integer(inputs["prefix"], 16, 30)
        if not isinstance(inputs["address"], str):
            raise ValueError("IPv4 地址须为字符串。")
        net = ipaddress.IPv4Network(f"{inputs['address']}/{prefix}", strict=False)
        return {"network": str(net.network_address), "broadcast": str(net.broadcast_address),
                "usable_hosts": net.num_addresses - 2}
    raise ValueError("不支持的数值见证类型或字段。")


TOPIC_KINDS = {"single_level_paging": "paging", "direct_mapped_cache": "cache",
               "stack_pop_sequence": "stack", "ipv4_subnet_network_address": "subnet"}


def verify_witnesses(topic, witnesses):
    if not isinstance(witnesses, list) or len(witnesses) > 16:
        raise ValueError("calculations 须为最多 16 条的数组。")
    required = TOPIC_KINDS.get(topic)
    if required and not witnesses:
        raise ValueError("计算题须提供可执行的数值见证。")
    for witness in witnesses:
        if not isinstance(witness, dict) or witness.keys() != {"kind", "inputs", "result"}:
            raise ValueError("数值见证须包含 kind、inputs、result。")
        if witness["kind"] != required:
            raise ValueError("数值见证与当前考点不符。")
        actual = solve(witness["kind"], witness["inputs"])
        # JSON comparison rejects True as a substitute for integer 1.
        import json
        if json.dumps(actual, sort_keys=True) != json.dumps(witness["result"], sort_keys=True):
            raise ValueError("数值见证与独立求解器不一致。")
    return len(witnesses)
