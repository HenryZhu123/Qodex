import copy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from exam_assembly_service.app import create_app
from exam_assembly_service.history import HistoryError, snapshots
from exam_assembly_service.repository import BankError
from test_service import fixtures, FakeRepository


class MemoryHistory:
    def __init__(self):
        self.rows = {}
    async def save(self, request, result):
        exam_id = uuid4()
        items = [{"position": n, "source_json": s, "student_json": q, "answer_json": a}
                 for n, s, q, a in snapshots(result)]
        self.rows[exam_id] = copy.deepcopy(dict(exam_id=exam_id, created_at=datetime.now(timezone.utc),
            status=result["status"], request_json=request, report_json=result, items=items,
            student_html=Path(result["artifacts"]["student_exam_html"]).read_text(encoding="utf-8") if items else None,
            answer_html=Path(result["artifacts"]["answer_key_html"]).read_text(encoding="utf-8") if items else None))
        return {"status": "STORED", "exam_id": str(exam_id)}
    async def get(self, exam_id):
        return self.rows.get(exam_id)
    async def list(self, limit, offset):
        return [{"exam_id": r["exam_id"], "status": r["status"]} for r in list(self.rows.values())[offset:offset+limit]]


def setup():
    req, entry, state = fixtures()
    public = dict(request_id="history-test", subject=req["subject"], question_count=1, total_score=2,
        question_type_counts={"single_choice": 1}, question_type_scores={"single_choice": 2},
        knowledge_point_counts={"栈": 1}, difficulty_counts=req["difficulty_counts"])
    return public, FakeRepository(entry, state)


def test_history_snapshot_separate_answers_and_download_after_local_files_removed():
    req, repo = setup()
    history = MemoryHistory()
    with TemporaryDirectory() as folder, TestClient(create_app(repo, folder, history=history)) as client:
        response = client.post("/v1/exam-assembly/assemble", json=req)
        assert response.status_code == 200
        result = response.json()
        exam_id = result["history"]["exam_id"]
        assert result["history"]["status"] == "STORED"
        for path in Path(folder).rglob("*"):
            if path.is_file():
                path.unlink()
        repo.current["question"]["answer_text"] = "D"
        detail = client.get(f"/v1/exam-assembly/history/{exam_id}").json()
        assert detail["student_exam"][0]["stem"] == "先进后出的结构是？"
        assert "answer_key" not in detail
        assert "answer" not in detail["student_exam"][0]
        assert client.get(f"/v1/exam-assembly/history/{exam_id}/answers").json()["answer_key"][0]["answer"] == "A"
        assert client.get(f"/v1/exam-assembly/history/{exam_id}/student.html").status_code == 200
        assert "第 1 题：A" in client.get(f"/v1/exam-assembly/history/{exam_id}/answer.html").text
        assert len(client.get("/v1/exam-assembly/history").json()["exams"]) == 1
        assert client.get("/v1/exam-assembly/history?limit=101").status_code == 422
        assert client.get(f"/v1/exam-assembly/history/{uuid4()}").status_code == 404


@pytest.mark.parametrize("kind", ["shortage", "invalid", "unresolved"])
def test_non_success_attempt_saved_without_exam(kind):
    req, repo = setup()
    if kind in {"shortage", "unresolved"}:
        repo.entries = []
        repo.complete = kind != "unresolved"
    else:
        req["total_score"] = 3
    history = MemoryHistory()
    with TemporaryDirectory() as folder, TestClient(create_app(repo, folder, history=history)) as client:
        result = client.post("/v1/exam-assembly/assemble", json=req).json()
        exam_id = result["history"]["exam_id"]
        assert result["status"] in {"NEEDS_QUESTIONS", "INVALID_REQUEST", "UNRESOLVED"}
        assert history.rows[UUID(exam_id)]["items"] == []
        assert client.get(f"/v1/exam-assembly/history/{exam_id}/student.html").status_code == 409


def test_history_save_failure_is_not_silent_success():
    req, repo = setup()
    class Broken(MemoryHistory):
        async def save(self, request, result):
            raise HistoryError("failure")
    with TemporaryDirectory() as folder, TestClient(create_app(repo, folder, history=Broken())) as client:
        response = client.post("/v1/exam-assembly/assemble", json=req)
        assert response.status_code == 503
        assert response.json()["detail"]["error_code"] == "HISTORY_SAVE_FAILED"


def test_no_database_explicitly_disables_history():
    req, repo = setup()
    with TemporaryDirectory() as folder, TestClient(create_app(repo, folder, database_url="")) as client:
        assert client.get("/health").json()["history_enabled"] is False
        assert client.get("/v1/exam-assembly/history").status_code == 503
        assert client.post("/v1/exam-assembly/assemble", json=req).json()["history"]["status"] == "DISABLED"


def test_bank_failure_recorded_as_failed_attempt():
    req, repo = setup()
    async def unavailable(request):
        raise BankError("QUESTION_BANK_UNAVAILABLE", status=503, detail="offline")
    repo.search_candidates = unavailable
    history = MemoryHistory()
    with TemporaryDirectory() as folder, TestClient(create_app(repo, folder, history=history)) as client:
        response = client.post("/v1/exam-assembly/assemble", json=req)
        assert response.status_code == 502
        exam_id = response.json()["history"]["exam_id"]
        row = client.get(f"/v1/exam-assembly/history/{exam_id}").json()
        assert row["status"] == "TOOL_ERROR"
        assert row["error_code"] == "QUESTION_BANK_UNAVAILABLE"
        assert row["student_exam"] == []


def test_snapshot_identity_mismatch_rejected():
    with pytest.raises(ValueError, match="identities differ"):
        snapshots({"status": "STRUCTURAL_PASS", "student_exam": [{"question_id": "one"}],
                   "answer_key": [{"question_id": "two"}], "selected_sources": [{"record_id": "one"}]})
