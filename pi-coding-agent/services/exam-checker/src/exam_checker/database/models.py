from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AssembledExamRow(Base):
    __tablename__ = "assembled_exams"
    __table_args__ = (Index("ix_assembled_exams_created", "created_at", "exam_id"),)
    exam_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_id: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    request_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    report_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    student_html: Mapped[str | None] = mapped_column(Text)
    answer_html: Mapped[str | None] = mapped_column(Text)


class AssembledExamItemRow(Base):
    __tablename__ = "assembled_exam_items"
    __table_args__ = (CheckConstraint("position > 0", name="ck_assembled_item_position"),)
    exam_id: Mapped[UUID] = mapped_column(ForeignKey("assembled_exams.exam_id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    student_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    answer_json: Mapped[dict[str, object]] = mapped_column(JSONB)


class ExamDocumentRow(Base):
    __tablename__ = "exam_documents"

    document_id: Mapped[str] = mapped_column(String, primary_key=True)
    document_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QuestionReviewRow(Base):
    __tablename__ = "question_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "question_id", "version"],
            ["question_snapshots.task_id", "question_snapshots.question_id", "question_snapshots.version"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("idempotency_key", name="uq_question_review_idempotency"),
        Index(
            "ix_question_reviews_version_created",
            "task_id",
            "question_id",
            "version",
            "created_at",
        ),
    )

    review_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    question_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    question_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    review_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QuestionBankRow(Base):
    __tablename__ = "question_bank"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "question_id", "version"],
            ["question_snapshots.task_id", "question_snapshots.question_id", "question_snapshots.version"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("task_id", "question_id", "version", name="uq_question_bank_source_version"),
        Index(
            "ix_question_bank_source_created",
            "task_id",
            "question_id",
            "created_at",
        ),
    )

    record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    question_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_review_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_reviews.review_id", ondelete="RESTRICT"), nullable=False
    )
    question_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class QuestionSnapshotRow(Base):
    __tablename__ = "question_snapshots"
    __table_args__ = (
        CheckConstraint(
            "generation_task_id IS NULL OR task_id = generation_task_id::text",
            name="ck_question_snapshot_generation_task_identity",
        ),
    )

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    question_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    generation_task_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("exam_documents.document_id", ondelete="RESTRICT"), nullable=True
    )
    revision_source: Mapped[str] = mapped_column(String, nullable=False)
    question_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_log: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
