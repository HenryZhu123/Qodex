#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agentic Reviewer: Multi-turn tool calling review executor.

Supports:
1. Native function calling with search_kb
2. Scoped retrieval from 408 SQLite knowledge base
3. Dynamic multi-turn loop and structured JSON extraction
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from router_and_retriever import (
    EvidenceItem,
    format_evidence_block,
    parse_json_from_text,
    targeted_retrieve,
)

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
PROMPT_FILE = ROOT_DIR / "prompts" / "agentic_logic_check" / "task.txt"

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "查询计算机考研408教材权威知识库，获取特定概念定义、参数规范、定理或计算公式",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "精准的实体检索词（例如：'TCP 初始拥塞窗口 cwnd 初始值 MSS'，'SCAN 磁盘调度算法 磁头移动方向'）",
                    },
                    "subject": {
                        "type": "string",
                        "enum": [
                            "computer_network",
                            "operating_system",
                            "computer_organization",
                            "data_structure",
                        ],
                        "description": "所属学科",
                    },
                },
                "required": ["query", "subject"],
            },
        },
    }
]


@dataclass
class ReviewResult:
    has_error: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    think: str = ""
    raw_content: str = ""
    tool_calls_count: int = 0
    tool_queries: list[str] = field(default_factory=list)
    evidence_retrieved: list[EvidenceItem] = field(default_factory=list)
    total_latency_ms: float = 0.0
    retrieval_latency_ms: float = 0.0
    rounds: int = 0
    error_msg: str = ""


async def run_agentic_review(
    client: Any,
    base_url: str,
    api_key: str,
    model: str,
    full_text: str,
    subject: str = "computer_network",
    system_prompt: str | None = None,
    max_rounds: int = 3,
    timeout: float = 90.0,
) -> ReviewResult:
    """Execute multi-turn agentic review with autonomous tool retrieval."""
    if system_prompt is None:
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8").strip()

    t0 = time.perf_counter()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": "[INPUT_PAYLOAD]\n"
            + json.dumps(
                {"detection_content": full_text, "subject": subject},
                ensure_ascii=False,
            ),
        },
    ]

    tool_queries: list[str] = []
    all_evidence: list[EvidenceItem] = []
    total_retrieval_latency = 0.0
    tool_calls_count = 0

    for round_idx in range(max_rounds):
        # In the last round, force finish by removing tools
        current_tools = TOOLS_SCHEMA if round_idx < (max_rounds - 1) else None
        current_choice = "auto" if round_idx < (max_rounds - 1) else "none"

        resp = None
        for attempt in range(3):
            try:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": messages,
                        "tools": current_tools,
                        "tool_choice": current_choice,
                        "temperature": 0.0,
                        "seed": 42,
                        "enable_thinking": False,
                    },
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    break
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(1.0)

        if resp is None or resp.status_code != 200:
            return ReviewResult(
                has_error=False,
                error_msg=f"API error status {resp.status_code if resp else 'None'}",
                total_latency_ms=(time.perf_counter() - t0) * 1000.0,
                rounds=round_idx + 1,
            )

            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
            messages.append(msg)

            tcs = msg.get("tool_calls")
            if not tcs:
                # Agent concluded and returned final analysis
                content = msg.get("content") or ""
                parsed = parse_json_from_text(content) or {}
                return ReviewResult(
                    has_error=bool(parsed.get("has_error", False)),
                    errors=parsed.get("errors") or [],
                    reason=parsed.get("reason") or "",
                    think=parsed.get("think") or "",
                    raw_content=content,
                    tool_calls_count=tool_calls_count,
                    tool_queries=tool_queries,
                    evidence_retrieved=all_evidence,
                    total_latency_ms=(time.perf_counter() - t0) * 1000.0,
                    retrieval_latency_ms=total_retrieval_latency,
                    rounds=round_idx + 1,
                )

            # Process tool calls
            for tc in tcs:
                tool_calls_count += 1
                try:
                    args = json.loads(tc["function"]["arguments"])
                except Exception:
                    args = {}
                q = args.get("query", "")
                sub = args.get("subject", subject)
                tool_queries.append(f"[{sub}] {q}")

                evs, r_lat = targeted_retrieve(sub, [q], top_k=2)
                total_retrieval_latency += r_lat
                all_evidence.extend(evs)
                ev_text = format_evidence_block(evs)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": ev_text if ev_text else "知识库未检索到完全匹配的教材段落。",
                    }
                )

    return ReviewResult(
        has_error=False,
        error_msg="Exceeded max_rounds without final decision",
        total_latency_ms=(time.perf_counter() - t0) * 1000.0,
        rounds=max_rounds,
    )
