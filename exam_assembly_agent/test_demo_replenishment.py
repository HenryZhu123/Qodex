import json
from pathlib import Path
import tempfile
import unittest
from .demo_replenishment import run_demo


class DemoTests(unittest.TestCase):
    def test_saved_artifacts_and_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "demo"
            summary = run_demo(output)
            self.assertTrue(summary["passed"])
            for name in ("01_initial", "02_pending_review", "04_stale_review"):
                self.assertFalse((output / name / "student_exam.json").exists())
            student = json.loads((output / "03_mock_review_passed/student_exam.json").read_text(encoding="utf-8"))
            self.assertEqual(len(student), 2)
            self.assertTrue(all("answer" not in q for q in student))
            with self.assertRaises(ValueError):
                run_demo(output)


if __name__ == "__main__":
    unittest.main()
