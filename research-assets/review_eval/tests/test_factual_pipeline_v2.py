import asyncio
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import factual_pipeline_v2 as pipeline  # noqa: E402


class _Response:
    status_code = 200
    text = ""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return {
            "choices": [
                {"message": {"content": json.dumps(self._payload, ensure_ascii=False)}}
            ]
        }


class _Client:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = iter(responses)

    async def post(self, *_args, **_kwargs) -> _Response:
        return _Response(next(self.responses))


def test_each_claim_uses_its_own_subject(monkeypatch) -> None:
    subjects: list[str] = []

    def retrieve(subject: str, _queries: list[str], top_k: int = 2):
        subjects.append(subject)
        return ([{"content": "教材规则", "title": "test"}], 1.0)

    monkeypatch.setattr(pipeline, "targeted_retrieve", retrieve)
    monkeypatch.setattr(pipeline, "format_evidence_block", lambda _evs: "教材规则")
    client = _Client([
        {
            "claims": [
                {"claim": "断言一", "search_query": "查询一", "subject": "data_structure"},
                {"claim": "断言二", "search_query": "查询二", "subject": "computer_network"},
            ]
        },
        {"textbook_rule": "规则一", "conflict": False, "supported": True},
        {"textbook_rule": "规则二", "conflict": False, "supported": True},
    ])

    result = asyncio.run(pipeline.run_factual_pipeline_v2(
        client=client,
        base_url="https://example.test",
        api_key="key",
        model="model",
        full_text="普通题面",
    ))

    assert result.status == "CLEAN"
    assert subjects == ["data_structure", "computer_network"]


def test_missing_retrieval_evidence_is_unresolved(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "targeted_retrieve", lambda *_args, **_kwargs: ([], 1.0))
    client = _Client([
        {
            "claims": [
                {"claim": "断言", "search_query": "查询", "subject": "data_structure"}
            ]
        }
    ])

    result = asyncio.run(pipeline.run_factual_pipeline_v2(
        client=client,
        base_url="https://example.test",
        api_key="key",
        model="model",
        full_text="普通题面",
    ))

    assert result.status == "UNRESOLVED"
    assert result.has_error is False
    assert result.failures[0]["kind"] == "no_evidence"
