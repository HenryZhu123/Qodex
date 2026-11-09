from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from exam_checker.domain.models import CheckerPayload, SpecialistReviewResult
from exam_checker.integrations.knowledge_base import KnowledgeBaseRetriever
from exam_checker.integrations.specialist_reviewer import (
    OpenAICompatibleSpecialistReviewer,
)
from exam_checker.prompts.repositories import JevPromptRepository, ReviewPromptRepository
from exam_checker.services.question_review_service import QuestionReviewService


class FakePrompts:
    def system_prompt(self, task_id: str) -> str:
        return f"PROMPT:{task_id}"


from exam_checker.domain.models import CheckerPayload, SpecialistReviewResult
from exam_checker.integrations.knowledge_base import (
    DEFAULT_KB_ROOT,
    KnowledgeBaseRetriever,
)
from exam_checker.integrations.specialist_reviewer import (
    OpenAICompatibleSpecialistReviewer,
)
from exam_checker.prompts.repositories import JevPromptRepository, ReviewPromptRepository
from exam_checker.services.question_review_service import QuestionReviewService


class FakePrompts:
    def system_prompt(self, task_id: str) -> str:
        return f"PROMPT:{task_id}"


def test_knowledge_base_retriever_search_and_format() -> None:
    kb = KnowledgeBaseRetriever(DEFAULT_KB_ROOT)
    assert kb.is_available() is True

    evs, lat = kb.search("computer_network", "TCP 拥塞窗口 慢开始", top_k=2)
    assert len(evs) > 0
    assert evs[0].subject == "computer_network"
    assert lat >= 0

    fmt = kb.format_evidence(evs)
    assert "【计算机网络｜" in fmt


def test_knowledge_base_auto_subject_routes_across_books() -> None:
    kb = KnowledgeBaseRetriever(DEFAULT_KB_ROOT)
    assert kb.is_available() is True

    # A term that only the computer-organization book defines: routing on "auto"
    # must reach it without the caller naming the subject.
    evs, _ = kb.search("auto", "中断隐指令 保存断点 关中断", top_k=2)
    assert len(evs) > 0
    assert evs[0].subject == "computer_organization"

    # A network-only term must still resolve to the network book.
    evs, _ = kb.search("auto", "802.11 帧 地址1 接收站 地址2 发送站", top_k=2)
    assert len(evs) > 0
    assert evs[0].subject == "computer_network"


@pytest.mark.asyncio
async def test_specialist_reviewer_agentic_tool_call_flow() -> None:
    kb = KnowledgeBaseRetriever(DEFAULT_KB_ROOT)

    # Mock transport that simulates tool calling on first turn, then final response on second turn
    round_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal round_count
        round_count += 1
        body = json.loads(request.content)
        if round_count == 1:
            # Model issues tool call
            assert "tools" in body
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "tc_1",
                                        "type": "function",
                                        "function": {
                                            "name": "search_kb",
                                            "arguments": json.dumps(
                                                {"query": "TCP 拥塞窗口", "subject": "computer_network"}
                                            ),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        # Model receives tool evidence and returns final verdict
        assert body["messages"][-1]["role"] == "tool"
        assert "[权威教材检索依据]" in body["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "reason": "大端方式描述错误",
                                    "has_error": True,
                                    "total_errors": 1,
                                    "errors": [
                                        {
                                            "error_type": "事实/逻辑错误",
                                            "position": "题干",
                                            "original_text": "大端方式",
                                            "anchor_text": "采用大端方式存储数据",
                                            "correction": "小端方式",
                                            "description": "大端方式下低位字节存储在高地址端，与选项不符。",
                                            "suggestion": "将大端方式改为小端方式。",
                                            "severity": "严重",
                                        }
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reviewer = OpenAICompatibleSpecialistReviewer(
            "https://llm.example/v1",
            "secret",
            "qwen3.8-27b",
            FakePrompts(),
            client=client,
            knowledge_base=kb,
        )

        result, lat, attempts = await reviewer.review(
            "logic_check",
            CheckerPayload(reference="", detection_content="某系统采用大端方式存储数据，请核对大端方式"),
        )

        assert result.has_error is True
        assert len(result.errors) == 1
        assert result.errors[0].error_type == "事实/逻辑错误"
        assert len(result.kb_queries) == 1
        assert "[computer_network] TCP 拥塞窗口" in result.kb_queries[0]
        assert result.kb_latency_ms >= 0


class DummyJevRouter:
    model = "mock-jev"

    async def predict(self, task_id: str, payload: CheckerPayload):
        from exam_checker.domain.models import JevPrediction
        return JevPrediction(
            task_id=task_id,
            model=self.model,
            choice="RUN",
            p_run=1.0,
            p_skip=0.0,
            confidence=0.9,
            latency_ms=5,
        )


@pytest.mark.asyncio
async def test_question_review_service_timing_and_kb_metrics() -> None:
    kb = KnowledgeBaseRetriever(DEFAULT_KB_ROOT)

    class MockSpecialist:
        model = "mock-qwen"

        async def review(self, task_id: str, payload: CheckerPayload):
            if task_id == "logic_check":
                return (
                    SpecialistReviewResult(
                        reason="逻辑有误",
                        has_error=True,
                        total_errors=1,
                        errors=[
                            {
                                "error_type": "事实/逻辑错误",
                                "position": "题干",
                                "original_text": "错误文本",
                                "anchor_text": "题目错误文本",
                                "correction": "正确文本",
                                "description": "存在逻辑错误",
                                "suggestion": "修改文本",
                                "severity": "严重",
                            }
                        ],
                        kb_queries=["[computer_network] 拥塞控制"],
                        kb_latency_ms=15,
                    ),
                    30,
                    1,
                )
            return (
                SpecialistReviewResult(
                    reason="无错",
                    has_error=False,
                    total_errors=0,
                    errors=[],
                ),
                10,
                1,
            )

    class DummyJevPrompts:
        task_ids = ["logic_check"]

        def get(self, task_id: str):
            class P:
                skip_threshold = 0.5
            return P()

    service = QuestionReviewService(
        router=DummyJevRouter(),
        reviewer=MockSpecialist(),
        jev_prompts=DummyJevPrompts(),
    )

    result = await service.review_question(
        document_id="doc1",
        question_id="q1",
        question_number="1",
        payload=CheckerPayload(reference="", detection_content="题目错误文本"),
    )

    assert result.review.status == "NEEDS_REVISION"
    assert result.review.timing_ms.knowledge_base == 15
    logic_check = next(c for c in result.review.checks if c.task_id == "logic_check")
    assert logic_check.kb_queries == ["[computer_network] 拥塞控制"]
    assert logic_check.kb_latency_ms == 15


if __name__ == "__main__":
    test_knowledge_base_retriever_search_and_format()
    asyncio.run(test_specialist_reviewer_agentic_tool_call_flow())
    asyncio.run(test_question_review_service_timing_and_kb_metrics())
    print("ALL KNOWLEDGE BASE INTEGRATION TESTS PASSED!")
