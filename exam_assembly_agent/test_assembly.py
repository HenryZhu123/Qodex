import copy
import json
from pathlib import Path
import unittest

from exam_assembly_agent.main import assemble_exam, inspect_candidates
from exam_assembly_agent.question_bank import load_questions
from exam_assembly_agent.assembly import select_questions, validate_selection


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / "examples"
        self.request = json.loads((root / "request.json").read_text(encoding="utf-8"))
        self.bank = load_questions(root / "question_bank.json")

    def test_success_and_student_answer_separation(self):
        result = assemble_exam(self.request, self.bank)
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        self.assertEqual(len(result["student_exam"]), 10)
        self.assertEqual(result["validation"]["actual_total_score"], 20)
        self.assertTrue(all("answer" not in q and "explanation" not in q for q in result["student_exam"]))

    def test_shortage_and_invalid_request(self):
        self.assertEqual(assemble_exam(self.request, self.bank[:1])["status"], "NEEDS_QUESTIONS")
        self.request["total_score"] = 30
        self.assertEqual(assemble_exam(self.request, self.bank)["status"], "INVALID_REQUEST")

    def test_joint_conflict_despite_sufficient_marginals(self):
        self.request.update(question_count=2, total_score=4,
                            topic_counts={"A": 1, "B": 1}, difficulty_counts={"hard": 2, "easy": 0})
        bank = []
        for i, (topic, level) in enumerate((("A", "hard"), ("A", "hard"), ("B", "easy"))):
            q = copy.deepcopy(self.bank[0])
            q.update(question_id=str(i), topic=topic, difficulty=level)
            bank.append(q)
        self.assertEqual(inspect_candidates(self.request, bank)["status"], "READY_FOR_SELECTION")
        self.assertEqual(assemble_exam(self.request, bank)["status"], "NEEDS_QUESTIONS")

    def test_budget_and_independent_validation(self):
        selected, trace = select_questions(self.request, self.bank, max_nodes=1)
        self.assertIsNone(selected)
        self.assertTrue(trace["budget_exhausted"])
        selected, _ = select_questions(self.request, self.bank)
        selected[0] = selected[1]
        self.assertFalse(validate_selection(self.request, selected)["passed"])

    def test_real_mode_rejects_mock_reviews(self):
        self.request["allow_mock_reviews"] = False
        self.assertEqual(assemble_exam(self.request, self.bank)["eligible_candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
