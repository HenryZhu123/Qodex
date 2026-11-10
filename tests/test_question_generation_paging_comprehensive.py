from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from question_generation import paging_comprehensive as comprehensive

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "question_generation" / "examples" / "paging-comprehensive.json"


def point_values(question):
    return {
        point["id"]: point["expected"]
        for part in question["instructor_view"]["parts"]
        for point in part["scoring_points"]
    }


class PagingComprehensiveTests(TestCase):
    def setUp(self):
        self.request = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def revision(self, current=None, **changes):
        if current is None:
            current, = comprehensive.generate_comprehensive(self.request)["questions"]
        feedback = {
            "feedback_id": "review-cross-page",
            "question_id": current["question_id"],
            "target_version": current["version"],
            "part_id": "cross-page",
            "action": "replace_next_frame",
            "replacement_frame": 18,
            "comment": "演示跨页后物理地址连续的情况。",
            **changes,
        }
        return {"schema_version": "0.1", "request_id": "revise-demo",
                "current_question": current, "feedback": feedback}

    def cli(self, mode, path):
        cli = subprocess.run(
            [sys.executable, "-m", "question_generation", mode, str(path)],
            cwd=ROOT, capture_output=True,
        )
        return cli.returncode, json.loads(cli.stdout)

    def test_cli_closed_loop_and_stale_feedback(self):
        code, v1 = self.cli("--comprehensive", EXAMPLE)
        self.assertEqual((code, v1["status"]), (0, "GENERATED"))
        self.assertEqual(v1, comprehensive.generate_comprehensive(self.request))
        before, = v1["questions"]
        self.assertEqual(before["version"], 1)
        self.assertEqual(before["review_status"], "PENDING")
        self.assertEqual(point_values(before), {
            "virtual-page": 11, "page-offset": 0xB4, "page-frame": 17, "translated-address": 0x11B4,
            "before-address": 0x11FF, "next-page-offset": {"virtual_page": 12, "offset": 0},
            "next-frame": 63, "after-address": 0x3F00, "increasing-contiguity": False,
        })
        before.update(review_status="APPROVED", review={"version": 1, "status": "PASS"})
        original = deepcopy(before)
        payload = self.revision(before)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "revision.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, v2 = self.cli("--revise", path)
            self.assertEqual((code, v2["status"]), (0, "REVISED"))
            self.assertEqual(v2, comprehensive.revise_comprehensive(payload))
            after, = v2["questions"]
            stale = {**payload, "current_question": after}
            path.write_text(json.dumps(stale), encoding="utf-8")
            code, result = self.cli("--revise", path)
        self.assertEqual((code, result["status"], result["questions"]), (1, "STALE_FEEDBACK", []))
        self.assertEqual(before, original)
        self.assertEqual(after["question_id"], before["question_id"])
        self.assertEqual(after["version"], 2)
        self.assertEqual(after["review_status"], "PENDING")
        self.assertNotIn("review", after)
        self.assertEqual(after["self_check"]["status"], "PASSED")
        self.assertEqual(after["student_view"]["parts"], before["student_view"]["parts"])
        self.assertNotEqual(after["student_view"]["stem"], before["student_view"]["stem"])
        self.assertIn("虚页 12 对应物理页框 18", after["student_view"]["stem"])
        self.assertEqual(after["instructor_view"]["parts"][:2], before["instructor_view"]["parts"][:2])
        self.assertEqual(after["metadata"], before["metadata"])
        self.assertEqual(after["evidence_refs"], before["evidence_refs"])
        before_points = point_values(before)
        self.assertEqual(point_values(after), {
            **before_points, "next-frame": 18, "after-address": 0x1200, "increasing-contiguity": True,
        })
        self.assertEqual((after["revision"]["part_id"], after["revision"]["from_version"]), ("cross-page", 1))

    def test_scores_and_equivalent_methods(self):
        question, = comprehensive.generate_comprehensive(self.request)["questions"]
        student = question["student_view"]
        instructor = question["instructor_view"]
        self.assertEqual(set(student), {"stem", "parts"})
        self.assertEqual([part["score"] for part in student["parts"]], [2, 3, 5])
        self.assertEqual(sum(part["score"] for part in student["parts"]), question["metadata"]["score"])
        ids = [part["id"] for part in student["parts"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([part["part_id"] for part in instructor["parts"]], ids)
        rubric = []
        for prompt, solution in zip(student["parts"], instructor["parts"]):
            self.assertEqual(set(prompt), {"id", "prompt", "score"})
            points = solution["scoring_points"]
            self.assertEqual(sum(point["points"] for point in points), prompt["score"])
            self.assertTrue(all(point["points"] > 0 and point["criterion"] for point in points))
            self.assertTrue(all(method["acceptance"] for method in solution["equivalent_methods"]))
            rubric.extend(point["id"] for point in points)
        self.assertEqual(len(rubric), len(set(rubric)))

    def test_invalid_or_unsupported_feedback_does_not_create_a_version(self):
        for changes, status in (
            ({"target_version": 2}, "STALE_FEEDBACK"),
            ({"question_id": "another-item"}, "FEEDBACK_TARGET_MISMATCH"),
            ({"part_id": "split-address"}, "UNSUPPORTED_FEEDBACK"),
            ({"action": "replace_previous_frame"}, "UNSUPPORTED_FEEDBACK"),
            ({"replacement_frame": 63}, "INVALID_REQUEST"),
            ({"replacement_frame": 17}, "INVALID_REQUEST"),
            ({"replacement_frame": True}, "INVALID_REQUEST"),
            ({"replacement_frame": 64}, "INVALID_REQUEST"),
        ):
            with self.subTest(changes=changes):
                result = comprehensive.revise_comprehensive(self.revision(**changes))
                self.assertEqual((result["status"], result["questions"]), (status, []))

    def test_revision_limits_and_reverse_frame_direction(self):
        v2, = comprehensive.revise_comprehensive(self.revision(replacement_frame=16))["questions"]
        self.assertEqual(point_values(v2)["after-address"], 0x1000)
        self.assertIs(point_values(v2)["increasing-contiguity"], False)
        v3, = comprehensive.revise_comprehensive(self.revision(v2, replacement_frame=0))["questions"]
        self.assertEqual(v3["version"], 3)
        self.assertEqual(point_values(v3)["after-address"], 0)
        result = comprehensive.revise_comprehensive(self.revision(v3, replacement_frame=18))
        self.assertEqual((result["status"], result["questions"]), ("REVISION_LIMIT", []))

    def test_corrupted_snapshot_is_rejected(self):
        request = self.revision()
        current = request["current_question"]
        current["instructor_view"]["parts"][2]["scoring_points"][-1]["expected"] = 0
        result = comprehensive.revise_comprehensive(request)
        self.assertEqual((result["status"], result["questions"]), ("INVALID_REQUEST", []))

    def test_revision_requires_new_answer_and_rubric_to_pass_self_check(self):
        request = self.revision()
        build = comprehensive._build_views

        def corrupt_revised(instance):
            student, instructor = build(instance)
            if 18 in instance.page_table.values():
                instructor["parts"][2]["scoring_points"][-1]["expected"] = False
            return student, instructor

        with patch.object(comprehensive, "_build_views", side_effect=corrupt_revised):
            result = comprehensive.revise_comprehensive(request)
        self.assertEqual((result["status"], result["questions"]), ("SELF_CHECK_FAILED", []))
        self.assertIn("cross-page", result["message"])

    def test_evidence_and_type_validation(self):
        for change, status in (
            ({"evidence": []}, "NEEDS_MATERIAL"),
            ({"constraints": {"page_size": 300}}, "INVALID_REQUEST"),
            ({"subject": "computer_networks"}, "UNSUPPORTED_REQUEST"),
            ({"question_type": "single_choice"}, "UNSUPPORTED_REQUEST"),
        ):
            with self.subTest(change=change):
                result = comprehensive.generate_comprehensive({**self.request, **change})
                self.assertEqual((result["status"], result["questions"]), (status, []))

    def test_minimum_and_maximum_supported_page_size(self):
        for size in (2, 65536):
            for offset in (0, size - 1):
                with self.subTest(size=size, offset=offset):
                    request = {**self.request, "constraints": {"page_size": size, "offset": offset}}
                    question, = comprehensive.generate_comprehensive(request)["questions"]
                    points = point_values(question)
                    self.assertEqual(points["page-offset"], offset)
                    self.assertEqual(points["translated-address"], 17 * size + offset)
                    self.assertEqual(points["before-address"], 18 * size - 1)
                    self.assertEqual(points["after-address"], 63 * size)
