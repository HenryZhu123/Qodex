from ipaddress import IPv4Address
import json
from pathlib import Path
import subprocess
import sys
from unittest import TestCase
from unittest.mock import patch

from question_generation import subnet
from question_generation.generation import generate_question

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "question_generation" / "examples" / "subnet.json"


class SubnetGenerationTests(TestCase):
    def setUp(self):
        self.request = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_cli_example(self):
        result = subprocess.run(
            [sys.executable, "-m", "question_generation", str(EXAMPLE)],
            cwd=ROOT, capture_output=True, check=True,
        )
        response = json.loads(result.stdout)
        self.assertEqual(response, generate_question(self.request))
        question, = response["questions"]
        answer = question["instructor_view"]["correct_option_id"]
        self.assertEqual(
            [option["text"] for option in question["student_view"]["options"] if option["id"] == answer],
            ["10.23.45.64"],
        )
        self.assertEqual(question["review_status"], "PENDING")

    def test_all_prefixes_and_address_boundaries(self):
        for prefix in range(16, 31):
            for seed, address in enumerate((
                "0.0.0.0", "255.255.255.255", "10.23.45.77", "10.23.45.64",
                "10.23.45.127", None, None, None, None, None,
            )):
                with self.subTest(prefix=prefix, seed=seed, address=address):
                    constraints = {"prefix_length": prefix}
                    if address is not None:
                        constraints["ipv4_address"] = address
                    result = generate_question({**self.request, "seed": seed, "constraints": constraints})
                    question, = result["questions"]
                    params = question["generator"]["parameters"]
                    self.assertEqual(params["prefix_length"], prefix)
                    if address is None:
                        self.assertTrue(params["ipv4_address"].startswith("10."))
                    else:
                        self.assertEqual(params["ipv4_address"], address)
                    mask = ((1 << prefix) - 1) << (32 - prefix)
                    expected = int(IPv4Address(params["ipv4_address"])) & mask
                    options = {
                        option["id"]: int(IPv4Address(option["text"]))
                        for option in question["student_view"]["options"]
                    }
                    self.assertEqual(len(set(options.values())), 4)
                    self.assertEqual(
                        [key for key, value in options.items() if value == expected],
                        [question["instructor_view"]["correct_option_id"]],
                    )

    def test_invalid_constraints_and_missing_material(self):
        for constraints in (
            {"prefix_length": 15}, {"prefix_length": 31}, {"prefix_length": True},
            {"ipv4_address": None}, {"ipv4_address": 123},
            {"ipv4_address": "010.23.45.77"}, {"ipv4_address": "10.23.45.77/26"},
            {"ipv4_address": "::1"}, {"ipv4_address": "10.23.45.256"}, {"address": 0},
        ):
            with self.subTest(constraints=constraints):
                result = generate_question({**self.request, "constraints": constraints})
                self.assertEqual(result["status"], "INVALID_REQUEST")
                self.assertEqual(result["questions"], [])
        self.request["evidence"][0]["rules"].remove("ipv4_subnet_alignment")
        result = generate_question(self.request)
        self.assertEqual(result["status"], "NEEDS_MATERIAL")
        self.assertEqual(result["missing_rules"], ["ipv4_subnet_alignment"])
        self.assertEqual(result["questions"], [])

    def test_self_check_blocks_duplicate_choices(self):
        def duplicate_choice(*args, **kwargs):
            stem, choices, expected, params = build(*args, **kwargs)
            choices[-1] = choices[0]
            return stem, choices, expected, params

        build = subnet.build
        with patch.object(subnet, "build", side_effect=duplicate_choice):
            result = generate_question(self.request)
            self.assertEqual(result["status"], "SELF_CHECK_FAILED")
            self.assertEqual(result["questions"], [])
