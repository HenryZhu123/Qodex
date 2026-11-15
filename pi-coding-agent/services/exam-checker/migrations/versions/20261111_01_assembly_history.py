"""Add immutable assembly attempts and ordered question snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261111_01"
down_revision = "20261017_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assembled_exams",
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_json", postgresql.JSONB(), nullable=False),
        sa.Column("report_json", postgresql.JSONB(), nullable=False),
        sa.Column("student_html", sa.Text()),
        sa.Column("answer_html", sa.Text()),
    )
    op.create_index("ix_assembled_exams_created", "assembled_exams", ["created_at", "exam_id"])
    op.create_table(
        "assembled_exam_items",
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assembled_exams.exam_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("source_json", postgresql.JSONB(), nullable=False),
        sa.Column("student_json", postgresql.JSONB(), nullable=False),
        sa.Column("answer_json", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("position > 0", name="ck_assembled_item_position"),
    )


def downgrade():
    op.drop_table("assembled_exam_items")
    op.drop_index("ix_assembled_exams_created", table_name="assembled_exams")
    op.drop_table("assembled_exams")
