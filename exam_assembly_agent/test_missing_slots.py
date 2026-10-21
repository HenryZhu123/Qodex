import copy
import unittest
from exam_assembly_agent.main import assemble_exam
from exam_assembly_agent.test_repair import make_scenarios


class MissingSlotsTests(unittest.TestCase):
    def test_explicit_slot_and_successful_resume(self):
        req, bank = make_scenarios()
        failed = assemble_exam(req, bank[:2])
        plan = failed["replenishment_request"]
        self.assertEqual(plan["suggested_additional_count"], 1)
        slot = plan["slots"][0]
        self.assertEqual((slot["topic"], slot["difficulty"], slot["score_per_question"], slot["count"]),
                         ("栈", "easy", 2, 1))
        self.assertEqual(plan["replace_question_ids"], ["MOCK_STACK_2"])
        # 第三道开发题作为补题样例，依然标记模拟审校。
        resumed = assemble_exam(req, bank)
        self.assertEqual(resumed["status"], "STRUCTURAL_PASS")

    def test_unreviewed_new_question_not_accepted(self):
        req, bank = make_scenarios()
        bank[2]["review"]["status"] = "NOT_REVIEWED"
        result = assemble_exam(req, bank)
        self.assertEqual(result["status"], "NEEDS_QUESTIONS")
        self.assertNotIn("student_exam", result)

    def test_three_duplicates_need_two_slots(self):
        req, bank = make_scenarios()
        req.update(question_count=3, total_score=6, topic_counts={"栈": 3}, difficulty_counts={"easy": 3})
        q3 = copy.deepcopy(bank[0])
        q3["question_id"] = "duplicate_3"
        result = assemble_exam(req, bank[:2] + [q3])
        self.assertEqual(result["replenishment_request"]["slots"][0]["count"], 2)

    def test_success_and_zero_budget_do_not_request_generation(self):
        req, bank = make_scenarios()
        self.assertNotIn("replenishment_request", assemble_exam(req, bank))
        req["max_repair_rounds"] = 0
        self.assertNotIn("replenishment_request", assemble_exam(req, bank))


if __name__ == "__main__":
    unittest.main()
