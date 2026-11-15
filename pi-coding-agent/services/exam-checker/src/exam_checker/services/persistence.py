from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID
from uuid import uuid4

from ..domain.models import (
    QuestionView,
    ReviewedQuestion,
    StoredQuestionBankEntry,
    StoredQuestionVersion,
)


class ReviewNotFoundError(KeyError):
    pass


class QuestionAlreadyStoredError(ValueError):
    pass


class QuestionBankEntryNotFoundError(KeyError):
    pass


class QuestionVersionNotFoundError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class StoredQuestionReview:
    review_id: UUID
    review: ReviewedQuestion
    question_snapshot: dict[str, Any] | None = None


class QuestionReviewRepository(Protocol):
    async def save(self, review: ReviewedQuestion) -> UUID: ...

    async def get_by_idempotency(
        self, idempotency_key: str
    ) -> StoredQuestionReview | None: ...

    async def get_latest(
        self, task_id: str, question_id: str
    ) -> StoredQuestionReview: ...

    async def get_latest_for_version(
        self, task_id: str, question_id: str, version: int
    ) -> StoredQuestionReview: ...


class QuestionBankRepository(Protocol):
    async def store(
        self,
        *,
        record_id: UUID,
        source_review_id: UUID,
        task_id: str,
        question_id: str,
        version: int,
        question_json: dict[str, Any],
    ) -> UUID: ...

    async def get(self, record_id: UUID) -> StoredQuestionBankEntry: ...

    async def get_by_source(
        self, task_id: str, question_id: str
    ) -> StoredQuestionBankEntry | None: ...

    async def search(
        self,
        *,
        subject: str | None,
        question_type: str | None,
        difficulty: str | None,
        knowledge_point: str | None,
        keyword: str | None,
        limit: int,
    ) -> list[StoredQuestionBankEntry]: ...


class QuestionVersionRepository(Protocol):
    async def initialize(self, questions: list[QuestionView]) -> None: ...

    async def get_latest(
        self, task_id: str, question_id: str
    ) -> StoredQuestionVersion: ...

    async def get(
        self, task_id: str, question_id: str, version: int
    ) -> StoredQuestionVersion: ...

    async def import_generated(
        self, *, task_id: str, question_id: str, version: int, question: QuestionView
    ) -> StoredQuestionVersion: ...

class InMemoryQuestionReviewRepository:
    def __init__(self) -> None:
        self._reviews: dict[tuple[str, str], list[StoredQuestionReview]] = {}
        self._idempotent: dict[str, StoredQuestionReview] = {}

    async def save(self, review: ReviewedQuestion) -> UUID:
        existing = self._idempotent.get(review.idempotency_key)
        if existing is not None:
            return existing.review_id
        review_id = UUID(review.review_id) if review.review_id else uuid4()
        stored = StoredQuestionReview(review_id=review_id, review=review)
        self._reviews.setdefault((review.task_id, review.question_id), []).append(stored)
        self._idempotent[review.idempotency_key] = stored
        return review_id

    async def get_by_idempotency(
        self, idempotency_key: str
    ) -> StoredQuestionReview | None:
        return self._idempotent.get(idempotency_key)

    async def get_latest(
        self, task_id: str, question_id: str
    ) -> StoredQuestionReview:
        reviews = self._reviews.get((task_id, question_id))
        if not reviews:
            raise ReviewNotFoundError((task_id, question_id))
        return reviews[-1]

    async def get_latest_for_version(
        self, task_id: str, question_id: str, version: int
    ) -> StoredQuestionReview:
        reviews = self._reviews.get((task_id, question_id), [])
        for stored in reversed(reviews):
            if stored.review.version == version:
                return stored
        raise ReviewNotFoundError((task_id, question_id, version))
