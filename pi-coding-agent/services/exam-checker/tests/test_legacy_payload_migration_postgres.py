"""Opt-in real PostgreSQL regression for JSON-only migration.

Uses transaction-local temporary tables in the explicitly named rehearsal DB;
never edits its source tables or writes any review to the user's live bank.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DSN = os.getenv("EXAM_CHECKER_MIGRATION_TEST_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="Explicit isolated PostgreSQL migration rehearsal required")


@pytest.mark.parametrize("conflict", [None, "outer", "nested", "review"])
def test_migration_preserves_content_and_verdicts_or_rejects_identity_conflict(conflict):
    assert urlparse(DSN).path == "/qodex_assembly_compat_20261116", "Refusing any live database"
    path = Path(__file__).parents[1] / "migrations/versions/20261116_01_legacy_snapshot_payloads.py"
    spec = importlib.util.spec_from_file_location("legacy_payload_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    async def run():
        engine = create_async_engine(DSN.replace("postgresql://", "postgresql+asyncpg://", 1))
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    for table in ("question_snapshots", "question_reviews", "question_bank"):
                        await conn.execute(text(f"CREATE TEMP TABLE {table} (task_id text, version integer, idempotency_key text, question_json jsonb, review_json jsonb) ON COMMIT DROP"))
                    question = dict(document_id="TEST_ONLY_task", question_id="TEST_ONLY_q", question_text="原题", answer_text="A", points=2)
                    review = dict(document_id="TEST_ONLY_task", question_version_id="TEST_ONLY_old_uuid",
                                  review=dict(status="NEEDS_REVISION", summary=dict(errors=["TEST_ONLY_preserved_error"])))
                    payload = dict(document_id="TEST_ONLY_task", question_id="TEST_ONLY_q", question=question.copy(),
                                   metadata=dict(difficulty="easy"), review_status="PASS")
                    if conflict == "outer":
                        question["document_id"] = "WRONG_SOURCE"
                    elif conflict == "nested":
                        payload["question"]["document_id"] = "WRONG_SOURCE"
                    elif conflict == "review":
                        review["document_id"] = "WRONG_SOURCE"
                    for table, value in (("question_snapshots", question), ("question_reviews", question), ("question_bank", payload)):
                        await conn.execute(text(f"INSERT INTO {table} VALUES ('TEST_ONLY_task',2,'legacy:TEST_ONLY_review',CAST(:q AS jsonb),CAST(:r AS jsonb))"),
                                           dict(q=json.dumps(value), r=json.dumps(review)))
                    def upgrade(connection):
                        with Operations.context(MigrationContext.configure(connection)):
                            migration.upgrade()
                    if conflict:
                        with pytest.raises(Exception, match="Conflicting.*identity"):
                            await conn.run_sync(upgrade)
                    else:
                        await conn.run_sync(upgrade)
                        after = (await conn.execute(text("SELECT question_json FROM question_bank"))).scalar_one()
                        assert after["question"] == {k: v for k, v in question.items() if k != "document_id"} | {"task_id": "TEST_ONLY_task"}
                        assert after["metadata"] == payload["metadata"] and after["review_status"] == "PASS"
                        checked = (await conn.execute(text("SELECT review_json FROM question_reviews"))).scalar_one()
                        assert checked["review"] == review["review"]
                        assert checked["version"] == 2 and checked["idempotency_key"] == "legacy:TEST_ONLY_review"
                        assert "question_version_id" not in checked
                        await conn.run_sync(upgrade)
                        assert (await conn.execute(text("SELECT question_json FROM question_bank"))).scalar_one() == after
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()
    asyncio.run(run())
