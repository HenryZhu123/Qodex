#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Factual/logical review pipeline v2 (stateless claim extraction + verification).

Implements the four changes agreed after the blind-test diagnosis:

1. Forced claim extraction: the long question is compressed into 2-3 falsifiable
   propositions before any judgement is made.
2. Stateless single-round verification: no multi-turn tool calling. Evidence is
   retrieved locally (~10ms) and injected into a single verification prompt,
   which removes the multi-round gateway latency that caused most dropouts.
3. Falsification wording: prompts ask "does the textbook state the opposite?"
   instead of "is there an error?", which counteracts the model's tendency to
   rationalise contradictions away.
4. Deterministic concept-inversion table: a small high-precision rule set for
   frequently inverted 408 concepts, evaluated in ~0ms.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from router_and_retriever import (  # noqa: E402
    format_evidence_block,
    parse_json_from_text,
    targeted_retrieve,
)

MAX_CLAIMS = 3
ERROR_TYPE = "事实/逻辑错误"

# ---------------------------------------------------------------- stage 1 rules

# High-precision, unambiguous concept inversions. Each entry is
# (rule_id, required_pattern, forbidden_pattern, description, correction).
# A hit requires BOTH regexes to match the question text.
CONCEPT_INVERSIONS: list[tuple[str, str, str, str, str]] = [
    (
        "forest_to_binary_leaf",
        r"森林.{0,30}二叉树|二叉树.{0,30}森林",
        r"叶结点.{0,15}右孩子(为空|的)|右孩子为空的.{0,10}结点.{0,10}(等于|对应).{0,10}叶",
        "森林转换为二叉树后，森林中的叶结点对应二叉树中「左孩子为空」的结点，而非右孩子为空",
        "左孩子为空",
    ),
    (
        "topo_sort_on_cycle",
        r"拓扑排序",
        r"有环|含环|环路|回路",
        "拓扑排序的前提是有向无环图（DAG），含环图上不存在拓扑序列",
        "有向无环图",
    ),
    (
        "burst_every_address",
        r"突发(传送|传输|方式)|猝发",
        r"每(个|一次|次)数据.{0,8}(都|均)?需.{0,6}(给出|发送|传送).{0,6}首地址",
        "突发（猝发）传送只需给出一次首地址，后续数据连续传输，不需要每个数据都发送首地址",
        "只需给出一次首地址",
    ),
    (
        "big_endian_low_byte",
        r"大端",
        r"低(位|有效)?字节.{0,10}(存放|存储).{0,6}(低地址|小地址|起始地址)",
        "大端方式将最高有效字节存放在低地址端，低有效字节存放在高地址端",
        "最高有效字节存放在低地址端",
    ),
    (
        "thread_right_predecessor",
        r"线索(二叉)?树|线索化",
        r"右线索.{0,12}(指向|指).{0,6}前驱",
        "中序线索二叉树中，右线索指向中序后继，左线索指向前驱",
        "指向中序后继",
    ),
    (
        "btree_order_key_limit",
        r"(\d)\s*阶\s*B[-－]?树",
        r"(?:根)?结点.{0,10}(包含|含有|有)\s*([4-9])\s*个关键字",
        "m 阶 B 树每个结点最多含 m-1 个关键字（4 阶最多 3 个），题面关键字数超出上限",
        "最多 m-1 个关键字",
    ),
]


def run_concept_inversion_rules(full_text: str) -> dict[str, Any] | None:
    """Stage 1: deterministic, ~0ms."""
    if not full_text:
        return None
    for rule_id, need, forbid, desc, correction in CONCEPT_INVERSIONS:
        m_need = re.search(need, full_text)
        if not m_need:
            continue
        m_forbid = re.search(forbid, full_text)
        if not m_forbid:
            continue
        span = m_forbid.group(0).strip()
        # B-tree rule needs the numeric guard: only flag when keys > order-1
        if rule_id == "btree_order_key_limit":
            order = int(m_need.group(1))
            keys = int(m_forbid.group(2))
            if keys <= order - 1:
                continue
            desc = (
                f"{order} 阶 B 树每个结点最多含 {order - 1} 个关键字，"
                f"题面声称包含 {keys} 个，超出上限"
            )
        return {
            "stage": "concept_inversion",
            "rule_id": rule_id,
            "original_text": span,
            "anchor_text": span,
            "correction": correction,
            "description": desc,
        }
    return None


# ------------------------------------------------------------ stage 2 prompts

EXTRACT_SYSTEM = """# 角色
你是 408 考研命题的「可证伪断言抽取器」。你只做信息抽取，不判断对错，不评价题目。

# 任务
从题目中提取 1~3 条【学科事实性断言】。断言必须是：
- 一个可以被教材原文直接证实或证伪的陈述；
- 独立成立，不依赖解题步骤，不依赖具体计算结果的数值；
- 覆盖题目中出现的概念定义、性质关系、协议规则、结构参数、方向/顺序约定。

# 严禁
- 严禁判断断言对错，严禁输出"可能""疑似"之类的评论。
- 严禁把纯计算过程本身当作断言（例如"结果是 1100"不算断言；"GBN 的发送窗口上限为 2^k−1"算断言）。
- 题目若完全没有事实性断言（纯计算题），输出空数组。

# 输出格式（纯 JSON）
{
  "claims": [
    {"claim": "断言原文（不超过40字）", "search_query": "用于检索教材的3-6个关键词", "subject": "computer_network|operating_system|computer_organization|data_structure"}
  ]
}
"""

VERIFY_SYSTEM = """# 角色
你是 408 教材核验员。你的职责是判断【待核验命题】是否与【教材原文】相冲突。

# 判定步骤（必须按顺序执行）
1. 从教材原文中提炼出与命题主题相关的**学科规则**（一句话，例如"分离Cache是为了减少指令流与数据流的访问冲突"）。
2. 把该规则代回命题：若命题成立，会不会与这条规则**同时为真**？
3. 只有当命题与教材规则**在逻辑上不能同时成立**时，才判 conflict=true。

# 判定标准
- conflict=true 的三种典型情形：
  (a) 教材陈述与命题**字面相反**；
  (b) 教材陈述了某规则，而命题**违反**该规则（含方向颠倒、顺序颠倒、参数越界、前提被换）；
  (c) 教材给出的定义/性质使命题的**推断必然为假**。
- conflict=false 仅限：教材原文确实没有涉及该主题，无法据此判断。

# 严禁
- 严禁使用你自己的参数记忆去否定教材原文；以给出的教材片段为准。
- 严禁为题目找补：不假设"题目可能隐含""出题人可能意指""这是特殊设定"。
- 严禁因为教材措辞与命题措辞不完全一致就判无冲突——先做语义对齐再判断。

# 输出格式（纯 JSON）
{
  "textbook_rule": "从教材原文提炼的规则（无相关内容则写空字符串）",
  "conflict": true/false,
  "confidence": "high|medium|low",
  "reason": "一句话说明冲突点，无冲突则写「教材未涉及该主题」",
  "original_text": "题目中与教材冲突的连续原文片段（无冲突则空字符串）",
  "correction": "依据教材原文给出的最小修正（无冲突则空字符串）"
}
"""


@dataclass
class PipelineResult:
    has_error: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    stage: str = ""
    latency_ms: float = 0.0
    claims: list[str] = field(default_factory=list)
    verified_claims: int = 0
    llm_calls: int = 0
    error_msg: str = ""


async def _call_json(
    client: Any,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[dict | None, float]:
    t0 = time.perf_counter()
    user = "[INPUT_PAYLOAD]\n" + json.dumps(payload, ensure_ascii=False)
    try:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
                "seed": 42,
                "response_format": {"type": "json_object"},
                "enable_thinking": False,
            },
            timeout=timeout,
        )
        lat = (time.perf_counter() - t0) * 1000.0
        if resp.status_code != 200:
            return None, lat
        return parse_json_from_text(resp.json()["choices"][0]["message"]["content"]), lat
    except Exception as exc:  # noqa: BLE001
        return {"_exception": f"{type(exc).__name__}: {exc}"}, (
            time.perf_counter() - t0
        ) * 1000.0


async def run_factual_pipeline_v2(
    client: Any,
    base_url: str,
    api_key: str,
    model: str,
    full_text: str,
    reference: str = "",
    subject: str = "computer_network",
    timeout: float = 180.0,
) -> PipelineResult:
    t0 = time.perf_counter()

    # Stage 1: deterministic inversion table
    hit = run_concept_inversion_rules(full_text)
    if hit:
        err = {
            "error_type": ERROR_TYPE,
            "position": "题干概念陈述",
            "original_text": hit["original_text"],
            "anchor_text": hit["anchor_text"],
            "correction": hit["correction"],
            "description": hit["description"],
            "suggestion": f"依据教材修正为：{hit['correction']}",
        }
        return PipelineResult(
            has_error=True,
            errors=[err],
            reason=f"[V2-Rule] {hit['description']}",
            stage="concept_inversion",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    calls = 0
    # Stage 2: claim extraction
    extracted, _ = await _call_json(
        client,
        base_url,
        api_key,
        model,
        EXTRACT_SYSTEM,
        {"reference": reference, "detection_content": full_text},
        timeout,
    )
    calls += 1
    if extracted is None:
        return PipelineResult(
            has_error=False,
            reason="[V2] claim extraction failed",
            stage="extract_failed",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            llm_calls=calls,
        )
    if "_exception" in extracted:
        return PipelineResult(
            has_error=False,
            reason=f"[V2] extract exception: {extracted['_exception']}",
            stage="extract_exception",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            llm_calls=calls,
        )

    raw_claims = extracted.get("claims") or []
    claims: list[str] = []
    queries: list[str] = []
    subj_hint = subject
    for c in raw_claims[:MAX_CLAIMS]:
        if not isinstance(c, dict):
            continue
        claim = (c.get("claim") or "").strip()
        if not claim:
            continue
        claims.append(claim)
        queries.append((c.get("search_query") or claim).strip())
        subj_hint = (c.get("subject") or subject).strip() or subject

    if not claims:
        return PipelineResult(
            has_error=False,
            reason="[V2] no falsifiable claim extracted (likely pure calculation)",
            stage="no_claim",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            llm_calls=calls,
        )

    # Stage 3: stateless verification, one call per claim, evidence pre-injected
    verified = 0
    for claim, query in zip(claims, queries):
        evs, _ = targeted_retrieve(subj_hint, [query], top_k=2)
        if not evs:
            continue
        ev_text = format_evidence_block(evs)
        verdict, _ = await _call_json(
            client,
            base_url,
            api_key,
            model,
            VERIFY_SYSTEM,
            {
                "claim": claim,
                "evidence": ev_text,
                "question_excerpt": full_text[:600],
            },
            timeout,
        )
        calls += 1
        if not verdict or "_exception" in verdict:
            continue
        verified += 1
        if not verdict.get("conflict"):
            continue
        if (verdict.get("confidence") or "").lower() == "low":
            continue
        span = (verdict.get("original_text") or "").strip() or claim
        correction = (verdict.get("correction") or "").strip()
        err = {
            "error_type": ERROR_TYPE,
            "position": "题干概念陈述",
            "original_text": span,
            "anchor_text": span,
            "correction": correction,
            "description": verdict.get("reason") or "题目陈述与教材原文冲突",
            "suggestion": (
                f"依据教材修正为：{correction}" if correction else "依据教材原文修正该陈述"
            ),
        }
        return PipelineResult(
            has_error=True,
            errors=[err],
            reason=f"[V2-KB] {verdict.get('reason', '')}",
            stage="claim_verification",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            claims=claims,
            verified_claims=verified,
            llm_calls=calls,
        )

    return PipelineResult(
        has_error=False,
        reason=f"[V2] {verified}/{len(claims)} claims verified against textbook, no conflict",
        stage="verified_clean",
        latency_ms=(time.perf_counter() - t0) * 1000.0,
        claims=claims,
        verified_claims=verified,
        llm_calls=calls,
    )
