import json
from pathlib import Path
import tempfile
import unittest
from .question_bank import load_questions
from .request_session import RequestSession
from .demo_changes import run_demo


class SessionTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / "examples"
        self.request = json.loads((root / "request.json").read_text(encoding="utf-8"))
        self.session = RequestSession(load_questions(root / "question_bank.json"))

    def test_snapshot_isolation_and_stale_base(self):
        first = self.session.submit(self.request)
        self.request["total_score"] = 999
        first["request_snapshot"]["total_score"] = 888
        self.assertEqual(self.session.history[0]["request_snapshot"]["total_score"], 20)
        self.session.submit(changes={"total_score": 30}, base_revision=1)
        with self.assertRaises(ValueError):
            self.session.submit(changes={"total_score": 20}, base_revision=1)
        self.assertEqual(len(self.session.history), 2)

    def test_invalid_then_corrected_request(self):
        self.session.submit(self.request)
        invalid = self.session.submit(changes={"total_score": 30}, base_revision=1)
        self.assertEqual(invalid["result"]["status"], "INVALID_REQUEST")
        self.assertFalse(invalid["current_exam_available"])
        corrected = self.session.submit(changes={"total_score": 20}, base_revision=2)
        self.assertEqual(corrected["result"]["status"], "STRUCTURAL_PASS")

    def test_demo_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "changes"
            self.assertTrue(run_demo(output)["passed"])
            self.assertFalse((output / "03_conflicting_request/student_exam.json").exists())
            self.assertFalse((output / "04_candidate_shortage/student_exam.json").exists())
            with self.assertRaises(ValueError):
                run_demo(output)


if __name__ == "__main__":
    unittest.main()
