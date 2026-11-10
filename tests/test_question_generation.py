import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from question_generation.generation import generate_question
from question_generation.paging import build_choices

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "question_generation" / "examples" / "paging.json"


class GenerationTests(TestCase):
    def setUp(self):
        self.request = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_example_runs_through_the_local_entry_point(self):
        result = subprocess.run(
            [sys.executable, "-m", "question_generation", str(EXAMPLE)],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        response = json.loads(result.stdout)
        self.assertEqual(response, generate_question(self.request))
        self.assertEqual(response["status"], "GENERATED")
        self.assertEqual(response["request_id"], self.request["request_id"])
        question, = response["questions"]

        student = question["student_view"]
        instructor = question["instructor_view"]
        self.assertEqual(set(student), {"stem", "options"})
        self.assertTrue(all(set(option) == {"id", "text"} for option in student["options"]))
        answers = {option["id"]: int(option["text"], 16) for option in student["options"]}
        self.assertEqual(len(set(answers.values())), 4)
        self.assertEqual(set(instructor["option_explanations"]), set(answers))

        params = question["generator"]["parameters"]
        page, offset = divmod(params["virtual_address"], params["page_size"])
        expected = params["page_table"][str(page)] * params["page_size"] + offset
        self.assertEqual(answers[instructor["correct_option_id"]], expected)
        self.assertIn(f"0x{expected:X}", instructor["explanation"])
        self.assertEqual(question["self_check"]["status"], "PASSED")
        self.assertEqual(question["review_status"], "PENDING")
        self.assertEqual(question["evidence_refs"][0]["anchor"], self.request["evidence"][0]["anchor"])

    def test_missing_evidence_returns_the_missing_rule_and_no_question(self):
        self.request["evidence"][0]["rules"].remove("preserve_offset")
        result = generate_question(self.request)
        self.assertEqual(result["status"], "NEEDS_MATERIAL")
        self.assertEqual(result["missing_rules"], ["preserve_offset"])
        self.assertEqual(result["questions"], [])

    def test_evidence_can_be_combined_and_unused_references_are_excluded(self):
        first = self.request["evidence"][0]
        first["rules"] = ["split_address"]
        second = dict(first, id="frame-mapping", rules=["map_virtual_page", "preserve_offset"])
        unrelated = dict(first, id="unrelated", rules=["tlb"])
        self.request["evidence"].extend([second, unrelated])
        result = generate_question(self.request)
        refs = result["questions"][0]["evidence_refs"]
        self.assertEqual([ref["id"] for ref in refs], [first["id"], second["id"]])

    def test_unsupported_and_invalid_requests(self):
        cases = (
            ({"topic": "multi_level_paging"}, "UNSUPPORTED_REQUEST"),
            ({"question_type": "comprehensive_application"}, "UNSUPPORTED_REQUEST"),
            ({"constraints": {"page_size": 300}}, "INVALID_REQUEST"),
            ({"constraints": {"page_size": 256, "offset": 256}}, "INVALID_REQUEST"),
            ({"constraints": {"offset": None}}, "INVALID_REQUEST"),
            ({"constraints": {"difficulty": "hard"}}, "INVALID_REQUEST"),
            ({"seed": True}, "INVALID_REQUEST"),
            ({"evidence": [{"id": "incomplete"}]}, "INVALID_REQUEST"),
        )
        for changes, status in cases:
            with self.subTest(changes=changes):
                result = generate_question({**self.request, **changes})
                self.assertEqual(result["status"], status)
                self.assertEqual(result["questions"], [])

    def test_self_check_failure_does_not_deliver_a_question(self):
        def wrong_answer(instance, rng):
            choices, answer_id = build_choices(instance, rng)
            return choices, next(key for key in choices if key != answer_id)

        with patch("question_generation.generation.build_choices", side_effect=wrong_answer):
            result = generate_question(self.request)
        self.assertEqual(result["status"], "SELF_CHECK_FAILED")
        self.assertEqual(result["questions"], [])

    def test_cli_returns_machine_readable_failure_and_nonzero_exit(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            for body, status in (
                ("{invalid", "INVALID_REQUEST"),
                (json.dumps({**self.request, "evidence": []}), "NEEDS_MATERIAL"),
            ):
                with self.subTest(status=status):
                    path.write_text(body, encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, "-m", "question_generation", str(path)],
                        cwd=ROOT,
                        capture_output=True,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(json.loads(result.stdout)["status"], status)
