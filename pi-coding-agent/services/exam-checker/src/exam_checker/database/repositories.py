from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.models import (
    ExamDocument,
    QuestionChangeLog,
    QuestionView,
    ReviewedQuestion,
    StoredQuestionBankEntry,
    StoredQuestionVersion,
)
from ..services.document_store import DocumentNotFoundError
from ..services.persistence import (
    QuestionBankEntryNotFoundError,
    ReviewNotFoundError,
    QuestionVersionNotFoundError,
    StoredQuestionReview,
)
from .models import (
    ExamDocumentRow,
    QuestionBankRow,
    QuestionReviewRow,
    QuestionSnapshotRow,
)


class PostgresExamDocumentStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def save(self, document: ExamDocument) -> None:
        statement = insert(ExamDocumentRow).values(
            document_id=document.document_id,
            document_json=document.model_dump(mode="json"),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[ExamDocumentRow.document_id],
            set_={"document_json": statement.excluded.document_json},
        )
        async with self.sessions.begin() as session:
            await session.execute(statement)

    async def get(self, document_id: str) -> ExamDocument:
        async with self.sessions() as session:
            payload = await session.scalar(
                select(ExamDocumentRow.document_json).where(
                    ExamDocumentRow.document_id == document_id
                )
            )
        if payload is None:
            raise DocumentNotFoundError(document_id)
        return ExamDocument.model_validate(payload)


class PostgresQuestionReviewRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def save(self, review: ReviewedQuestion) -> UUID:
        review_id = UUID(review.review_id) if review.review_id else uuid4()
        async with self.sessions.begin() as session:
            question_json = await session.scalar(
                select(QuestionSnapshotRow.question_json).where(
                    QuestionSnapshotRow.task_id == review.task_id,
                    QuestionSnapshotRow.question_id == review.question_id,
                    QuestionSnapshotRow.version == review.version,
                )
            )
            if question_json is None:
                raise QuestionVersionNotFoundError(
                    (review.task_id, review.question_id, review.version)
                )
            statement = insert(QuestionReviewRow).values(
                review_id=review_id,
                task_id=review.task_id,
                question_id=review.question_id,
                version=review.version,
                idempotency_key=review.idempotency_key,
                question_json=question_json,
                review_json=review.model_dump(mode="json"),
            )
            statement = statement.on_conflict_do_nothing(
                constraint="uq_question_review_idempotency"
            ).returning(QuestionReviewRow.review_id)
            stored_id = await session.scalar(statement)
            if stored_id is None:
                stored_id = await session.scalar(
                    select(QuestionReviewRow.review_id).where(
                        QuestionReviewRow.idempotency_key == review.idempotency_key
                    )
                )
        assert stored_id is not None
        return stored_id

    async def get_by_idempotency(self, idempotency_key: str) -> StoredQuestionReview | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(QuestionReviewRow).where(
                    QuestionReviewRow.idempotency_key == idempotency_key
                )
            )
        return self._to_domain(row) if row is not None else None

    async def get_latest(
        self, task_id: str, question_id: str
    ) -> StoredQuestionReview:
        statement = (
            select(QuestionReviewRow)
            .where(
                QuestionReviewRow.task_id == task_id,
                QuestionReviewRow.question_id == question_id,
            )
            .order_by(QuestionReviewRow.created_at.desc())
            .limit(1)
        )
        async with self.sessions() as session:
            row = await session.scalar(statement)
        if row is None:
            raise ReviewNotFoundError((task_id, question_id))
        return self._to_domain(row)

    async def get_latest_for_version(
        self, task_id: str, question_id: str, version: int
    ) -> StoredQuestionReview:
        statement = (
            select(QuestionReviewRow)
            .where(
                QuestionReviewRow.task_id == task_id,
                QuestionReviewRow.question_id == question_id,
                QuestionReviewRow.version == version,
            )
            .order_by(QuestionReviewRow.created_at.desc())
            .limit(1)
        )
        async with self.sessions() as session:
            row = await session.scalar(statement)
        if row is None:
            raise ReviewNotFoundError(
                (task_id, question_id, version)
            )
        return self._to_domain(row)

    @staticmethod
    def _to_domain(row: QuestionReviewRow) -> StoredQuestionReview:
        return StoredQuestionReview(
            review_id=row.review_id,
            review=ReviewedQuestion.model_validate(row.review_json),
            question_snapshot=row.question_json,
        )


class PostgresQuestionBankRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def store(
        self,
        *,
        record_id: UUID,
        source_review_id: UUID,
        task_id: str,
        question_id: str,
        version: int,
        question_json: dict[str, Any],
    ) -> UUID:
        statement = insert(QuestionBankRow).values(
            record_id=record_id,
            task_id=task_id,
            question_id=question_id,
            version=version,
            source_review_id=source_review_id,
            question_json=question_json,
        )
        statement = statement.on_conflict_do_nothing(
            constraint="uq_question_bank_source_version"
        ).returning(QuestionBankRow.record_id)
        async with self.sessions.begin() as session:
            stored_id = await session.scalar(statement)
            if stored_id is None:
                stored_id = await session.scalar(
                select(QuestionBankRow.record_id).where(
                    QuestionBankRow.task_id == task_id,
                    QuestionBankRow.question_id == question_id,
                    QuestionBankRow.version == version,
                )
            )
        assert stored_id is not None
        return stored_id

    async def get(self, record_id: UUID) -> StoredQuestionBankEntry:
        async with self.sessions() as session:
            row = await session.get(QuestionBankRow, record_id)
        if row is None:
            raise QuestionBankEntryNotFoundError(record_id)
        return self._to_domain(row)

    async def get_by_source(
        self, task_id: str, question_id: str
    ) -> StoredQuestionBankEntry | None:
        statement = select(QuestionBankRow).where(
            QuestionBankRow.task_id == task_id,
            QuestionBankRow.question_id == question_id,
        ).order_by(QuestionBankRow.version.desc()).limit(1)
        async with self.sessions() as session:
            row = await session.scalar(statement)
        return self._to_domain(row) if row is not None else None

    async def search(
        self,
        *,
        subject: str | None,
        question_type: str | None,
        difficulty: str | None,
        knowledge_point: str | None,
        keyword: str | None,
        limit: int,
    ) -> list[StoredQuestionBankEntry]:
        statement = select(QuestionBankRow)
        if subject:
            statement = statement.where(
                QuestionBankRow.question_json["question"]["subject"].astext
                == subject
            )
        if question_type:
            statement = statement.where(
                QuestionBankRow.question_json["question"]["question_type"].astext
                == question_type
            )
        if difficulty:
            statement = statement.where(
                QuestionBankRow.question_json["metadata"]["difficulty"].astext
                == difficulty
            )
        if knowledge_point:
            statement = statement.where(
                QuestionBankRow.question_json["metadata"][
                    "knowledge_points"
                ].contains([knowledge_point])
            )
        if keyword:
            statement = statement.where(
                QuestionBankRow.question_json["question"]["question_text"]
                .astext.ilike(f"%{keyword}%")
            )
        statement = statement.order_by(QuestionBankRow.created_at.desc()).limit(limit)
        async with self.sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: QuestionBankRow) -> StoredQuestionBankEntry:
        return StoredQuestionBankEntry(
            record_id=str(row.record_id),
            task_id=row.task_id,
            question_id=row.question_id,
            version=row.version,
            question_json=row.question_json,
        )


class PostgresQuestionVersionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def initialize(self, questions: list[QuestionView]) -> None:
        if not questions:
            return
        async with self.sessions.begin() as session:
            for question in questions:
                statement = insert(QuestionSnapshotRow).values(
                    task_id=question.task_id,
                    question_id=question.question_id,
                    version=1,
                    generation_task_id=None,
                    source_document_id=question.task_id,
                    revision_source="PARSED",
                    question_json=question.model_dump(mode="json"),
                    change_log=None,
                )
                await session.execute(
                    statement.on_conflict_do_nothing(
                        index_elements=[
                            QuestionSnapshotRow.task_id,
                            QuestionSnapshotRow.question_id,
                            QuestionSnapshotRow.version,
                        ]
                    )
                )

    async def get_latest(
        self, task_id: str, question_id: str
    ) -> StoredQuestionVersion:
        statement = (
            select(QuestionSnapshotRow)
            .where(
                QuestionSnapshotRow.task_id == task_id,
                QuestionSnapshotRow.question_id == question_id,
            )
            .order_by(QuestionSnapshotRow.version.desc())
            .limit(1)
        )
        async with self.sessions() as session:
            row = await session.scalar(statement)
        if row is None:
            raise QuestionVersionNotFoundError((task_id, question_id))
        return self._to_domain(row)

    async def get(self, task_id: str, question_id: str, version: int) -> StoredQuestionVersion:
        async with self.sessions() as session:
            row = await session.get(QuestionSnapshotRow, (task_id, question_id, version))
        if row is None:
            raise QuestionVersionNotFoundError((task_id, question_id, version))
        return self._to_domain(row)

    async def import_generated(
        self, *, task_id: str, question_id: str, version: int, question: QuestionView
    ) -> StoredQuestionVersion:
        statement = insert(QuestionSnapshotRow).values(
            task_id=task_id,
            question_id=question_id,
            version=version,
            generation_task_id=UUID(task_id),
            source_document_id=None,
            revision_source="GENERATED",
            question_json=question.model_dump(mode="json"),
            change_log=None,
        ).on_conflict_do_nothing(
            index_elements=[
                QuestionSnapshotRow.task_id,
                QuestionSnapshotRow.question_id,
                QuestionSnapshotRow.version,
            ]
        )
        async with self.sessions.begin() as session:
            await session.execute(statement)
        stored = await self.get(task_id, question_id, version)
        if stored.question != question or stored.revision_source != "GENERATED":
            raise ValueError(
                "Generated version content conflicts with the imported snapshot"
            )
        return stored

    @staticmethod
    def _to_domain(row: QuestionSnapshotRow) -> StoredQuestionVersion:
        return StoredQuestionVersion(
            task_id=row.task_id,
            question_id=row.question_id,
            version=row.version,
            revision_source=row.revision_source,
            question=QuestionView.model_validate(row.question_json),
            change_log=(
                QuestionChangeLog.model_validate(row.change_log)
                if row.change_log is not None
                else None
            ),
        )
