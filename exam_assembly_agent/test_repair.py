import copy
import json
from pathlib import Path
import unittest
from exam_assembly_agent.main import assemble_exam
from exam_assembly_agent.assembly import find_duplicate_stems


def make_scenarios():
    root = Path(__file__).parent / "examples"
    base = json.loads((root / "question_bank.json").read_text(encoding="utf-8"))
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    request.update(request_id="REPAIR_DEMO", question_count=2, total_score=4,
                   topic_counts={"栈": 2}, difficulty_counts={"easy": 2}, max_repair_rounds=3)
    q1 = copy.deepcopy(base[4])
    q1.update(question_id="MOCK_STACK_1")
    q2 = copy.deepcopy(q1)
    q2["question_id"] = "MOCK_STACK_2"
    q3 = json.loads((root / "question.json").read_text(encoding="utf-8"))
    q3["question_id"] = "MOCK_STACK_3"
    return request, [q1, q2, q3]


class RepairTests(unittest.TestCase):
    def test_repair_and_full_revalidation(self):
        req, bank = make_scenarios()
        result = assemble_exam(req, bank)
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        self.assertTrue(all(result["validation"]["checks"].values()))
        self.assertEqual(result["repair_history"][0]["removed_question_ids"], ["MOCK_STACK_2"])
        self.assertEqual(result["repair_history"][0]["added_question_ids"], ["MOCK_STACK_3"])

    def test_no_replacement_no_final_exam(self):
        req, bank = make_scenarios()
        result = assemble_exam(req, bank[:2])
        self.assertEqual(result["status"], "NEEDS_QUESTIONS")
        self.assertNotIn("student_exam", result)
        self.assertEqual(result["repair_history"][0]["outcome"], "NO_FEASIBLE_REPLACEMENT")

    def test_zero_budget(self):
        req, bank = make_scenarios()
        req["max_repair_rounds"] = 0
        result = assemble_exam(req, bank)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["repair_history"], [])
        self.assertNotIn("student_exam", result)

    def test_normalization_retains_numbers(self):
        self.assertEqual(len(find_duplicate_stems([
            {"question_id": "a", "stem": "Ａ  B"}, {"question_id": "b", "stem": "A B"}])), 1)
        self.assertEqual(find_duplicate_stems([
            {"question_id": "a", "stem": "n=1"}, {"question_id": "b", "stem": "n=2"}]), [])

    def test_invalid_budget(self):
        req, bank = make_scenarios()
        req["max_repair_rounds"] = -1
        self.assertEqual(assemble_exam(req, bank)["status"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
