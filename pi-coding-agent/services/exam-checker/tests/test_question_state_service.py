from __future__ import annotations

from uuid import uuid4

import pytest

from exam_checker.domain.models import (
    CheckerPayload,
    QuestionReview,
    QuestionView,
    ReviewedQuestion,
    ReviewError,
    ReviewSummary,
    ReviewTiming,
    StoredQuestionBankEntry,
)
from exam_checker.services.persistence import (
    InMemoryQuestionReviewRepository,
)
from exam_checker.services.question_state_service import QuestionStateService
from exam_checker.services.question_version_store import (
    InMemoryQuestionVersionRepository,
)


def question() -> QuestionView:
    return QuestionView(
        task_id="exam_1",
        question_id="question_1",
        question_number="1",
        question_type="single_choice",
        question_text="TCP 是否可靠？",
        options=["A. 是", "B. 否"],
        answer_text="A",
        points=2,
        subject="Computer Science",
        paper_title="Computer Networks",
        section_titles=["Single Choice"],
        numbering_path=["1", "1"],
        numbering_description="第1大题-第1小题",
        reference="",
    )


class FakeQuestionBankRepository:
    def __init__(self, entry: StoredQuestionBankEntry | None) -> None:
        self.entry = entry

    async def get_by_source(
        self, task_id: str, question_id: str
    ) -> StoredQuestionBankEntry | None:
        assert (task_id, question_id) == ("exam_1", "question_1")
        return self.entry


@pytest.mark.asyncio
async def test_state_returns_latest_version_review_and_bank_record() -> None:
    versions = InMemoryQuestionVersionRepository()
    reviews = InMemoryQuestionReviewRepository()
    await versions.initialize([question()])
    version = await versions.get_latest("exam_1", "question_1")
    review = ReviewedQuestion(
        task_id="exam_1",
        question_id="question_1",
        question_number="1",
        version=version.version,
        idempotency_key="state-review-1",
        review_id=str(uuid4()),
        question=CheckerPayload(reference="", detection_content="TCP 是否可靠？"),
        review=QuestionReview(
            status="NEEDS_REVISION",
            routing={},
            checks=[],
            summary=ReviewSummary(
                has_error=True,
                total_errors=1,
                errors=[ReviewError(error_type="事实/逻辑错误")],
                unresolved_checks=[],
            ),
            timing_ms=ReviewTiming(routing=0, specialist_checks=1, total=1),
        ),
    )
    await reviews.save(review)
    entry = StoredQuestionBankEntry(
        record_id=str(uuid4()),
        task_id="exam_1",
        question_id="question_1",
        version=version.version,
        question_json={"question": question().model_dump(mode="json")},
    )
    service = QuestionStateService(
        version_repository=versions,
        review_repository=reviews,
        question_bank_repository=FakeQuestionBankRepository(entry),
    )

    state = await service.get("exam_1", "question_1")

    assert state.version == version.version
    assert state.review.status == "NEEDS_REVISION"
    assert state.review.errors[0].error_type == "事实/逻辑错误"
    assert state.question_bank.status == "STORED"
    assert state.question_bank.record_id == entry.record_id


@pytest.mark.asyncio
async def test_state_does_not_reuse_review_from_an_older_version() -> None:
    versions = InMemoryQuestionVersionRepository()
    reviews = InMemoryQuestionReviewRepository()
    original = question()
    await versions.initialize([original])
    first = await versions.get_latest("exam_1", "question_1")
    old_review = ReviewedQuestion(
        task_id="exam_1",
        question_id="question_1",
        question_number="1",
        version=first.version,
        idempotency_key="state-review-old",
        review_id=str(uuid4()),
        question=CheckerPayload(reference="", detection_content="TCP 是否可靠？"),
        review=QuestionReview(
            status="PASS",
            routing={},
            checks=[],
            summary=ReviewSummary(
                has_error=False,
                total_errors=0,
                errors=[],
                unresolved_checks=[],
            ),
            timing_ms=ReviewTiming(routing=0, specialist_checks=1, total=1),
        ),
    )
    await reviews.save(old_review)
    await versions.import_generated(
        task_id="exam_1",
        question_id="question_1",
        version=first.version + 1,
        question=original.model_copy(update={"question_text": "修改后的题目"}),
    )
    service = QuestionStateService(
        version_repository=versions,
        review_repository=reviews,
        question_bank_repository=None,
    )

    state = await service.get("exam_1", "question_1")

    assert state.review.status == "NOT_REVIEWED"
    assert state.question_bank.status == "NOT_CONFIGURED"
