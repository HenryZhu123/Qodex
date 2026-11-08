import json
from pathlib import Path
import subprocess
import sys
from unittest import TestCase
from unittest.mock import patch

from question_generation.generation import generate_question

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "question_generation" / "examples" / "stack.json"


def reachable_outputs(count):
    """Enumerate legal schedules directly from the problem's rules."""
    def visit(next_input, stack, output):
        if len(output) == count:
            yield output
        if next_input <= count:
            yield from visit(next_input + 1, (*stack, next_input), output)
        if stack:
            yield from visit(next_input, stack[:-1], (*output, stack[-1]))

    return set(visit(1, (), ()))


class StackGenerationTests(TestCase):
    def setUp(self):
        self.request = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_cli_sample_is_reproducible_and_includes_evidence(self):
        result = subprocess.run(
            [sys.executable, "-m", "question_generation", str(EXAMPLE)],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        response = json.loads(result.stdout)
        self.assertEqual(response, generate_question(self.request))
        self.assertEqual(response["status"], "GENERATED")
        question, = response["questions"]
        self.assertEqual(question["metadata"]["topic"], "stack_pop_sequence")
        self.assertEqual(question["generator"]["parameters"]["input_sequence"], [1, 2, 3, 4, 5])
        self.assertEqual(question["evidence_refs"][0]["id"], self.request["evidence"][0]["id"])
        self.assertEqual(question["self_check"]["status"], "PASSED")
        self.assertEqual(question["review_status"], "PENDING")
        self.assertEqual(set(question["student_view"]), {"stem", "options"})

    def test_only_one_option_is_reachable_at_each_supported_size(self):
        for count in (4, 5, 6):
            reachable = reachable_outputs(count)
            for seed in range(40):
                with self.subTest(count=count, seed=seed):
                    result = generate_question({
                        **self.request, "seed": seed, "constraints": {"element_count": count},
                    })
                    question, = result["questions"]
                    options = {
                        option["id"]: tuple(map(int, option["text"].split("、")))
                        for option in question["student_view"]["options"]
                    }
                    self.assertEqual(len(set(options.values())), 4)
                    for output in options.values():
                        self.assertEqual(sorted(output), list(range(1, count + 1)))
                    instructor = question["instructor_view"]
                    self.assertEqual(set(options), set(instructor["option_explanations"]))
                    self.assertEqual(
                        [key for key, output in options.items() if output in reachable],
                        [instructor["correct_option_id"]],
                    )

    def test_missing_stack_rule_returns_no_question(self):
        self.request["evidence"][0]["rules"] = ["stack_push_top", "preserve_offset"]
        result = generate_question(self.request)
        self.assertEqual(result["status"], "NEEDS_MATERIAL")
        self.assertEqual(result["missing_rules"], ["stack_pop_top"])
        self.assertEqual(result["questions"], [])

    def test_rejects_incompatible_metadata_and_constraints(self):
        for changes, expected in (
            ({"subject": "operating_systems"}, "UNSUPPORTED_REQUEST"),
            ({"constraints": {"offset": 0}}, "INVALID_REQUEST"),
            ({"constraints": {"element_count": True}}, "INVALID_REQUEST"),
            ({"constraints": {"element_count": 3}}, "INVALID_REQUEST"),
            ({"constraints": {"element_count": 7}}, "INVALID_REQUEST"),
        ):
            with self.subTest(changes=changes):
                result = generate_question({**self.request, **changes})
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["questions"], [])

    def test_self_check_rejects_multiple_reachable_options(self):
        self.request["constraints"]["element_count"] = 4
        choices = {
            "option-1": (1, 2, 3, 4),
            "option-2": (4, 3, 2, 1),
            "option-3": (3, 1, 2, 4),
            "option-4": (4, 2, 3, 1),
        }
        with patch("question_generation.stack.build_choices", return_value=(choices, "option-1")):
            result = generate_question(self.request)
        self.assertEqual(result["status"], "SELF_CHECK_FAILED")
        self.assertEqual(result["questions"], [])
