from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from ..domain.models import (
    IngestionResult,
    QuestionChangeLog,
    QuestionMetadata,
    QuestionRevisionResult,
    QuestionView,
    ReviewedQuestion,
    ReviewError,
    StoredQuestionVersion,
)
from .persistence import QuestionReviewRepository, QuestionVersionRepository
from .question_bank_service import QuestionBankService
from .question_review_service import QuestionReviewService
from .question_service import QuestionService


class QuestionRevisionNotAllowedError(ValueError):
    pass


class QuestionIdentityError(ValueError):
    pass


class QuestionWorkflowModel(Protocol):
    model: str

    async def revise(
        self,
        question: QuestionView,
        errors: list[ReviewError],
        user_instruction: str,
        proposed_question: QuestionView | None = None,
    ) -> QuestionRevisionResult: ...

    async def annotate(self, question: QuestionView) -> QuestionMetadata: ...


class QuestionWorkflowService:
    def __init__(
        self,
        *,
        version_repository: QuestionVersionRepository,
        review_repository: QuestionReviewRepository,
        review_service: QuestionReviewService,
        model: QuestionWorkflowModel,
        question_bank_service: QuestionBankService | None,
    ) -> None:
        self.version_repository = version_repository
        self.review_repository = review_repository
        self.review_service = review_service
        self.model = model
        self.question_bank_service = question_bank_service

    async def review_latest(
        self, task_id: str, question_id: str, *, idempotency_key: str | None = None
    ) -> ReviewedQuestion:
        version = await self.version_repository.get_latest(task_id, question_id)
        return await self._review_version(version, idempotency_key or str(uuid4()))

    async def review_version(
        self,
        task_id: str,
        question_id: str,
        version: int,
        *,
        idempotency_key: str,
    ) -> ReviewedQuestion:
        snapshot = await self.version_repository.get(task_id, question_id, version)
        return await self._review_version(snapshot, idempotency_key)

    async def revise_and_review(
        self,
        *,
        task_id: str,
        question_id: str,
        base_version: int,
        question_json: dict[str, object] | None,
        user_instruction: str,
        idempotency_key: str,
    ) -> ReviewedQuestion:
        current = await self.version_repository.get_latest(task_id, question_id)
        if current.version != base_version:
            from .persistence import QuestionVersionConflictError

            raise QuestionVersionConflictError(
                "The question changed after the requested base version"
            )
        stored_review = await self.review_repository.get_latest_for_version(
            task_id, question_id, current.version
        )
        if stored_review.review.review.status != "NEEDS_REVISION":
            raise QuestionRevisionNotAllowedError(
                "Revision requires a latest NEEDS_REVISION review"
            )
        review_feedback = stored_review.review.review.summary.errors
        proposed_question = (
            QuestionView.model_validate(question_json)
            if question_json is not None
            else None
        )
        revision_result = await self.model.revise(
            current.question,
            review_feedback,
            user_instruction,
            proposed_question,
        )
        revised = revision_result.question
        revision_source = "USER_EDIT" if proposed_question is not None else "AI_EDIT"
        self._validate_identity(current.question, revised)
        change_log = QuestionChangeLog(
            user_instruction=user_instruction,
            review_feedback=review_feedback,
            changes=revision_result.changes,
            model=self.model.model,
        )
        version = await self.version_repository.create_revision(
            task_id=task_id,
            question_id=question_id,
            base_version=base_version,
            revision_source=revision_source,
            question=revised,
            change_log=change_log,
        )
        return await self._review_version(version, idempotency_key)

    async def _review_version(
        self, version: StoredQuestionVersion, idempotency_key: str
    ) -> ReviewedQuestion:
        existing = await self.review_repository.get_by_idempotency(idempotency_key)
        if existing is not None:
            if (
                existing.review.task_id != version.task_id
                or existing.review.question_id != version.question_id
                or existing.review.version != version.version
            ):
                raise QuestionIdentityError(
                    "idempotency_key is already bound to another question version"
                )
            return existing.review
        question = version.question
        payload = QuestionService.to_checker_payload_from_view(question)
        reviewed = await self.review_service.review_question(
            task_id=question.task_id,
            question_id=question.question_id,
            question_number=question.question_number,
            version=version.version,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reviewed.review.status != "PASS":
            return reviewed
        if self.question_bank_service is None:
            return reviewed.model_copy(
                update={
                    "ingestion": IngestionResult(
                        status="SKIPPED", error_code="DATABASE_NOT_CONFIGURED"
                    )
                }
            )
        try:
            metadata = await self.model.annotate(question)
            bank_json = {
                "task_id": question.task_id,
                "question_id": question.question_id,
                "version": version.version,
                "question": question.model_dump(mode="json"),
                "review_status": "PASS",
                "metadata": metadata.model_dump(mode="json"),
            }
            ingestion = await self.question_bank_service.ingest(
                task_id=question.task_id,
                question_id=question.question_id,
                version=version.version,
                question_json=bank_json,
            )
        except Exception as exc:
            ingestion = IngestionResult(
                status="FAILED", error_code=type(exc).__name__
            )
        return reviewed.model_copy(update={"ingestion": ingestion})

    @staticmethod
    def _validate_identity(original: QuestionView, revised: QuestionView) -> None:
        if revised.task_id != original.task_id:
            raise QuestionIdentityError("task_id cannot be changed")
        if revised.question_id != original.question_id:
            raise QuestionIdentityError("question_id cannot be changed")
