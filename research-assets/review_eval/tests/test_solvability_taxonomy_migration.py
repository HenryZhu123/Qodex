from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from migrate_solvability_taxonomy import (  # noqa: E402
    infer_subtype,
    migrate_gold,
    migrate_row,
    normalize_decision,
)


def test_missing_and_unsolvable_share_one_top_level_type() -> None:
    missing = migrate_row({"error_type": "missing_info", "error_detailed_type": "删除必要条件"})
    impossible = migrate_row(
        {
            "error_type": "unsolvable",
            "error_detailed_type": "条件矛盾",
            "rationale": "两个条件不能同时成立",
        }
    )

    assert missing["error_type"] == "solvability_failure"
    assert missing["solvability_subtype"] == "missing_required_condition"
    assert impossible["error_type"] == "solvability_failure"
    assert impossible["solvability_subtype"] == "contradictory_conditions"


def test_blank_manual_decision_with_completed_reclassification_is_inferred_keep() -> None:
    adjudication = {
        "你的决定": None,
        "正确类别": "unsolvable",
        "你的判断理由": "题目没有设问，无法作答",
    }
    assert normalize_decision(adjudication) == ("keep", True)
    migrated = migrate_row({"error_type": "missing_info"}, adjudication)
    assert migrated["solvability_subtype"] == "underspecified_task"
    assert migrated["strict_eval_eligible"] is True


def test_l0_human_keep_is_preserved_but_excluded_from_strict() -> None:
    adjudication = {
        "你的决定": "keep",
        "正确类别": "answer_leakage",
        "你的判断理由": "普通提示",
        "leakage_level": "L0",
    }
    migrated = migrate_row({"error_type": "answer_leakage"}, adjudication)
    assert migrated["human_decision"] == "keep"
    assert migrated["strict_eval_eligible"] is False


def test_gold_nested_error_uses_production_label_and_subtype() -> None:
    full = migrate_row({"error_type": "unsolvable", "rationale": "有两个正确答案"})
    gold = migrate_gold(
        {
            "sample_id": "x",
            "error_type": "unsolvable",
            "errors": [{"error_type": "unsolvable"}],
        },
        full,
    )
    assert gold["error_type"] == "solvability_failure"
    assert gold["errors"][0]["error_type"] == "可解性错误"
    assert gold["errors"][0]["error_subtype"] == "multiple_valid_answers"


def test_subtype_fallback_is_explicit() -> None:
    assert infer_subtype({"error_type": "unsolvable", "rationale": "无法唯一作答"}) == "indeterminate_answer"
