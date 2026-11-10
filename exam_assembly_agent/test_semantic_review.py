import copy
import unittest
from .semantic_review import build_review_packet, evaluate_decisions


class SemanticReviewTests(unittest.TestCase):
    def setUp(self):
        self.questions = [dict(question_id="a", version=1, topic="栈", stem="栈如何弹出元素？"),
                          dict(question_id="b", version=1, topic="栈", stem="哪项描述了栈的出栈次序？")]
        self.packet = build_review_packet(self.questions)
        p = self.packet["pairs"][0]
        self.decision = dict(pair_id=p["pair_id"], content_hashes=p["content_hashes"],
                             source="human", reviewer="unit-test-fixture", verdict="DUPLICATE",
                             reason="测试占位结论，仅验证程序分支，不代表人工语义评测")

    def test_similarity_does_not_approve(self):
        self.assertEqual(evaluate_decisions(self.packet, [])["status"], "NEEDS_REVIEW")

    def test_decisions_and_explicit_unresolved(self):
        self.assertEqual(evaluate_decisions(self.packet, [self.decision])["status"], "DUPLICATES_FOUND")
        self.decision["verdict"] = "DISTINCT"
        self.assertEqual(evaluate_decisions(self.packet, [self.decision])["status"], "SEMANTIC_REVIEW_PASS")
        self.decision["verdict"] = "UNRESOLVED"
        self.assertEqual(evaluate_decisions(self.packet, [self.decision])["status"], "NEEDS_REVIEW")

    def test_changed_content_invalidates_decision(self):
        questions = copy.deepcopy(self.questions)
        questions[0]["stem"] += "修改"
        packet = build_review_packet(questions)
        self.assertEqual(evaluate_decisions(packet, [self.decision])["status"], "NEEDS_REVIEW")

    def test_all_pairs_kept_and_duplicate_decisions_rejected(self):
        questions = self.questions + [dict(question_id="c", stem="图有多少条边？", topic="图")]
        self.assertEqual(build_review_packet(questions)["pair_count"], 3)
        self.assertEqual(evaluate_decisions(self.packet, [self.decision, self.decision])["status"], "NEEDS_REVIEW")


if __name__ == "__main__":
    unittest.main()
