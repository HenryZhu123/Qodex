from __future__ import annotations

from uuid import uuid4

import pytest

from exam_checker.domain.models import (
    QuestionMetadata,
    QuestionReview,
    QuestionView,
    ReviewedQuestion,
    ReviewSummary,
    ReviewTiming,
)
from exam_checker.services.persistence import InMemoryQuestionReviewRepository
from exam_checker.services.question_version_store import (
    InMemoryQuestionVersionRepository,
)
from exam_checker.services.question_workflow_service import QuestionWorkflowService


def make_question() -> QuestionView:
    return QuestionView(
        task_id="exam_1",
        question_id="question_1",
        question_number="1",
        question_type="single_choice",
        question_text="以下哪项错吴？",
        options=["A. 甲", "B. 乙"],
        answer_text="A",
        points=2,
        subject="计算机",
        paper_title="测试卷",
        section_titles=["选择题"],
        numbering_path=["1", "1"],
        numbering_description="第1大题-第1小题",
        reference="",
    )


class FakeModel:
    model = "metadata-model"

    async def annotate(self, question):
        return QuestionMetadata(
            difficulty="easy", knowledge_points=["基础概念"]
        )


class PassingReviewService:
    def __init__(self, repository) -> None:
        self.repository = repository
        self.calls: list[str] = []

    async def review_question(
        self,
        *,
        task_id,
        question_id,
        question_number,
        version,
        idempotency_key,
        payload,
    ):
        self.calls.append(version)
        review = ReviewedQuestion(
            task_id=task_id,
            question_id=question_id,
            question_number=question_number,
            version=version,
            idempotency_key=idempotency_key,
            review_id=str(uuid4()),
            question=payload,
            review=QuestionReview(
                status="PASS",
                checks=[],
                summary=ReviewSummary(
                    has_error=False,
                    total_errors=0,
                    errors=[],
                    unresolved_checks=[],
                ),
                timing_ms=ReviewTiming(routing=0, specialist_checks=0, total=1),
            ),
        )
        await self.repository.save(review)
        return review


@pytest.mark.asyncio
async def test_review_idempotency_key_reuses_the_first_review() -> None:
    question = make_question()
    versions = InMemoryQuestionVersionRepository()
    await versions.initialize([question])
    reviews = InMemoryQuestionReviewRepository()
    reviewer = PassingReviewService(reviews)
    workflow = QuestionWorkflowService(
        version_repository=versions,
        review_repository=reviews,
        review_service=reviewer,
        model=FakeModel(),
        question_bank_service=None,
    )

    first = await workflow.review_latest(
        "exam_1", "question_1", idempotency_key="same-call"
    )
    second = await workflow.review_latest(
        "exam_1", "question_1", idempotency_key="same-call"
    )

    assert second.review_id == first.review_id
    assert reviewer.calls == [1]
