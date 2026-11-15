"""Add indexes for exact-version review and latest bank lookups.

Revision ID: 20261115_04
Revises: 20261115_03
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261115_04"
down_revision: str | None = "20261115_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_question_reviews_version_created",
        "question_reviews",
        ["task_id", "question_id", "version", "created_at"],
    )
    op.create_index(
        "ix_question_bank_source_created",
        "question_bank",
        ["task_id", "question_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_question_bank_source_created", table_name="question_bank")
    op.drop_index("ix_question_reviews_version_created", table_name="question_reviews")
