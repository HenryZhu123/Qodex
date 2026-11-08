import copy
import unittest

from .similarity import decisions_template, inspect_pair, screen
from .similarity_assembly import assemble_with_similarity


def make_question(qid, stem, options=None):
    return dict(question_id=qid, version=1, topic="栈", subject="数据结构", question_type="single_choice",
                difficulty="easy", score=2, stem=stem, options=options or dict(A="栈", B="队列", C="树", D="图"),
                answer="A", explanation="测试占位解析", review=dict(status="PASS", question_version=1, is_mock=True))


def scenario():
    req = dict(request_id="SIMILARITY_TEST_ONLY", subject="数据结构", question_type="single_choice",
               question_count=2, score_per_question=2, total_score=4, topic_counts={"栈": 2},
               difficulty_counts={"easy": 2}, max_repair_rounds=3, allow_mock_reviews=True)
    a = make_question("a", "容量为3的顺序栈中依次压入元素，哪项描述了它的操作规则？")
    b = make_question("b", "容量为5的顺序栈中依次压入元素，哪项描述了它的操作规则？")
    c = make_question("c", "空栈出栈会怎样？", dict(A="下溢", B="上溢", C="扩容", D="遍历"))
    return req, [a, b, c]


def human_decision(pair, verdict):
    return dict(pair_id=pair["pair_id"], question_ids=pair["question_ids"], content_hashes=pair["content_hashes"],
                source="human", reviewer="TEST_ONLY_human_fixture", verdict=verdict,
                reason="合成测试结论，仅验证程序分支，不代表实际人工语义评测")


class DetectionTests(unittest.TestCase):
    def test_option_reordering_is_explained_and_pair_order_is_stable(self):
        a = make_question("a", "下列数据结构中哪一种使用后进先出的操作原则？")
        b = make_question("b", a["stem"], dict(A="队列", B="栈", C="图", D="树"))
        b["answer"] = "B"
        pair = inspect_pair(a, b)
        self.assertEqual(pair["classification"], "CONFIRMED_DUPLICATE")
        self.assertIn("OPTION_ORDER_CHANGED", pair["reasons"])
        self.assertEqual(pair, inspect_pair(b, a))

    def test_number_changes_are_suspicions_not_semantic_verdicts(self):
        _, bank = scenario()
        pair = inspect_pair(bank[0], bank[1])
        self.assertEqual(pair["classification"], "SUSPECTED_DUPLICATE")
        self.assertIn("SAME_TEXT_TEMPLATE_CHANGED_NUMBERS", pair["reasons"])

    def test_similar_paraphrase_is_flagged(self):
        a = make_question("a", "使用顺序栈存放元素时，哪一项描述了栈的操作规则？")
        b = make_question("b", "采用顺序栈存放元素时，下面哪项描述了栈的操作规则？")
        self.assertEqual(inspect_pair(a, b)["classification"], "SUSPECTED_DUPLICATE")

    def test_negation_is_never_automatically_equated(self):
        a = make_question("a", "下列关于顺序栈操作和存储特点的描述中，正确的是哪一项？")
        b = make_question("b", "下列关于顺序栈操作和存储特点的描述中，不正确的是哪一项？")
        self.assertEqual(inspect_pair(a, b)["classification"], "SUSPECTED_DUPLICATE")

    def test_same_topic_or_answer_alone_does_not_trigger(self):
        _, bank = scenario()
        pair = inspect_pair(bank[0], bank[2])
        self.assertEqual(pair["classification"], "NO_LEXICAL_FLAG")
        self.assertFalse(screen([bank[0], bank[2]])["semantic_quality_certified"])

    def test_every_selected_pair_is_compared(self):
        _, bank = scenario()
        self.assertEqual(screen(bank)["pair_count"], 3)

    def test_long_text_requires_review_instead_of_unbounded_comparison(self):
        pair = inspect_pair(make_question("a", "题" * 2001), make_question("b", "目" * 2001))
        self.assertEqual(pair["classification"], "SUSPECTED_DUPLICATE")
        self.assertIn("TEXT_EXCEEDS_LEXICAL_SCREEN_LIMIT", pair["reasons"])
        self.assertIsNone(pair["evidence"]["text_similarity"])


class WorkflowTests(unittest.TestCase):
    def test_suspicion_waits_without_deleting_or_exporting_questions(self):
        req, bank = scenario()
        original = copy.deepcopy(bank)
        result = assemble_with_similarity(req, bank)
        self.assertEqual(result["status"], "UNRESOLVED")
        self.assertEqual(result["similarity_review"]["status"], "NEEDS_REVIEW")
        self.assertNotIn("student_exam", result)
        self.assertNotIn("answer_key", result)
        self.assertEqual(bank, original)
        self.assertEqual(result["repair_history"], [])
        self.assertEqual(result["similarity_review_packet"]["audience"], "TEACHER_ONLY")
        self.assertEqual(result["similarity_decisions_template"][0]["reviewer"], "")

    def test_explicit_distinct_resumes(self):
        req, bank = scenario()
        pair = inspect_pair(*bank[:2])
        result = assemble_with_similarity(req, bank, decisions=[human_decision(pair, "DISTINCT")])
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        self.assertEqual(result["similarity_review"]["pending_pair_count"], 0)
        self.assertFalse(result["similarity_review"]["semantic_quality_certified"])

    def test_human_duplicate_replaces_within_quotas(self):
        req, bank = scenario()
        result = assemble_with_similarity(req, bank, decisions=[human_decision(inspect_pair(*bank[:2]), "DUPLICATE")])
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        self.assertEqual({q["question_id"] for q in result["student_exam"]}, {"a", "c"})
        self.assertTrue(result["validation"]["passed"])
        self.assertEqual(len(result["repair_history"]), 1)

    def test_no_alternative_reports_confirmed_conflict(self):
        req, bank = scenario()
        result = assemble_with_similarity(req, bank[:2], decisions=[human_decision(inspect_pair(*bank[:2]), "DUPLICATE")])
        self.assertEqual(result["status"], "NEEDS_QUESTIONS")
        self.assertEqual(result["confirmed_duplicate_pairs"], [["a", "b"]])
        self.assertNotIn("student_exam", result)

    def test_replacement_with_new_suspicion_needs_its_own_review(self):
        req, bank = scenario()
        bank[2] = make_question("c", "容量为7的顺序栈中依次压入元素，哪项描述了它的操作规则？")
        result = assemble_with_similarity(req, bank, decisions=[human_decision(inspect_pair(*bank[:2]), "DUPLICATE")])
        self.assertEqual(result["status"], "UNRESOLVED")
        self.assertEqual(len(result["repair_history"]), 1)
        self.assertEqual(result["similarity_decisions_template"][0]["question_ids"], ["a", "c"])
        self.assertNotIn("student_exam", result)

    def test_same_stem_option_shuffle_uses_existing_automatic_repair(self):
        req, bank = scenario()
        bank[1]["stem"] = bank[0]["stem"]
        bank[1]["options"] = dict(A="队列", B="栈", C="图", D="树")
        bank[1]["answer"] = "B"
        result = assemble_with_similarity(req, bank)
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        self.assertIn("OPTION_ORDER_CHANGED", result["initial_similarity_screen"]["flagged_pairs"][0]["reasons"])
        self.assertEqual({q["question_id"] for q in result["student_exam"]}, {"a", "c"})

    def test_repair_budget_is_shared_and_respected(self):
        req, bank = scenario()
        req["max_repair_rounds"] = 0
        result = assemble_with_similarity(req, bank, decisions=[human_decision(inspect_pair(*bank[:2]), "DUPLICATE")])
        self.assertEqual(result["status"], "UNRESOLVED")
        self.assertEqual(result["repair_history"], [])

    def test_changed_content_or_version_invalidates_decision(self):
        req, bank = scenario()
        decision = human_decision(inspect_pair(*bank[:2]), "DISTINCT")
        for field, value in (("stem", "完全修改的题干"), ("answer", "B"), ("version", 2)):
            changed = copy.deepcopy(bank)
            changed[0][field] = value
            if field == "version":
                changed[0]["review"]["question_version"] = value
            result = assemble_with_similarity(req, changed, decisions=[decision])
            self.assertEqual(result["status"], "UNRESOLVED")
            self.assertEqual(result["similarity_review"]["status"], "INVALID_OR_STALE_DECISIONS")

    def test_missing_reviewer_unknown_pair_and_conflicting_decisions_are_rejected(self):
        req, bank = scenario()
        decision = human_decision(inspect_pair(*bank[:2]), "DISTINCT")
        for decisions in ([{**decision, "reviewer": ""}], [{**decision, "question_ids": ["a", "unknown"]}],
                          [decision, {**decision, "verdict": "DUPLICATE"}], [{**decision, "source": "model"}]):
            result = assemble_with_similarity(req, bank, decisions=decisions)
            self.assertEqual(result["status"], "UNRESOLVED")
            self.assertNotIn("student_exam", result)

    def test_unresolved_human_decision_does_not_approve(self):
        req, bank = scenario()
        result = assemble_with_similarity(req, bank, decisions=[human_decision(inspect_pair(*bank[:2]), "UNRESOLVED")])
        self.assertEqual(result["status"], "UNRESOLVED")


if __name__ == "__main__":
    unittest.main()
