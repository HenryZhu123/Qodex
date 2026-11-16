"""Align legacy JSON identity with the task-scoped columns introduced on 20261115.

Only identity keys are transformed; content, review verdicts and source evidence
are retained. No empty/new database is seeded and no review is manufactured.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20261116_01"
down_revision: str | None = "20261115_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fail rather than silently redirect a conflicting historical source identity.
    for table in ("question_snapshots", "question_reviews", "question_bank"):
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM {table}
                    WHERE question_json ? 'document_id'
                      AND (question_json->>'document_id' IS DISTINCT FROM task_id
                           OR (question_json ? 'task_id' AND question_json->>'task_id' IS DISTINCT FROM task_id))
                ) THEN
                    RAISE EXCEPTION 'Conflicting legacy identity in {table}';
                END IF;
            END $$
        """)
    for table in ("question_snapshots", "question_reviews"):
        op.execute(f"""
            UPDATE {table}
            SET question_json = (question_json - 'document_id') || jsonb_build_object('task_id', task_id)
            WHERE question_json ? 'document_id'
        """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM question_reviews
                WHERE review_json ? 'document_id'
                  AND review_json->>'document_id' IS DISTINCT FROM task_id
            ) OR EXISTS (
                SELECT 1 FROM question_bank
                WHERE question_json ? 'document_id'
                  AND (question_json->'question'->>'document_id' IS DISTINCT FROM task_id
                       OR (question_json->'question' ? 'task_id'
                           AND question_json->'question'->>'task_id' IS DISTINCT FROM task_id))
            ) THEN
                RAISE EXCEPTION 'Conflicting nested legacy identity';
            END IF;
        END $$
    """)
    op.execute("""
        UPDATE question_reviews
        SET review_json = (review_json - 'document_id' - 'question_version_id') ||
            jsonb_build_object('task_id', task_id, 'version', version, 'idempotency_key', idempotency_key)
        WHERE review_json ? 'document_id' OR review_json ? 'question_version_id'
    """)
    op.execute("""
        UPDATE question_bank
        SET question_json = jsonb_set(
            (question_json - 'document_id') || jsonb_build_object('task_id', task_id, 'version', version),
            '{question}',
            ((question_json->'question') - 'document_id') || jsonb_build_object('task_id', task_id)
        )
        WHERE question_json ? 'document_id'
          AND question_json->'question'->>'document_id' = task_id
    """)


def downgrade() -> None:
    raise NotImplementedError("Restore the pre-upgrade backup to recover legacy JSON identities")
