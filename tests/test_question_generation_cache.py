import json
from pathlib import Path
import subprocess
import sys
from unittest import TestCase
from unittest.mock import patch

from question_generation import cache
from question_generation.generation import generate_question

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "question_generation" / "examples" / "cache.json"


class CacheGenerationTests(TestCase):
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
            ["18、3、4"],
        )
        self.assertEqual(question["review_status"], "PENDING")

    def test_address_fields_across_supported_geometry(self):
        for cache_size in (2**power for power in range(4, 13)):
            for block_size in (2**power for power in range(2, 9) if 2**power < cache_size):
                for address in (0, block_size - 1, block_size, cache_size, 0xA5B3, 65535):
                    with self.subTest(cache_size=cache_size, block_size=block_size, address=address):
                        result = generate_question({
                            **self.request,
                            "constraints": {"cache_size": cache_size, "block_size": block_size, "address": address},
                        })
                        question, = result["questions"]
                        options = {
                            option["id"]: tuple(map(int, option["text"].split("、")))
                            for option in question["student_view"]["options"]
                        }
                        self.assertEqual(len(set(options.values())), 4)
                        for tag, index, offset in options.values():
                            self.assertIn(tag, range(65536 // cache_size))
                            self.assertIn(index, range(cache_size // block_size))
                            self.assertIn(offset, range(block_size))
                        matching = [
                            key for key, (tag, index, offset) in options.items()
                            if tag * cache_size + index * block_size + offset == address
                        ]
                        self.assertEqual(matching, [question["instructor_view"]["correct_option_id"]])

    def test_invalid_constraints_and_missing_material(self):
        for constraints in (
            {"block_size": 24}, {"block_size": 256}, {"cache_size": True},
            {"cache_size": 65536}, {"address": None}, {"address": 65536}, {"offset": 0},
        ):
            with self.subTest(constraints=constraints):
                result = generate_question({**self.request, "constraints": constraints})
                self.assertEqual(result["status"], "INVALID_REQUEST")
                self.assertEqual(result["questions"], [])
        self.request["evidence"][0]["rules"].remove("cache_tag")
        result = generate_question(self.request)
        self.assertEqual(result["status"], "NEEDS_MATERIAL")
        self.assertEqual(result["missing_rules"], ["cache_tag"])
        self.assertEqual(result["questions"], [])

    def test_self_check_blocks_mismatched_answer(self):
        def wrong_expected(*args, **kwargs):
            stem, choices, _, params = build(*args, **kwargs)
            return stem, choices, choices[1][0], params

        build = cache.build
        with patch.object(cache, "build", side_effect=wrong_expected):
            result = generate_question(self.request)
            self.assertEqual(result["status"], "SELF_CHECK_FAILED")
            self.assertEqual(result["questions"], [])
