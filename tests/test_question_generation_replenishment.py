import copy
import json
from pathlib import Path
import unittest

from question_generation.replenishment import generate_replenishment
from question_generation.stack import render_stem


EXAMPLES = Path(__file__).resolve().parents[1] / "question_generation" / "examples"


def request():
    stack = json.loads((EXAMPLES / "stack.json").read_text(encoding="utf-8"))
    return {
        "seed": 42,
        "replenishment_request": {
            "schema_version": "1.0",
            "request_id": "joint-deficit",
            "plan_status": "PROPOSED_NOT_EXECUTED",
            "scope": "CURRENT_VERIFIED_CANDIDATE_POOL",
            "suggested_additional_count": 1,
            "avoid_stems": [],
            "deficits": [{
                "subject": "数据结构", "knowledge_point": "栈", "question_type": "single_choice",
                "difficulty": "hard", "score_per_question": 2, "missing_count": 1,
            }],
        },
        "slot_profiles": {"assembly-1": {
            "topic": stack["topic"], "constraints": stack["constraints"], "evidence": stack["evidence"],
        }},
    }


class ReplenishmentTests(unittest.TestCase):
    def test_one_joint_slot_and_score_preserve_provenance_without_claiming_difficulty(self):
        payload = request()
        before = copy.deepcopy(payload)
        result = generate_replenishment(payload)
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(result["generated_count"], 1)
        self.assertEqual(result["generated_score"], 2)
        self.assertEqual(result["assembly_request_id"], "joint-deficit")
        question, = result["questions"]
        self.assertEqual(question["slot_id"], "assembly-1")
        self.assertEqual(question["metadata"]["score"], 2)
        self.assertEqual(question["review_status"], "PENDING")
        self.assertEqual(question["self_check"]["status"], "PASSED")
        self.assertEqual(question["assembly_slot"], {
            **payload["replenishment_request"]["deficits"][0],
            "request_id": "joint-deficit", "difficulty_status": "REVIEW_REQUIRED",
        })
        self.assertEqual(payload, before)
        self.assertEqual(generate_replenishment(payload), result)
        payload["replenishment_request"]["deficits"][0]["difficulty"] = "easy"
        self.assertNotEqual(generate_replenishment(payload)["questions"][0]["question_id"], question["question_id"])

    def test_unmapped_topic_and_missing_material_preserve_other_slot(self):
        payload = request()
        plan = payload["replenishment_request"]
        plan["suggested_additional_count"] = 3
        plan["deficits"] += [
            {**plan["deficits"][0], "knowledge_point": "队列"},
            {**plan["deficits"][0], "difficulty": "easy"},
        ]
        payload["slot_profiles"]["assembly-3"] = {"topic": "stack_pop_sequence", "evidence": []}
        result = generate_replenishment(payload)
        self.assertEqual((result["status"], result["requested_score"], result["generated_score"]), ("PARTIAL", 6, 2))
        self.assertEqual([item["reason"]["code"] for item in result["deficits"]], ["UNSUPPORTED_REQUEST", "NEEDS_MATERIAL"])
        self.assertEqual([item["assembly_slot"]["knowledge_point"] for item in result["deficits"]], ["队列", "栈"])

    def test_reserved_stem_uses_existing_normalization(self):
        payload = request()
        payload["replenishment_request"]["avoid_stems"] = ["  " + render_stem(5).replace("5", "５") + "\n"]
        result = generate_replenishment(payload)
        self.assertEqual(result["status"], "NO_QUESTIONS")
        self.assertEqual(result["deficits"][0]["reason"]["code"], "REFERENCE_DUPLICATE")
        self.assertEqual(result["deficits"][0]["reason"]["reference_ids"], ["reserved-stem-1"])

    def test_rejects_invalid_plan_before_sampling(self):
        def unexpected(_):
            self.fail("Invalid plan must not generate candidates")

        for changes in (
            {"suggested_additional_count": 2}, {"schema_version": "2.0"},
            {"plan_status": "UNRESOLVED"}, {"avoid_stems": [None]},
            {"deficits": [{"missing_count": 1}]},
        ):
            with self.subTest(changes=changes):
                payload = request()
                payload["replenishment_request"].update(changes)
                result = generate_replenishment(payload, single_generator=unexpected)
                self.assertEqual(result["status"], "INVALID_REQUEST")
                self.assertFalse(result["questions"])

    def test_unsupported_type_is_not_converted_to_single_choice(self):
        payload = request()
        payload["replenishment_request"]["deficits"][0]["question_type"] = "calculation"
        result = generate_replenishment(payload)
        self.assertEqual(result["status"], "NO_QUESTIONS")
        self.assertEqual(result["deficits"][0]["reason"]["code"], "UNSUPPORTED_REQUEST")
        self.assertEqual(result["deficits"][0]["assembly_slot"]["question_type"], "calculation")
