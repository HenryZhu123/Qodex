import copy
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from exam_assembly_agent.test_similarity import scenario
from exam_assembly_service.app import create_app


class SyntheticBank:
    """Unit-test API fixture only, not real review evidence or a production fallback."""
    def __init__(self, questions):
        self.questions = copy.deepcopy(questions)

    async def search_candidates(self, request):
        return [dict(record_id=q["question_id"], document_id="TEST_ONLY_doc", question_id=q["question_id"],
                     source_version_id=str(q["version"]), question_json=dict(document_id="TEST_ONLY_doc",
                     question_id=q["question_id"], review_status="PASS", question=dict(
                         subject=q["subject"], question_type=q["question_type"], question_text=q["stem"],
                         options=list(q["options"].values()), answer_text=q["answer"], points=q["score"]),
                     metadata=dict(difficulty=q["difficulty"], knowledge_points=[q["topic"]]))) for q in self.questions], True

    async def state(self, entry):
        return dict(document_id=entry["document_id"], question_id=entry["question_id"],
                    question_version_id=entry["source_version_id"], question=entry["question_json"]["question"],
                    review=dict(status="PASS", review_id="TEST_ONLY_review", errors=[], unresolved_checks=[]),
                    question_bank=dict(status="STORED", record_id=entry["record_id"]))


def public_request():
    return dict(request_id="TEST_ONLY_similarity", subject="数据结构", question_count=2, total_score=4,
                question_type_counts={"single_choice": 2}, question_type_scores={"single_choice": 2},
                knowledge_point_counts={"栈": 2}, difficulty_counts={"easy": 2, "medium": 0, "hard": 0})


class SimilarityApiTests(unittest.TestCase):
    def test_wait_review_resume_and_stale_version(self):
        _, questions = scenario()
        bank = SyntheticBank(questions)
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(bank, folder)) as client:
            first = client.post("/v1/exam-assembly/assemble", json=public_request()).json()
            self.assertEqual(first["status"], "UNRESOLVED")
            self.assertEqual(first["similarity_review"]["status"], "NEEDS_REVIEW")
            self.assertFalse(first["validation"]["passed"])
            self.assertNotIn("similarity_review_packet", first)
            self.assertNotIn("answer_key_html", first["artifacts"])
            self.assertNotIn("student_exam_html", first["artifacts"])
            packet = json.loads(Path(first["artifacts"]["similarity_review_packet"]).read_text(encoding="utf-8"))
            self.assertTrue(packet["contains_answers"])
            decisions = json.loads(Path(first["artifacts"]["similarity_decisions_template"]).read_text(encoding="utf-8"))
            # Templates are not approvals and cannot be submitted with empty reviewer/reason.
            self.assertEqual(client.post("/v1/exam-assembly/assemble", json={**public_request(), "similarity_decisions": decisions}).status_code, 422)
            for decision in decisions:
                decision.update(reviewer="TEST_ONLY_human", reason="单元测试人工结论占位", verdict="DISTINCT")
            resumed = client.post("/v1/exam-assembly/assemble", json={**public_request(), "similarity_decisions": decisions}).json()
            self.assertEqual(resumed["status"], "STRUCTURAL_PASS")
            self.assertTrue(Path(resumed["artifacts"]["student_exam_html"]).is_file())
            bank.questions[0]["version"] = 2
            stale = client.post("/v1/exam-assembly/assemble", json={**public_request(), "similarity_decisions": decisions}).json()
            self.assertEqual(stale["status"], "UNRESOLVED")
            self.assertEqual(stale["similarity_review"]["status"], "INVALID_OR_STALE_DECISIONS")
            self.assertNotIn("student_exam_html", stale["artifacts"])

    def test_confirmed_duplicate_supplement_plan_does_not_keep_both(self):
        _, questions = scenario()
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(SyntheticBank(questions[:2]), folder)) as client:
            first = client.post("/v1/exam-assembly/assemble", json=public_request()).json()
            decisions = json.loads(Path(first["artifacts"]["similarity_decisions_template"]).read_text(encoding="utf-8"))
            for decision in decisions:
                decision.update(reviewer="TEST_ONLY_human", reason="测试占位：同模板题", verdict="DUPLICATE")
            result = client.post("/v1/exam-assembly/assemble", json={**public_request(), "similarity_decisions": decisions}).json()
            self.assertEqual(result["status"], "NEEDS_QUESTIONS")
            plan = result["replenishment_request"]
            self.assertEqual(plan["suggested_additional_count"], 1)
            self.assertEqual(len(plan["keep_assignments"]), 1)
            self.assertEqual(plan["requirements"]["avoid_confirmed_record_pairs"], [["a", "b"]])
            self.assertNotIn("student_exam_html", result["artifacts"])

    def test_confirmed_duplicate_replacement_exports_new_paper(self):
        _, questions = scenario()
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(SyntheticBank(questions), folder)) as client:
            first = client.post("/v1/exam-assembly/assemble", json=public_request()).json()
            decisions = json.loads(Path(first["artifacts"]["similarity_decisions_template"]).read_text(encoding="utf-8"))
            for decision in decisions:
                decision.update(reviewer="TEST_ONLY_human", reason="测试占位：重复题", verdict="DUPLICATE")
            result = client.post("/v1/exam-assembly/assemble", json={**public_request(), "similarity_decisions": decisions}).json()
            self.assertEqual(result["status"], "STRUCTURAL_PASS")
            self.assertEqual({q["record_id"] for q in result["selected_sources"]}, {"a", "c"})
            self.assertEqual(result["repair_history"][0]["action"], "RESELECT_WITH_CONFIRMED_PAIR_CONSTRAINTS")


if __name__ == "__main__":
    unittest.main()
