"""Add the optional physical link to an AI generation task.

The foreign key is installed by question_generation/sql/002_generation_tasks.sql
after the owning question_generation.generation_tasks table exists.

Revision ID: 20261115_02
Revises: 20261115_01
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261115_02"
down_revision: str | None = "20261115_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "question_snapshots",
        sa.Column("generation_task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("question_snapshots", "generation_task_id")
