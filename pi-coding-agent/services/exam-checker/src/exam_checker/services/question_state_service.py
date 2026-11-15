from __future__ import annotations

from ..domain.models import (
    QuestionBankState,
    QuestionState,
    QuestionStateReview,
)
from .persistence import (
    QuestionBankRepository,
    QuestionReviewRepository,
    QuestionVersionRepository,
    ReviewNotFoundError,
)


class QuestionStateService:
    def __init__(
        self,
        *,
        version_repository: QuestionVersionRepository,
        review_repository: QuestionReviewRepository,
        question_bank_repository: QuestionBankRepository | None,
    ) -> None:
        self.version_repository = version_repository
        self.review_repository = review_repository
        self.question_bank_repository = question_bank_repository

    async def get(self, task_id: str, question_id: str) -> QuestionState:
        version = await self.version_repository.get_latest(task_id, question_id)
        try:
            stored_review = await self.review_repository.get_latest_for_version(
                task_id, question_id, version.version
            )
        except ReviewNotFoundError:
            review = QuestionStateReview(status="NOT_REVIEWED")
        else:
            summary = stored_review.review.review.summary
            review = QuestionStateReview(
                status=stored_review.review.review.status,
                review_id=str(stored_review.review_id),
                errors=summary.errors,
                unresolved_checks=summary.unresolved_checks,
            )

        if self.question_bank_repository is None:
            bank_state = QuestionBankState(status="NOT_CONFIGURED")
        else:
            stored_question = await self.question_bank_repository.get_by_source(
                task_id, question_id
            )
            if stored_question is None:
                bank_status = "NOT_STORED"
            elif stored_question.version == version.version:
                bank_status = "STORED"
            else:
                bank_status = "OUTDATED"
            bank_state = QuestionBankState(
                status=bank_status,
                record_id=(
                    stored_question.record_id if stored_question is not None else None
                ),
            )

        return QuestionState(
            task_id=task_id,
            question_id=question_id,
            version=version.version,
            revision_source=version.revision_source,
            question=version.question,
            change_log=version.change_log,
            review=review,
            question_bank=bank_state,
        )
