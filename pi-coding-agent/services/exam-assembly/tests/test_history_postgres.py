"""Optional real PostgreSQL test; only the explicitly named isolated database is accepted."""
import asyncio
import copy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlparse

import asyncpg
from fastapi.testclient import TestClient
import pytest

from exam_assembly_service.app import create_app
from exam_assembly_service.history import HistoryError, PostgresHistory, snapshots
from test_history import setup

DSN = os.getenv("EXAM_ASSEMBLY_HISTORY_TEST_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="Explicit isolated PostgreSQL database required")


def test_real_history_transaction_routes_and_snapshot():
    assert urlparse(DSN).path == "/assembly_history_test", "Refusing a non-test database"
    req, repo = setup()
    with TemporaryDirectory() as folder, TestClient(create_app(repo, folder, database_url=DSN)) as client:
        result = client.post("/v1/exam-assembly/assemble", json=req).json()
        exam_id = result["history"]["exam_id"]
        assert result["history"]["status"] == "STORED"
        before = client.get(f"/v1/exam-assembly/history/{exam_id}").json()
        repo.current["question"]["answer_text"] = "D"
        repo.entries[0]["question_json"]["question"]["question_text"] = "changed"
        assert client.get(f"/v1/exam-assembly/history/{exam_id}").json() == before
        assert client.get(f"/v1/exam-assembly/history/{exam_id}/answers").json()["answer_key"][0]["answer"] == "A"
        full_report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))

        async def rollback():
            store = PostgresHistory(DSN)
            await store.open()
            try:
                async with store.pool.acquire() as conn:
                    count = await conn.fetchval("SELECT count(*) FROM assembled_exams")
                invalid_items = [(0, *item[1:]) for item in snapshots(full_report)]
                with patch("exam_assembly_service.history.snapshots", return_value=invalid_items):
                    with pytest.raises(HistoryError):
                        await store.save(req, copy.deepcopy(full_report))
                async with store.pool.acquire() as conn:
                    assert await conn.fetchval("SELECT count(*) FROM assembled_exams") == count
                    assert await conn.fetchval("SELECT count(*) FROM question_bank") == 0
            finally:
                await store.close()
        asyncio.run(rollback())
        for file in Path(folder).rglob("*"):
            if file.is_file():
                file.unlink()
        assert client.get(f"/v1/exam-assembly/history/{exam_id}/student.html").status_code == 200
        assert client.get(f"/v1/exam-assembly/history/{exam_id}/answer.html").status_code == 200
        assert client.get("/v1/exam-assembly/history").json()["exams"]
