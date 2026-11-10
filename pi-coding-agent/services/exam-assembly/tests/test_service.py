import copy
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
import httpx

from exam_assembly_service.app import create_app
from exam_assembly_service.repository import BankError, HttpQuestionBankRepository
from exam_assembly_service.service import assemble


def fixtures():
    request = dict(request_id="test", subject="数据结构", question_type="single_choice", question_count=1,
                   score_per_question=2, total_score=2, topic_counts={"栈": 1},
                   difficulty_counts={"easy": 1, "medium": 0, "hard": 0})
    question = dict(document_id="doc", question_id="q1", question_text="先进后出的结构是？", subject="数据结构",
                    question_type="single_choice", points=2, options=["栈", "队列", "图", "树"], answer_text="A")
    entry = dict(record_id="record", document_id="doc", question_id="q1", source_version_id="v1",
                 question_json=dict(document_id="doc", question_id="q1", review_status="PASS", question=question,
                                    metadata=dict(difficulty="easy", knowledge_points=["栈"])))
    state = dict(document_id="doc", question_id="q1", question_version_id="v1", question=copy.deepcopy(question),
                 review=dict(status="PASS", review_id="review1", errors=[], unresolved_checks=[]),
                 question_bank=dict(status="STORED", record_id="record"))
    return request, entry, state


class FakeRepository:
    def __init__(self, entry, state, complete=True):
        self.entries, self.current, self.complete = [entry], state, complete
        self.reads = 0

    async def search_candidates(self, request):
        return self.entries, self.complete

    async def state(self, entry):
        self.reads += 1
        return self.current


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_html_and_separate_answers(self):
        req, entry, state = fixtures()
        repo = FakeRepository(entry, state)
        with tempfile.TemporaryDirectory() as folder:
            result = await assemble(req, repo, Path(folder))
            self.assertEqual(result["status"], "STRUCTURAL_PASS")
            self.assertEqual(repo.reads, 2)
            self.assertNotIn("answer_key", result)
            self.assertEqual(result["selected_sources"][0]["record_id"], "record")
            self.assertTrue(Path(result["artifacts"]["student_exam_html"]).is_file())
            self.assertEqual(json.loads(Path(result["artifacts"]["answer_key"]).read_text(encoding="utf-8"))[0]["answer"], "A")

    async def test_shortage_and_full_page_are_distinct(self):
        req, entry, state = fixtures()
        for complete, status in ((True, "NEEDS_QUESTIONS"), (False, "UNRESOLVED")):
            repo = FakeRepository(entry, state, complete)
            repo.entries = []
            with tempfile.TemporaryDirectory() as folder:
                result = await assemble(req, repo, Path(folder))
                self.assertEqual(result["status"], status)
                self.assertFalse(list(Path(folder).rglob("*.html")))
                if status == "UNRESOLVED":
                    self.assertNotIn("replenishment_request", result)
                    self.assertFalse(list(Path(folder).rglob("replenishment_request.json")))

    async def test_rejects_missing_answer_stale_version_failed_review_and_changed_content(self):
        for mutation in ("answer", "version", "review", "content"):
            req, entry, state = fixtures()
            if mutation == "answer":
                entry["question_json"]["question"]["answer_text"] = ""
                state["question"]["answer_text"] = ""
            elif mutation == "version":
                state["question_version_id"] = "v2"
            elif mutation == "review":
                state["review"]["status"] = "NEEDS_REVISION"
            else:
                state["question"]["answer_text"] = "B"
            with tempfile.TemporaryDirectory() as folder:
                result = await assemble(req, FakeRepository(entry, state), Path(folder))
                self.assertEqual(result["status"], "NEEDS_QUESTIONS")
                self.assertEqual(len(result["rejected_records"]), 1)

    async def test_invalid_quota_does_not_query(self):
        req, entry, state = fixtures()
        req["total_score"] = 3
        repo = FakeRepository(entry, state)
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual((await assemble(req, repo, Path(folder)))["status"], "INVALID_REQUEST")
            self.assertEqual(repo.reads, 0)

    async def test_core_excluded_candidate_cannot_be_kept_in_supplement_plan(self):
        req, entry, state = fixtures()
        # The source API accepts arbitrary metadata, but the core requires text explanations.
        entry["question_json"]["explanation"] = 42
        with tempfile.TemporaryDirectory() as folder:
            result = await assemble(req, FakeRepository(entry, state), Path(folder))
            self.assertEqual(result["status"], "NEEDS_QUESTIONS")
            self.assertEqual(result["replenishment_request"]["keep_assignments"], [])
            self.assertEqual(result["replenishment_request"]["suggested_additional_count"], 1)

    async def test_http_adapter_dedup_filters_and_errors(self):
        req, entry, state = fixtures()
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"questions": [entry]})
        async with httpx.AsyncClient(base_url="http://bank", transport=httpx.MockTransport(handler)) as client:
            entries, complete = await HttpQuestionBankRepository(client).search_candidates(req)
        self.assertEqual(entries, [entry])
        self.assertTrue(complete)
        self.assertEqual(dict(requests[0].url.params), {"subject": "数据结构", "question_type": "single_choice",
                         "knowledge_point": "栈", "difficulty": "easy", "limit": "100"})
        async with httpx.AsyncClient(base_url="http://bank", transport=httpx.MockTransport(
                lambda request: httpx.Response(503, json={"detail": "offline"}))) as client:
            with self.assertRaises(BankError) as caught:
                await HttpQuestionBankRepository(client).search_candidates(req)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.detail, "offline")

    async def test_multiple_topic_assignment_without_reuse(self):
        req, entry, state = fixtures()
        req.update(question_count=2, total_score=4, topic_counts={"栈": 1, "队列": 1},
                   difficulty_counts={"easy": 2, "medium": 0, "hard": 0})
        first = copy.deepcopy(entry)
        first["question_json"]["metadata"]["knowledge_points"] = ["栈", "队列"]
        second = copy.deepcopy(entry)
        second["record_id"] = "record2"
        second["question_json"]["question"]["question_text"] = "另一道不同的题干"
        class Repo:
            async def search_candidates(self, request):
                return [first, second], True
            async def state(self, e):
                return {**state, "question": e["question_json"]["question"],
                        "question_bank": {"status": "STORED", "record_id": e["record_id"]}}
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual((await assemble(req, Repo(), Path(folder)))["status"], "STRUCTURAL_PASS")


class ApiTests(unittest.TestCase):
    def test_api_rejects_mock_and_preserves_bank_error(self):
        req, entry, state = fixtures()
        req = dict(request_id=req["request_id"], subject=req["subject"], question_count=1, total_score=2,
                   question_type_counts={"single_choice": 1}, question_type_scores={"single_choice": 2},
                   knowledge_point_counts={"栈": 1}, difficulty_counts=req["difficulty_counts"])
        class BrokenRepository(FakeRepository):
            async def search_candidates(self, request):
                raise BankError("QUESTION_BANK_UNAVAILABLE", status=503, detail="offline")
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(BrokenRepository(entry, state), folder)) as client:
            self.assertEqual(client.post("/v1/exam-assembly/assemble", json={**req, "allow_mock_reviews": True}).status_code, 422)
            response = client.post("/v1/exam-assembly/assemble", json=req)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()["upstream_http_status"], 503)


if __name__ == "__main__":
    unittest.main()
