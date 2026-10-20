from __future__ import annotations

import json

import httpx
import pytest

from exam_checker.parsing.structure_extractor import (
    OpenAICompatibleStructureExtractor,
    StructureExtractionError,
)


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


@pytest.mark.asyncio
async def test_structure_extractor_calls_openai_compatible_endpoint() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer secret"
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["enable_thinking"] is False
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        if call_count == 1:
            content = json.dumps(
                {
                    "paper": {"title": "Test"},
                    "questions": [
                        {
                            "id": "1",
                            "title": "Section One",
                            "children": [{"id": "1", "content": ""}],
                        }
                    ],
                }
            )
        else:
            assert "Section One" in body["messages"][1]["content"]
            content = json.dumps(
                {
                    "id": "1",
                    "title": "Section One",
                    "children": [{"id": "1", "content": "Question"}],
                }
            )
        return stream_response(f"```json\n{content}\n```")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        extractor = OpenAICompatibleStructureExtractor(
            "https://llm.example.test/v1",
            "secret",
            "model",
            client=client,
        )
        result = await extractor.extract("# Exam\nSection One\n1. Question")

    assert result["paper"] == {"title": "Test"}
    assert result["questions"][0]["children"][0]["content"] == "Question"
    assert call_count == 2


@pytest.mark.asyncio
async def test_structure_extractor_maps_provider_error() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable"))
    ) as client:
        extractor = OpenAICompatibleStructureExtractor(
            "https://llm.example.test/v1",
            "secret",
            "model",
            client=client,
        )
        with pytest.raises(StructureExtractionError, match="HTTP 503"):
            await extractor.extract("# Exam")


@pytest.mark.asyncio
async def test_structure_extractor_repairs_only_an_empty_question() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        call_number = len(requests)
        if call_number == 1:
            content = {
                "paper": {"title": "Test"},
                "questions": [
                    {
                        "id": "3",
                        "title": "判断题",
                        "children": [
                            {"id": "1", "content": ""},
                            {"id": "2", "content": ""},
                        ],
                    }
                ],
            }
        elif call_number == 2:
            content = {
                "id": "3",
                "title": "判断题",
                "children": [
                    {"id": "1", "content": "第一题"},
                    {"id": "2", "content": ""},
                ],
            }
        else:
            content = {"id": "2", "content": "第二题"}
        return stream_response(json.dumps(content, ensure_ascii=False))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        extractor = OpenAICompatibleStructureExtractor(
            "https://llm.example.test/v1",
            "secret",
            "model",
            client=client,
        )
        result = await extractor.extract("# Exam\n三、判断题\n1. 第一题\n2. 第二题")

    questions = result["questions"][0]["children"]
    assert questions[0]["content"] == "第一题"
    assert questions[1]["content"] == "第二题"
    assert len(requests) == 3
    assert "单道缺失题目补全工具" in requests[2]["messages"][0]["content"]
    assert "<target_path>root.3.2</target_path>" in requests[2]["messages"][1][
        "content"
    ]


@pytest.mark.asyncio
async def test_structure_extractor_reports_the_specific_unrepaired_question() -> None:
    call_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            content = {
                "paper": {"title": "Test"},
                "questions": [
                    {
                        "id": "3",
                        "title": "判断题",
                        "children": [{"id": "7", "content": ""}],
                    }
                ],
            }
        elif call_count == 2:
            content = {
                "id": "3",
                "title": "判断题",
                "children": [{"id": "7", "content": ""}],
            }
        else:
            content = {"id": "7", "content": ""}
        return stream_response(json.dumps(content, ensure_ascii=False))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        extractor = OpenAICompatibleStructureExtractor(
            "https://llm.example.test/v1",
            "secret",
            "model",
            client=client,
        )
        with pytest.raises(
            StructureExtractionError,
            match=r"Question repair failed after three attempts at root\.3\.7",
        ):
            await extractor.extract("# Exam\n三、判断题\n7. 第七题")

    assert call_count == 5
