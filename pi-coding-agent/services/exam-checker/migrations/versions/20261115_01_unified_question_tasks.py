"""Replace UUID question versions with task-scoped immutable snapshots.

Revision ID: 20261115_01
Revises: 20261111_01
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261115_01"
down_revision: str | None = "20261111_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "question_snapshots",
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("question_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.String(), nullable=True),
        sa.Column("revision_source", sa.String(), nullable=False),
        sa.Column("question_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("change_log", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_question_snapshot_version"),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["exam_documents.document_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("task_id", "question_id", "version"),
    )
    op.execute(
        """
        INSERT INTO question_snapshots (
            task_id, question_id, version, source_document_id, revision_source,
            question_json, change_log, created_at
        )
        SELECT document_id, question_id, version_number, document_id,
               revision_source, question_json, change_log, created_at
        FROM question_versions
        """
    )

    op.add_column("question_reviews", sa.Column("task_id", sa.String(), nullable=True))
    op.add_column("question_reviews", sa.Column("version", sa.Integer(), nullable=True))
    op.add_column("question_reviews", sa.Column("idempotency_key", sa.String(), nullable=True))
    op.add_column(
        "question_reviews",
        sa.Column("question_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        """
        UPDATE question_reviews AS review
        SET task_id = version.document_id,
            version = version.version_number,
            idempotency_key = 'legacy:' || review.review_id::text,
            question_json = version.question_json
        FROM question_versions AS version
        WHERE review.question_version_id = version.version_id
        """
    )
    op.execute(
        """
        UPDATE question_reviews AS review
        SET task_id = review.document_id,
            version = snapshot.version,
            idempotency_key = COALESCE(review.idempotency_key, 'legacy:' || review.review_id::text),
            question_json = snapshot.question_json
        FROM question_snapshots AS snapshot
        WHERE review.task_id IS NULL
          AND snapshot.task_id = review.document_id
          AND snapshot.question_id = review.question_id
          AND snapshot.version = 1
        """
    )
    op.alter_column("question_reviews", "task_id", nullable=False)
    op.alter_column("question_reviews", "version", nullable=False)
    op.alter_column("question_reviews", "idempotency_key", nullable=False)
    op.alter_column("question_reviews", "question_json", nullable=False)
    op.create_unique_constraint(
        "uq_question_review_idempotency", "question_reviews", ["idempotency_key"]
    )
    op.create_foreign_key(
        "fk_question_reviews_snapshot",
        "question_reviews",
        "question_snapshots",
        ["task_id", "question_id", "version"],
        ["task_id", "question_id", "version"],
        ondelete="RESTRICT",
    )

    op.add_column("question_bank", sa.Column("task_id", sa.String(), nullable=True))
    op.add_column("question_bank", sa.Column("version", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE question_bank AS bank
        SET task_id = version.document_id,
            version = version.version_number
        FROM question_versions AS version
        WHERE bank.source_version_id = version.version_id
        """
    )
    op.execute(
        """
        UPDATE question_bank AS bank
        SET task_id = bank.document_id,
            version = snapshot.version
        FROM question_snapshots AS snapshot
        WHERE bank.task_id IS NULL
          AND snapshot.task_id = bank.document_id
          AND snapshot.question_id = bank.question_id
          AND snapshot.version = 1
        """
    )
    op.alter_column("question_bank", "task_id", nullable=False)
    op.alter_column("question_bank", "version", nullable=False)
    op.create_foreign_key(
        "fk_question_bank_snapshot",
        "question_bank",
        "question_snapshots",
        ["task_id", "question_id", "version"],
        ["task_id", "question_id", "version"],
        ondelete="RESTRICT",
    )

    op.drop_constraint("uq_question_bank_source", "question_bank", type_="unique")
    op.create_unique_constraint(
        "uq_question_bank_source_version",
        "question_bank",
        ["task_id", "question_id", "version"],
    )
    op.drop_constraint("fk_question_bank_version", "question_bank", type_="foreignkey")
    op.drop_constraint("fk_question_reviews_version", "question_reviews", type_="foreignkey")
    op.drop_constraint("question_bank_document_id_fkey", "question_bank", type_="foreignkey")
    op.drop_constraint("question_reviews_document_id_fkey", "question_reviews", type_="foreignkey")
    op.drop_column("question_bank", "source_version_id")
    op.drop_column("question_bank", "document_id")
    op.drop_column("question_reviews", "question_version_id")
    op.drop_column("question_reviews", "document_id")
    op.drop_table("question_versions")


def downgrade() -> None:
    raise NotImplementedError(
        "The task/version identity migration is intentionally irreversible because UUID version identities are discarded"
    )
