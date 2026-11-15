"""Require AI snapshot task IDs to match their generation task.

Revision ID: 20261115_03
Revises: 20261115_02
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261115_03"
down_revision: str | None = "20261115_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_question_snapshot_generation_task_identity",
        "question_snapshots",
        "generation_task_id IS NULL OR task_id = generation_task_id::text",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_question_snapshot_generation_task_identity",
        "question_snapshots",
        type_="check",
    )
