from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from validate_dataset_quality import audit, leakage_level  # noqa: E402


def _base_record() -> dict:
    return {
        "sample_id": "sample-1",
        "error_type": "answer_leakage",
        "source_record_id": "source-1",
        "clean_text": "题干。\nA. 一\nB. 二",
        "error_text": "题干（答案：B）。\nA. 一\nB. 二",
        "original_text": "（答案：B）",
        "correction": "",
        "source_answer": "B",
    }


def test_direct_answer_is_strong_leakage() -> None:
    assert leakage_level(_base_record()) == "L2_direct"


def test_generic_hint_is_rejected_from_strict_eval() -> None:
    record = _base_record()
    record["error_text"] = "题干（提示：按公式代入）。\nA. 一\nB. 二"
    record["original_text"] = "（提示：按公式代入）"

    report = audit([record], [])

    assert report["strict_eligible"] == 0
    assert report["issue_counts"]["WEAK_LEAKAGE_LABEL"] == 1


def test_missing_information_requires_two_distinct_witness_answers() -> None:
    record = _base_record()
    record.update({
        "error_type": "missing_info",
        "validation": {
            "necessity_witnesses": [
                {"assumptions": "条件一", "answer": "A"},
                {"assumptions": "条件二", "answer": "B"},
            ]
        },
    })

    report = audit([record], [])

    assert report["strict_eligible"] == 1
