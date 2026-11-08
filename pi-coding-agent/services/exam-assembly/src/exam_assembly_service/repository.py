"""Read-only Question Bank API adapter and strict source/version verification."""
import asyncio
from typing import Protocol
from urllib.parse import quote

import httpx


class BankError(Exception):
    def __init__(self, code, *, status=None, detail=None):
        super().__init__(code)
        self.code, self.status, self.detail = code, status, detail


class QuestionBankRepository(Protocol):
    async def search_candidates(self, request: dict) -> tuple[list[dict], bool]: ...
    async def state(self, entry: dict) -> dict: ...


class HttpQuestionBankRepository:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.semaphore = asyncio.Semaphore(8)

    async def get(self, path, params=None):
        async with self.semaphore:
            try:
                response = await self.client.get(path, params=params)
            except httpx.HTTPError as exc:
                raise BankError("QUESTION_BANK_UNAVAILABLE", detail=type(exc).__name__) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise BankError("INVALID_QUESTION_BANK_RESPONSE", status=response.status_code) from exc
        if not response.is_success:
            raise BankError("QUESTION_BANK_UNAVAILABLE", status=response.status_code,
                            detail=body.get("detail", body) if isinstance(body, dict) else body)
        if not isinstance(body, dict):
            raise BankError("INVALID_QUESTION_BANK_RESPONSE")
        return body

    async def search_candidates(self, request):
        # Existing API has limit <= 100 and no pagination. Query each requested cell;
        # a full page is explicitly incomplete, never evidence of global shortage.
        queries = [dict(subject=request["subject"], question_type=request["question_type"],
                        knowledge_point=topic, difficulty=level, limit=100)
                   for topic, count in request["topic_counts"].items() if count
                   for level, count in request["difficulty_counts"].items() if count]
        pages = await asyncio.gather(*(self.get("/v1/question-bank/search", q) for q in queries))
        records, complete = {}, True
        for page in pages:
            entries = page.get("questions")
            if not isinstance(entries, list) or len(entries) > 100:
                raise BankError("INVALID_QUESTION_BANK_RESPONSE")
            complete = complete and len(entries) < 100
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("record_id"), str):
                    raise BankError("INVALID_QUESTION_BANK_RESPONSE")
                if entry["record_id"] in records and records[entry["record_id"]] != entry:
                    raise BankError("QUESTION_BANK_CHANGED", detail="Conflicting record snapshots")
                records[entry["record_id"]] = entry
        return list(records.values()), complete

    async def state(self, entry):
        doc = quote(entry["document_id"], safe="")
        question = quote(entry["question_id"], safe="")
        return await self.get(f"/v1/exam-checker/documents/{doc}/questions/{question}/state")


def verified_state(entry, state):
    """Reject outdated bank snapshots, re-review failures and content substitution."""
    payload = entry["question_json"]
    review = state.get("review", {})
    bank = state.get("question_bank", {})
    if (state.get("document_id") != entry["document_id"]
            or state.get("question_id") != entry["question_id"]
            or not entry.get("source_version_id")
            or state.get("question_version_id") != entry["source_version_id"]
            or review.get("status") != "PASS" or not review.get("review_id")
            or review.get("errors") != [] or review.get("unresolved_checks") != []
            or bank.get("status") != "STORED" or bank.get("record_id") != entry["record_id"]
            or payload.get("review_status") != "PASS"
            or payload.get("question") != state.get("question")):
        raise ValueError("题库版本、当前 PASS 审校或题目内容不匹配")
    return review["review_id"]
