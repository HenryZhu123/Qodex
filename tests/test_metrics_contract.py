"""Read-only contract test for the v2 honest metrics.

Only reads optimization_research/metrics/review-v2.json and score-v2.json; it does
not touch the frozen Phase C artifacts or call a model.

Run from the repo:
    python3 -m unittest tests.test_metrics_contract -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METRICS = ROOT / "optimization_research" / "metrics"


class MetricsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        review_path = METRICS / "review-v2.json"
        score_path = METRICS / "score-v2.json"
        if not review_path.exists() or not score_path.exists():
            raise unittest.SkipTest("optimization_research/metrics artifacts are not present")
        cls.review = json.loads(review_path.read_text(encoding="utf-8"))
        cls.score = json.loads(score_path.read_text(encoding="utf-8"))
        cls.items = cls.review["items"]

    def test_expected_counts(self):
        self.assertEqual(self.score["pending"], 38)
        self.assertEqual(self.score["blocking_clear"], 38)
        self.assertEqual(self.score["advisory_clear"], 28)
        self.assertEqual(self.score["warning_free"], 27)
        self.assertEqual(self.score["chapter_coverage"], 19)
        self.assertEqual(self.score["total_chapters"], 24)
        self.assertEqual(len(self.items), 38)

    def test_answer_enum_not_boolean(self):
        allowed = {"agree", "disagree", "not_checked"}
        for cid, item in self.items.items():
            value = item["answer_matches"]
            self.assertIsInstance(value, str, cid)
            self.assertNotIsInstance(value, bool, cid)
            self.assertIn(value, allowed, cid)
        self.assertEqual(set(self.score["answer_claim_counts"]), allowed)
        self.assertEqual(sum(self.score["answer_claim_counts"].values()), 38)
        self.assertEqual(self.score["answer_claim_counts"]["agree"], 35)
        self.assertEqual(self.score["answer_claim_counts"]["not_checked"], 3)
        self.assertEqual(self.score["answer_claim_counts"]["disagree"], 0)

    def test_strict_quality_enum_not_boolean(self):
        allowed = {"pass", "soft_warn", "fail", "not_checked"}
        for cid, item in self.items.items():
            value = item["strict_quality"]
            self.assertIsInstance(value, str, cid)
            self.assertNotIsInstance(value, bool, cid)
            self.assertIn(value, allowed, cid)
        self.assertEqual(set(self.score["strict_quality_counts"]), allowed)
        self.assertEqual(sum(self.score["strict_quality_counts"].values()), 38)
        self.assertEqual(self.score["strict_quality_counts"]["pass"], 27)
        self.assertEqual(self.score["strict_quality_counts"]["soft_warn"], 8)
        self.assertEqual(self.score["strict_quality_counts"]["fail"], 0)
        self.assertEqual(self.score["strict_quality_counts"]["not_checked"], 3)

    def test_warning_count_not_persisted(self):
        self.assertNotIn("warning_count", self.review)
        for item in self.items.values():
            self.assertNotIn("warning_count", item)

    def test_derived_fields_present(self):
        for cid, item in self.items.items():
            self.assertEqual(item["case_id"], cid)
            for field in ("area", "subject", "question_type", "warnings", "audit"):
                self.assertIn(field, item, cid)
            self.assertIsInstance(item["warnings"], list, cid)
            self.assertIn("blocking_failures", item["audit"], cid)
            self.assertIn("advisory_failures", item["audit"], cid)
            self.assertIn("failed_checks", item["audit"], cid)

    def test_not_checked_cases_are_retained(self):
        self.assertEqual(
            self.score["component_cases"]["answer_not_checked"],
            ["co.representation-co", "ds.sort-co", "os.foundations-co"],
        )
        self.assertEqual(self.score["component_cases"]["answer_disagree"], [])

    def test_chapter_coverage_uses_advisory_clear(self):
        advisory_areas = {
            self.items[cid]["area"] for cid in self.score["component_cases"]["advisory_clear"]
        }
        self.assertEqual(self.score["chapter_coverage"], len(advisory_areas))
        self.assertEqual(
            self.score["chapter_coverage_detail"]["missing"],
            ["cn.architecture", "cn.network", "co.memory", "ds.sort", "os.process"],
        )


if __name__ == "__main__":
    unittest.main()
