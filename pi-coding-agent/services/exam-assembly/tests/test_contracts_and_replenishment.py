import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from exam_assembly_agent.main import assemble_exam
from exam_assembly_service.app import create_app
from exam_assembly_service.contracts import AssemblyRequest
from exam_assembly_service.replenishment import propose_replenishment


EXAMPLE = Path(__file__).parents[1] / "examples/request.json"


def request():
    return dict(request_id="joint_test", subject="数据结构", question_type="single_choice",
                question_count=3, score_per_question=2, total_score=6, topic_counts={"栈": 2, "队列": 1},
                difficulty_counts={"easy": 1, "medium": 0, "hard": 2}, allow_mock_reviews=True)


def question(index, topic, level, *, stem=None, topics=None):
    return dict(question_id=f"TEST_ONLY_{index}", version="TEST_ONLY_v1", subject="数据结构",
                question_type="single_choice", score=2, topic=topic, eligible_topics=topics or [topic],
                difficulty=level, stem=stem or f"合成测试题{index}", options=dict(A="甲", B="乙", C="丙", D="丁"),
                answer="A", explanation="合成测试，不是真实审校", review=dict(status="PASS",
                question_version="TEST_ONLY_v1", is_mock=True))


class ContractTests(unittest.TestCase):
    def test_public_example_normalizes_without_changing_quotas(self):
        public = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        fields, errors = AssemblyRequest.model_validate(public).selection_request()
        self.assertEqual(errors, [])
        self.assertEqual(fields["topic_counts"], public["knowledge_point_counts"])
        self.assertEqual(fields["score_per_question"], 2)
        self.assertNotIn("allow_mock_reviews", fields)

    def test_inconsistent_unsupported_and_unknown_difficulty_are_invalid(self):
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        changes = [dict(total_score=100), dict(knowledge_point_counts={"栈": 1}),
                   dict(question_type_counts={"single_choice": 1, "calculation": 1},
                        question_type_scores={"single_choice": 2, "calculation": 2}),
                   dict(question_type_scores={"single_choice": 0}),
                   dict(difficulty_counts={"easy": 1, "medium": 0, "unknown": 1}),
                   dict(knowledge_point_counts={" ": 2})]
        for change in changes:
            with self.subTest(change=change):
                core, errors = AssemblyRequest.model_validate({**example, **change}).selection_request()
                self.assertIsNone(core)
                self.assertTrue(errors)

    def test_rejects_mock_flags_wrong_versions_and_non_integer_scores(self):
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        for change in (dict(bank="development"), dict(schema_version="2.0"),
                       dict(question_type_scores={"single_choice": 2.5}), dict(allow_mock_reviews=True)):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                AssemblyRequest.model_validate({**example, **change})

    def test_invalid_request_never_queries_repository(self):
        class MustNotRead:
            async def search_candidates(self, request):
                raise AssertionError("Invalid request accessed the bank")
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(MustNotRead(), folder)) as client:
            response = client.post("/v1/exam-assembly/assemble", json={**example, "total_score": 99})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "INVALID_REQUEST")


class ReplenishmentTests(unittest.TestCase):
    def verify_completion(self, req, pool, plan):
        by_id = {q["question_id"]: q for q in pool}
        completed = [{**by_id[a["record_id"]], "topic": a["knowledge_point"],
                      "eligible_topics": [a["knowledge_point"]]} for a in plan["keep_assignments"]]
        for slot in plan["deficits"]:
            for _ in range(slot["missing_count"]):
                completed.append(question(f"SUPPLIED_{len(completed)}", slot["knowledge_point"], slot["difficulty"]))
        self.assertEqual(sum(s["missing_count"] for s in plan["deficits"]), plan["suggested_additional_count"])
        # Independent whole-exam validation after hypothetical reviewed supplements.
        self.assertEqual(assemble_exam(req, completed)["status"], "STRUCTURAL_PASS")

    def test_joint_gap_when_all_marginal_counts_are_sufficient(self):
        req = request()
        pool = [question(i, "栈", "easy") for i in range(3)] + [question(i+3, "队列", "hard") for i in range(3)]
        report = assemble_exam(req, pool)
        self.assertFalse(any(report["topic_deficits"].values()))
        self.assertFalse(any(report["difficulty_deficits"].values()))
        self.assertEqual(report["status"], "NEEDS_QUESTIONS")
        plan = propose_replenishment(req, pool)
        self.assertTrue(plan["minimum_count_proven"])
        self.assertEqual(plan["suggested_additional_count"], 1)
        self.assertEqual((plan["deficits"][0]["knowledge_point"], plan["deficits"][0]["difficulty"]), ("栈", "hard"))
        self.verify_completion(req, pool, plan)

    def test_duplicate_stems_are_not_retained_twice(self):
        req = request()
        req.update(question_count=2, total_score=4, topic_counts={"栈": 2},
                   difficulty_counts={"easy": 1, "medium": 0, "hard": 1})
        pool = [question(1, "栈", "easy", stem="same"), question(2, "栈", "hard", stem="same")]
        plan = propose_replenishment(req, pool)
        self.assertEqual(plan["suggested_additional_count"], 1)
        self.verify_completion(req, pool, plan)

    def test_empty_pool_and_budget_limit_are_honest(self):
        req = request()
        empty = propose_replenishment(req, [])
        self.assertEqual(empty["suggested_additional_count"], 3)
        self.verify_completion(req, [], empty)
        limited = propose_replenishment(req, [question(1, "栈", "easy")], max_nodes=0)
        self.assertFalse(limited["minimum_count_proven"])
        self.assertTrue(limited["search"]["budget_exhausted"])
        self.verify_completion(req, [], limited)

    def test_overlapping_labels_keep_unique_records_and_do_not_mutate_input(self):
        req = request()
        pool = [question(1, "栈", "hard", topics=["栈", "队列"]), question(2, "栈", "easy")]
        before = copy.deepcopy(pool)
        plan = propose_replenishment(req, pool)
        self.assertEqual(len(plan["keep_assignments"]), 2)
        self.assertEqual(pool, before)
        self.verify_completion(req, pool, plan)

    def test_maximum_retention_matches_small_exhaustive_oracle(self):
        req = request()
        variants = [("栈", "easy"), ("栈", "hard"), ("队列", "easy"), ("队列", "hard")]
        for cells in itertools.product(variants, repeat=3):
            pool = [question(i, *cell) for i, cell in enumerate(cells)]
            best = 0
            for size in range(4):
                for subset in itertools.combinations(pool, size):
                    if all(sum(q["topic"] == k for q in subset) <= n for k, n in req["topic_counts"].items()) and all(
                            sum(q["difficulty"] == k for q in subset) <= n for k, n in req["difficulty_counts"].items()):
                        best = max(best, size)
            plan = propose_replenishment(req, pool)
            self.assertTrue(plan["minimum_count_proven"])
            self.assertEqual(len(plan["keep_assignments"]), best)
            self.verify_completion(req, pool, plan)


if __name__ == "__main__":
    unittest.main()
