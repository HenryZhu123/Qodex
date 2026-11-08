from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from question_generation.batch import ATTEMPTS_PER_QUESTION, generate_batch
from question_generation.generation import generate_question

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "question_generation" / "examples" / "batch.json"


class BatchGenerationTests(TestCase):
    def setUp(self):
        self.request = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def run_cli(self, path):
        return subprocess.run(
            [sys.executable, "-m", "question_generation", "--batch", str(path)],
            cwd=ROOT, capture_output=True,
        )

    def test_mixed_batch_cli_preserves_slot_counts_and_metadata(self):
        cli = self.run_cli(EXAMPLE)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        result = json.loads(cli.stdout)
        self.assertEqual(result, generate_batch(self.request))
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(result["requested_count"], 5)
        self.assertEqual(result["generated_count"], 5)
        self.assertEqual(result["requested_score"], 11)
        self.assertEqual(result["generated_score"], 11)
        self.assertEqual(result["deficits"], [])
        slots = {slot["slot_id"]: slot for slot in self.request["slots"]}
        counts = Counter(question["slot_id"] for question in result["questions"])
        self.assertEqual(counts, {key: slot["count"] for key, slot in slots.items()})
        self.assertEqual(len({question["question_id"] for question in result["questions"]}), 5)
        self.assertEqual(len({question["student_view"]["stem"] for question in result["questions"]}), 5)
        for question in result["questions"]:
            slot = slots[question["slot_id"]]
            self.assertEqual(question["metadata"], {
                "subject": slot["subject"], "topic": slot["topic"],
                "question_type": slot["question_type"], "score": slot["score_per_question"],
            })
            self.assertEqual(question["self_check"]["status"], "PASSED")
            self.assertEqual(question["review_status"], "PENDING")

    def test_partial_batch_reports_missing_material_and_duplicate_candidates(self):
        self.request["slots"][1]["evidence"] = []
        self.request["slots"][2]["count"] = 2
        self.request["question_count"] += 1
        self.request["total_score"] += 3
        with TemporaryDirectory() as directory:
            path = Path(directory) / "partial.json"
            path.write_text(json.dumps(self.request), encoding="utf-8")
            cli = self.run_cli(path)
        self.assertEqual(cli.returncode, 1, cli.stderr)
        result = json.loads(cli.stdout)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["requested_count"], 6)
        self.assertEqual(result["generated_count"], 4)
        self.assertEqual(result["requested_score"], 14)
        self.assertEqual(result["generated_score"], 9)
        self.assertEqual([question["slot_id"] for question in result["questions"]],
                         ["paging", "paging", "cache", "subnet"])
        stack, cache = result["deficits"]
        self.assertEqual((stack["slot_id"], stack["missing_count"]), ("stack", 1))
        self.assertEqual(stack["reason"]["code"], "NEEDS_MATERIAL")
        self.assertEqual(stack["reason"]["missing_rules"], ["stack_pop_top", "stack_push_top"])
        self.assertEqual(stack["attempts"], 1)
        self.assertEqual((cache["slot_id"], cache["missing_count"]), ("cache", 1))
        self.assertEqual(cache["reason"]["code"], "INSUFFICIENT_UNIQUE_CANDIDATES")
        self.assertEqual(cache["unique_candidate_count"], 1)
        self.assertEqual(cache["attempts"], 2 * ATTEMPTS_PER_QUESTION)

    def test_same_stem_with_new_seeds_ids_and_choices_is_still_a_duplicate(self):
        cache = self.request["slots"][2]
        other = {**cache, "slot_id": "other-cache", "score_per_question": 2}
        request = {**self.request, "slots": [cache, other], "question_count": 2, "total_score": 5}
        candidates = []

        def observe(payload):
            result = generate_question(payload)
            question, = result["questions"]
            candidates.append(question)
            return result

        with patch("question_generation.batch.generate_question", side_effect=observe):
            result = generate_batch(request)
        self.assertEqual(result["generated_count"], 1)
        self.assertEqual(result["deficits"][0]["slot_id"], "other-cache")
        self.assertEqual(len({question["student_view"]["stem"] for question in candidates}), 1)
        self.assertGreater(len({question["generator"]["seed"] for question in candidates}), 1)
        self.assertGreater(len({question["question_id"] for question in candidates}), 1)
        self.assertGreater(len({
            tuple(option["text"] for option in question["student_view"]["options"])
            for question in candidates
        }), 1)

    def test_allocation_can_move_a_candidate_to_fill_a_more_restrictive_slot(self):
        fixed = self.request["slots"][2]
        flexible = {**fixed, "slot_id": "flexible",
                    "constraints": {"cache_size": 256, "block_size": 16}}
        request = {**self.request, "slots": [flexible, fixed], "question_count": 2, "total_score": 6}

        def overlap(payload):
            if "address" not in payload["constraints"]:
                address = 4660 if payload["request_id"].endswith("/1") else 4661
                payload = {**payload, "constraints": {**payload["constraints"], "address": address}}
            return generate_question(payload)

        with patch("question_generation.batch.generate_question", side_effect=overlap):
            result = generate_batch(request)
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(
            [(question["slot_id"], question["generator"]["parameters"]["address"])
             for question in result["questions"]],
            [("flexible", 4661), ("cache", 4660)],
        )

    def test_wrong_candidate_metadata_cannot_fill_a_slot(self):
        cache = self.request["slots"][2]
        request = {**self.request, "slots": [cache], "question_count": 1, "total_score": 3}
        for field, value in (
            ("subject", "data_structures"), ("topic", "single_level_paging"),
            ("question_type", "comprehensive_application"), ("score", 2), ("score", True),
        ):
            with self.subTest(field=field, value=value):
                def mismatch(payload):
                    result = generate_question(payload)
                    result["questions"][0]["metadata"][field] = value
                    return result

                with patch("question_generation.batch.generate_question", side_effect=mismatch):
                    result = generate_batch(request)
                self.assertEqual(result["status"], "NO_QUESTIONS")
                self.assertEqual(result["generated_count"], 0)
                self.assertEqual(result["deficits"][0]["reason"]["code"], "SLOT_MISMATCH")

    def test_rejects_inconsistent_or_invalid_batch_without_generating(self):
        duplicate_slots = deepcopy(self.request["slots"])
        duplicate_slots[1]["slot_id"] = duplicate_slots[0]["slot_id"]
        invalid_slots = deepcopy(self.request["slots"])
        invalid_slots[0]["score_per_question"] = True
        for changes in (
            {"question_count": 6}, {"question_count": 101}, {"total_score": 10},
            {"seed": True}, {"slots": duplicate_slots}, {"slots": invalid_slots}, {"slots": []},
        ):
            with self.subTest(changes=changes):
                with patch("question_generation.batch.generate_question") as single:
                    result = generate_batch({**self.request, **changes})
                single.assert_not_called()
                self.assertEqual(result["status"], "INVALID_REQUEST")
                self.assertEqual(result["questions"], [])
