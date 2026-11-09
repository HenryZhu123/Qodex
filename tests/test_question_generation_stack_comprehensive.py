from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from question_generation import stack_comprehensive as stack
from question_generation.comprehensive import generate_comprehensive, revise_comprehensive

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "question_generation" / "examples" / "stack-comprehensive.json"


def points(question):
    return {
        item["id"]: item["expected"]
        for part in question["instructor_view"]["parts"]
        for item in part["scoring_points"]
    }


class StackComprehensiveTests(TestCase):
    def setUp(self):
        self.request = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def revision(self, current=None, **overrides):
        if current is None:
            current, = generate_comprehensive(self.request)["questions"]
        return {
            "schema_version": "0.1", "request_id": "stack-revision-demo", "current_question": current,
            "feedback": {
                "feedback_id": "review-capacity", "question_id": current["question_id"],
                "target_version": current["version"], "part_id": "minimum-capacity",
                "action": "replace_output_sequence", "replacement_output": [1, 2, 3, 4, 5],
                "comment": "增加最小容量等于 1 的对照示例。", **overrides,
            },
        }

    def cli(self, mode, path):
        result = subprocess.run(
            [sys.executable, "-m", "question_generation", mode, str(path)], cwd=ROOT, capture_output=True,
        )
        return result.returncode, json.loads(result.stdout)

    def test_cli_generation_and_revision_recheck_both_parts(self):
        exit_code, result = self.cli("--comprehensive", EXAMPLE)
        self.assertEqual((exit_code, result["status"]), (0, "GENERATED"))
        self.assertEqual(result, generate_comprehensive(self.request))
        v1, = result["questions"]
        self.assertEqual(v1["generator"]["parameters"]["output_sequence"], [4, 5, 3, 2, 1])
        self.assertEqual(points(v1)["capacity-value"], 4)
        self.assertEqual(points(v1)["capacity-lower-bound"], {"output_position": 1, "height": 4})
        v1.update(review_status="APPROVED", review={"version": 1, "status": "PASS"})
        original = deepcopy(v1)
        revision = self.revision(v1)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "revision.json"
            path.write_text(json.dumps(revision), encoding="utf-8")
            exit_code, revised = self.cli("--revise", path)
            self.assertEqual((exit_code, revised["status"]), (0, "REVISED"))
            self.assertEqual(revised, revise_comprehensive(revision))
            v2, = revised["questions"]
            path.write_text(json.dumps({**revision, "current_question": v2}), encoding="utf-8")
            exit_code, stale = self.cli("--revise", path)
        self.assertEqual((exit_code, stale["status"], stale["questions"]), (1, "STALE_FEEDBACK", []))
        self.assertEqual(v1, original)
        self.assertEqual(v2["question_id"], v1["question_id"])
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v2["review_status"], "PENDING")
        self.assertNotIn("review", v2)
        self.assertEqual(v2["self_check"]["status"], "PASSED")
        self.assertEqual(v2["student_view"]["parts"], v1["student_view"]["parts"])
        self.assertEqual(v2["metadata"], v1["metadata"])
        self.assertEqual(v2["revision"]["affected_parts"], ["operation-trace", "minimum-capacity"])
        self.assertNotEqual(points(v2)["lifo-output-trace"], points(v1)["lifo-output-trace"])
        self.assertEqual(points(v2)["capacity-value"], 1)
        self.assertEqual(points(v2)["capacity-witness"], 1)

    def test_structured_trace_and_capacity_across_supported_sizes(self):
        for count in range(4, 7):
            for seed in range(20):
                with self.subTest(count=count, seed=seed):
                    result = generate_comprehensive({
                        **self.request, "seed": seed, "constraints": {"element_count": count},
                    })
                    question, = result["questions"]
                    parts = question["student_view"]["parts"]
                    self.assertEqual([part["score"] for part in parts], [4, 4])
                    self.assertEqual(question["metadata"]["score"], 8)
                    for part, answer in zip(parts, question["instructor_view"]["parts"]):
                        self.assertEqual(answer["part_id"], part["id"])
                        self.assertEqual(sum(item["points"] for item in answer["scoring_points"]), part["score"])
                        self.assertTrue(all(method["acceptance"] for method in answer["equivalent_methods"]))
                    expected = points(question)
                    pending, output, pushed = [], [], []
                    for operation in expected["lifo-output-trace"]:
                        if operation["action"] == "push":
                            pushed.append(operation["value"])
                            pending.append(operation["value"])
                        else:
                            self.assertEqual(operation["action"], "pop")
                            self.assertEqual(operation["value"], pending[-1])
                            output.append(pending.pop())
                    self.assertEqual(pending, [])
                    self.assertEqual(pushed, list(range(1, count + 1)))
                    self.assertEqual(output, question["generator"]["parameters"]["output_sequence"])
                    capacity = max(max(output[:index + 1]) - index for index in range(count))
                    self.assertEqual(expected["capacity-value"], capacity)
                    witness = expected["capacity-lower-bound"]["output_position"]
                    self.assertEqual(max(output[:witness]) - witness + 1, capacity)

    def test_invalid_feedback_and_snapshots_never_produce_a_version(self):
        for overrides, status in (
            ({"replacement_output": [3, 1, 2, 4, 5]}, "INVALID_REQUEST"),
            ({"replacement_output": [1, 2, 2, 4, 5]}, "INVALID_REQUEST"),
            ({"replacement_output": [True, 2, 3, 4, 5]}, "INVALID_REQUEST"),
            ({"replacement_output": [4, 5, 3, 2, 1]}, "INVALID_REQUEST"),
            ({"target_version": 2}, "STALE_FEEDBACK"),
            ({"part_id": "operation-trace"}, "UNSUPPORTED_FEEDBACK"),
            ({"question_id": "wrong"}, "FEEDBACK_TARGET_MISMATCH"),
        ):
            with self.subTest(overrides=overrides):
                result = revise_comprehensive(self.revision(**overrides))
                self.assertEqual((result["status"], result["questions"]), (status, []))
        payload = self.revision()
        payload["current_question"]["instructor_view"]["parts"][1]["scoring_points"][0]["expected"] = 99
        result = revise_comprehensive(payload)
        self.assertEqual((result["status"], result["questions"]), ("INVALID_REQUEST", []))

    def test_revision_limit(self):
        v2, = revise_comprehensive(self.revision())["questions"]
        v3, = revise_comprehensive(self.revision(v2, replacement_output=[5, 4, 3, 2, 1]))["questions"]
        self.assertEqual((v3["version"], points(v3)["capacity-value"]), (3, 5))
        result = revise_comprehensive(self.revision(v3))
        self.assertEqual((result["status"], result["questions"]), ("REVISION_LIMIT", []))

    def test_revised_trace_must_pass_independent_recheck(self):
        request = self.revision()
        build = stack._build_views

        def incorrect(count, output):
            student, instructor = build(count, output)
            if output == (1, 2, 3, 4, 5):
                instructor["parts"][0]["scoring_points"][1]["expected"][0]["value"] = 2
            return student, instructor

        with patch.object(stack, "_build_views", side_effect=incorrect):
            result = revise_comprehensive(request)
        self.assertEqual((result["status"], result["questions"]), ("SELF_CHECK_FAILED", []))
        self.assertIn("operation-trace", result["message"])

    def test_generation_requires_evidence_and_valid_element_count(self):
        for overrides, status in (
            ({"evidence": []}, "NEEDS_MATERIAL"),
            ({"constraints": {"element_count": 7}}, "INVALID_REQUEST"),
            ({"question_type": "single_choice"}, "UNSUPPORTED_REQUEST"),
        ):
            result = generate_comprehensive({**self.request, **overrides})
            self.assertEqual((result["status"], result["questions"]), (status, []))
