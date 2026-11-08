import json
from pathlib import Path
import subprocess
import sys
from unittest import TestCase
from unittest.mock import patch

from question_generation import tcp
from question_generation.batch import generate_batch
from question_generation.generation import generate_question

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "question_generation" / "examples" / "tcp.json"


class TCPGenerationTests(TestCase):
    def setUp(self):
        self.request = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_cli_and_both_evidence_anchors(self):
        cli = subprocess.run(
            [sys.executable, "-m", "question_generation", str(EXAMPLE)],
            cwd=ROOT, capture_output=True, check=True,
        )
        response = json.loads(cli.stdout)
        self.assertEqual(response, generate_question(self.request))
        question, = response["questions"]
        self.assertEqual([ref["anchor"] for ref in question["evidence_refs"]],
                         ["§2.2 Key TCP Concepts", "§3.7 Segmentation"])
        self.assertEqual(question["review_status"], "PENDING")
        self.assertEqual(set(question["student_view"]), {"stem", "options"})

    def test_each_scenario_has_one_correct_option_across_option_orders(self):
        for scenario, expected in (("reads", "保持发送顺序"), ("framing", "固定宽度的长度字段")):
            for seed in (0, 1, 42, 43):
                with self.subTest(scenario=scenario, seed=seed):
                    result = generate_question({
                        **self.request, "seed": seed, "constraints": {"scenario": scenario},
                    })
                    question, = result["questions"]
                    options = {item["id"]: item["text"] for item in question["student_view"]["options"]}
                    instructor = question["instructor_view"]
                    self.assertEqual(len(set(options.values())), 4)
                    self.assertEqual([key for key, text in options.items() if expected in text],
                                     [instructor["correct_option_id"]])
                    self.assertEqual(set(instructor["option_explanations"]), set(options))

    def test_material_and_constraints(self):
        for removed in self.request["evidence"]:
            result = generate_question({
                **self.request, "evidence": [item for item in self.request["evidence"] if item is not removed],
            })
            self.assertEqual(result["status"], "NEEDS_MATERIAL")
            self.assertEqual(result["missing_rules"], removed["rules"])
        for constraints in ({"scenario": []}, {"scenario": "unknown"}, {"offset": 0}):
            result = generate_question({**self.request, "constraints": constraints})
            self.assertEqual(result["status"], "INVALID_REQUEST")
            self.assertEqual(result["questions"], [])

    def test_batch_can_use_both_scenarios(self):
        slot = {key: self.request[key] for key in ("subject", "topic", "question_type", "evidence")}
        result = generate_batch({
            "schema_version": "0.1", "request_id": "tcp-pair", "seed": 42,
            "question_count": 2, "total_score": 4,
            "slots": [{**slot, "slot_id": "tcp", "count": 2, "score_per_question": 2}],
        })
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual({q["generator"]["parameters"]["scenario"] for q in result["questions"]},
                         {"reads", "framing"})

    def test_two_supported_claims_fail_self_check(self):
        with patch.object(tcp, "SUPPORTED_CLAIMS", tcp.SUPPORTED_CLAIMS | {"one_read_per_write"}):
            result = generate_question(self.request)
        self.assertEqual(result["status"], "SELF_CHECK_FAILED")
        self.assertEqual(result["questions"], [])
