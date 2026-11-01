from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from exam_checker.domain.models import CheckerPayload, SpecialistReviewResult
from exam_checker.integrations.specialist_reviewer import (
    OpenAICompatibleSpecialistReviewer,
    SpecialistReviewError,
)


class FakePrompts:
    def system_prompt(self, task_id: str) -> str:
        return f"PROMPT:{task_id}"


def stream_response(content: str) -> httpx.Response:
    midpoint = len(content) // 2
    events = [
        {"choices": [{"delta": {"content": content[:midpoint]}}]},
        {"choices": [{"delta": {"content": content[midpoint:]}}]},
    ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return httpx.Response(
        200,
        text=f"{body}data: [DONE]\n\n",
        headers={"content-type": "text/event-stream"},
    )


def test_parse_content_extracts_complete_json_after_prefix_noise() -> None:
    result = OpenAICompatibleSpecialistReviewer._parse_content(
        '根据检索结果，最终结论如下：\n'
        '{"reason":"未发现问题","has_error":false,'
        '"total_errors":0,"errors":[]}'
    )

    assert result.has_error is False
    assert result.total_errors == 0


def test_parse_content_rejects_truncated_json_without_fabricating_fields() -> None:
    with pytest.raises(SpecialistReviewError) as raised:
        OpenAICompatibleSpecialistReviewer._parse_content(
            '{"reason":"发现问题","has_error":true,'
        )

    assert raised.value.error_code == "JSON_TRUNCATED"


def test_parse_content_rejects_schema_invalid_complete_json() -> None:
    with pytest.raises(SpecialistReviewError) as raised:
        OpenAICompatibleSpecialistReviewer._parse_content(
            '{"reason":"字段不足","has_error":false}'
        )

    assert raised.value.error_code == "JSON_SCHEMA_INVALID"


def test_compact_json_regeneration_reuses_context_without_tools() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tool_choice"] == "none"
        assert "tools" not in body
        assert body["response_format"] == {"type": "json_object"}
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert "think 字段" in body["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "reason": "未发现问题",
                                    "has_error": False,
                                    "total_errors": 0,
                                    "errors": [],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ]
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            reviewer = OpenAICompatibleSpecialistReviewer(
                "https://llm.example/v1",
                "secret",
                "qwen3.8-27b",
                FakePrompts(),
                client=client,
            )
            result = await reviewer._regenerate_compact_json(
                [
                    {"role": "system", "content": "PROMPT:logic_check"},
                    {"role": "assistant", "content": '{"reason":"被截断"'},
                ]
            )
            assert result.has_error is False

    asyncio.run(run())


def test_validation_restores_original_whitespace_from_payload() -> None:
    result = SpecialistReviewResult.model_validate(
        {
            "reason": "存在问题",
            "has_error": True,
            "total_errors": 1,
            "errors": [
                {
                    "error_type": "语义不清",
                    "original_text": "至少 是",
                }
            ],
        }
    )

    OpenAICompatibleSpecialistReviewer._validate_result(
        "ambiguity_check",
        result,
        CheckerPayload(reference="", detection_content="个数至少\n是 。"),
    )

    assert result.errors[0].original_text == "至少\n是"


def test_validation_drops_unanchored_model_findings() -> None:
    result = SpecialistReviewResult.model_validate(
        {
            "reason": "存在问题",
            "has_error": True,
            "total_errors": 1,
            "errors": [
                {
                    "error_type": "事实/逻辑错误",
                    "original_text": "模型臆造的原文",
                }
            ],
        }
    )

    OpenAICompatibleSpecialistReviewer._validate_result(
        "logic_check",
        result,
        CheckerPayload(reference="", detection_content="实际题目文本"),
    )

    assert result.has_error is False
    assert result.total_errors == 0
    assert result.errors == []


def test_validation_protects_valid_domain_term_from_typo_expansion() -> None:
    result = SpecialistReviewResult.model_validate(
        {
            "reason": "存在问题",
            "has_error": True,
            "total_errors": 1,
            "errors": [
                {
                    "error_type": "错别字",
                    "original_text": "界地址保护",
                    "correction": "界限地址保护",
                }
            ],
        }
    )

    OpenAICompatibleSpecialistReviewer._validate_result(
        "typo_check",
        result,
        CheckerPayload(reference="", detection_content="A. 界地址保护"),
    )

    assert result.has_error is False
    assert result.errors == []


def test_builtin_timeout_is_retried_and_classified() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise TimeoutError()

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            reviewer = OpenAICompatibleSpecialistReviewer(
                "https://llm.example/v1",
                "secret",
                "qwen3.8-27b",
                FakePrompts(),
                max_attempts=3,
                retry_base_delay_seconds=0,
                client=client,
            )
            with pytest.raises(SpecialistReviewError) as raised:
                await reviewer.review(
                    "typo_check",
                    CheckerPayload(reference="", detection_content="计算机网络"),
                )
            assert raised.value.error_code == "UPSTREAM_TIMEOUT"
            assert raised.value.attempts == 3

    asyncio.run(run())
    assert request_count == 3


@pytest.mark.asyncio
async def test_specialist_reviewer_uses_input_payload_and_parses_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == "PROMPT:typo_check"
        assert body["messages"][1]["content"].startswith("[INPUT_PAYLOAD]\n")
        assert body["enable_thinking"] is False
        assert body["stream"] is True
        return stream_response(
            json.dumps(
                {
                    "reason": "存在错别字",
                    "has_error": True,
                    "total_errors": 1,
                    "errors": [
                        {
                            "error_type": "错别字",
                            "position": "题干",
                            "original_text": "计祘机",
                            "anchor_text": "计祘机网络",
                            "correction": "计算机",
                            "description": "存在错别字。",
                            "suggestion": "将计祘机改为计算机。",
                            "severity": "严重",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reviewer = OpenAICompatibleSpecialistReviewer(
            "https://llm.example/v1",
            "secret",
            "qwen3.8-27b",
            FakePrompts(),
            client=client,
        )
        result, latency_ms, attempts = await reviewer.review(
            "typo_check",
            CheckerPayload(reference="【学科】计算机", detection_content="计祘机网络"),
        )

    assert result.has_error
    assert result.errors[0].correction == "计算机"
    assert latency_ms >= 0
    assert attempts == 1


@pytest.mark.asyncio
async def test_specialist_reviewer_retries_retryable_failures() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count < 3:
            return httpx.Response(503, text="temporarily unavailable")
        return stream_response(
            json.dumps(
                {
                    "reason": "未发现问题",
                    "has_error": False,
                    "total_errors": 0,
                    "errors": [],
                },
                ensure_ascii=False,
            )
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reviewer = OpenAICompatibleSpecialistReviewer(
            "https://llm.example/v1",
            "secret",
            "qwen3.8-27b",
            FakePrompts(),
            max_attempts=3,
            retry_base_delay_seconds=0,
            client=client,
        )
        result, _, attempts = await reviewer.review(
            "typo_check",
            CheckerPayload(reference="", detection_content="计算机网络"),
        )

    assert result.has_error is False
    assert attempts == 3
    assert request_count == 3


@pytest.mark.asyncio
async def test_specialist_reviewer_reports_exhausted_retry_metadata() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(429, text="rate limited")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reviewer = OpenAICompatibleSpecialistReviewer(
            "https://llm.example/v1",
            "secret",
            "qwen3.8-27b",
            FakePrompts(),
            max_attempts=3,
            retry_base_delay_seconds=0,
            client=client,
        )
        with pytest.raises(SpecialistReviewError) as raised:
            await reviewer.review(
                "typo_check",
                CheckerPayload(reference="", detection_content="计算机网络"),
            )

    assert raised.value.error_code == "RATE_LIMITED"
    assert raised.value.retryable is True
    assert raised.value.attempts == 3
    assert request_count == 3
