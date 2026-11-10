import copy
import json
from pathlib import Path
import unittest
from exam_assembly_agent.checker_adapter import convert_export
from exam_assembly_agent.main import assemble_exam


class AdapterTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / "examples"
        self.data = json.loads((root / "checker_export_mock.json").read_text(encoding="utf-8"))
        self.mapping = json.loads((root / "topic_mapping.json").read_text(encoding="utf-8"))

    def convert(self):
        return convert_export(self.data, self.mapping, mock_input=True)

    def test_options_answer_topics_and_missing_explanation(self):
        bank, report = self.convert()
        self.assertEqual(report["accepted_count"], 1)
        q = bank[0]
        self.assertEqual(q["options"]["B"], "后进先出")
        self.assertEqual(q["answer"], "B")
        self.assertEqual(q["topic"], "栈")
        self.assertEqual(len(q["knowledge_points"]), 2)
        self.assertEqual(q["explanation_status"], "NOT_PROVIDED")
        req = dict(request_id="adapter_test", subject="数据结构", question_type="single_choice",
                   question_count=1, score_per_question=2, total_score=2,
                   topic_counts={"栈": 1}, difficulty_counts={"easy": 1}, allow_mock_reviews=True)
        self.assertEqual(assemble_exam(req, bank)["status"], "STRUCTURAL_PASS")

    def test_no_guessing_ambiguous_answer(self):
        self.data["questions"][0]["question_json"]["question"]["answer_text"] = "答案是 B，因为栈后进先出"
        bank, report = self.convert()
        self.assertEqual(bank, [])
        self.assertEqual(len(report["rejected"]), 1)

    def test_conflicting_topics_rejected(self):
        self.data["questions"][0]["question_json"]["metadata"]["knowledge_points"] = ["栈", "树"]
        self.assertEqual(self.convert()[0], [])

    def test_real_records_not_silently_trusted(self):
        bank, report = convert_export(self.data, self.mapping)
        self.assertEqual(bank, [])
        self.assertEqual(len(report["rejected"]), 1)

    def test_missing_score_and_duplicate_options(self):
        q = self.data["questions"][0]["question_json"]["question"]
        original = copy.deepcopy(q)
        q["points"] = None
        self.assertEqual(self.convert()[0], [])
        q.update(original)
        q["options"] = ["同一内容"] * 4
        self.assertEqual(self.convert()[0], [])

    def test_empty_bank(self):
        self.assertEqual(convert_export({"questions": []}, self.mapping)[0], [])


if __name__ == "__main__":
    unittest.main()
