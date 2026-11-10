from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from evaluation_metrics import calibrated_precision, summarize  # noqa: E402


def test_three_state_metrics_keep_unresolved_separate() -> None:
    summary = summarize([
        {"sample_id": "e1", "category": "typo", "is_clean": False, "status": "DETECTED", "target_type_hit": True},
        {"sample_id": "e2", "category": "typo", "is_clean": False, "status": "UNRESOLVED", "target_type_hit": False},
        {"sample_id": "c1", "category": "clean", "is_clean": True, "status": "CLEAN"},
        {"sample_id": "c2", "category": "clean", "is_clean": True, "status": "DETECTED"},
    ])

    assert summary["conservative_recall"]["rate"] == 0.5
    assert summary["conditional_recall"]["rate"] == 1.0
    assert summary["conservative_fpr"]["rate"] == 0.5
    assert summary["counts"]["unresolved_errors"] == 1
    assert summary["exact_type_recall"]["rate"] == 0.5


def test_calibrated_precision_uses_target_prevalence() -> None:
    assert round(calibrated_precision(0.8, 0.1, 0.05), 3) == 0.296
