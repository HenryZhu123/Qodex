"""Synthetic offline examples. Simulated reviewer records are not actual human approval."""
import copy
import json
from pathlib import Path
import sys

from exam_assembly_agent.similarity import inspect_pair
from exam_assembly_agent.similarity_assembly import assemble_with_similarity
from exam_assembly_service.replenishment import propose_replenishment


def question(qid, stem, options=None):
    return dict(question_id=qid, version=1, subject="数据结构", question_type="single_choice", topic="栈",
                difficulty="easy", score=2, stem=stem, options=options or dict(A="栈", B="队列", C="树", D="图"),
                answer="A", explanation="合成测试解析，不是真实试题审校结果",
                review=dict(status="PASS", question_version=1, is_mock=True))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    req = dict(request_id="SIMILARITY_SYNTHETIC_DEMO", subject="数据结构", question_type="single_choice",
               question_count=2, score_per_question=2, total_score=4, topic_counts={"栈": 2},
               difficulty_counts={"easy": 2}, max_repair_rounds=3, allow_mock_reviews=True)
    a = question("TEST_ONLY_a", "容量为3的顺序栈中依次压入元素，哪项描述了它的操作规则？")
    b = question("TEST_ONLY_b", "容量为5的顺序栈中依次压入元素，哪项描述了它的操作规则？")
    c = question("TEST_ONLY_c", "空栈出栈会怎样？", dict(A="下溢", B="上溢", C="扩容", D="遍历"))
    shuffle = {**b, "stem": a["stem"], "options": dict(A="队列", B="栈", C="图", D="树"), "answer": "B"}
    pair = inspect_pair(a, b)
    simulated = dict(pair_id=pair["pair_id"], question_ids=pair["question_ids"], content_hashes=pair["content_hashes"],
                     source="human", reviewer="SYNTHETIC_TEST_ONLY_NOT_A_REAL_REVIEWER", verdict="DUPLICATE",
                     reason="仅模拟复核分支，不代表实际人工评测；不得向正式题库提交")
    changed = copy.deepcopy(a)
    changed.update(version=2, review=dict(status="PASS", question_version=2, is_mock=True))
    cases = [
        ("01_option_shuffle_repaired", [a, shuffle, c], [], "STRUCTURAL_PASS"),
        ("02_suspected_waiting_review", [a, b, c], [], "UNRESOLVED"),
        ("03_simulated_duplicate_replaced", [a, b, c], [simulated], "STRUCTURAL_PASS"),
        ("04_simulated_duplicate_shortage", [a, b], [simulated], "NEEDS_QUESTIONS"),
        ("05_changed_version_rejects_old_review", [changed, b, c], [simulated], "UNRESOLVED"),
    ]
    folder = Path(__file__).resolve().parents[4] / "outputs/similarity_demo"
    folder.mkdir(parents=True, exist_ok=True)
    summary = dict(mode="DEVELOPMENT_MOCK_BANK", real_quality_acceptance=False,
                   human_decisions_are_simulated=True, cases=[])
    for name, bank, decisions, expected in cases:
        result = assemble_with_similarity(req, bank, decisions=decisions)
        assert result["status"] == expected, result
        result.update(mode="DEVELOPMENT_MOCK_BANK", real_quality_acceptance=False, human_decisions_are_simulated=True)
        if result["status"] == "NEEDS_QUESTIONS":
            result["replenishment_request"] = propose_replenishment(req, bank,
                forbidden_pairs={frozenset(p) for p in result["confirmed_duplicate_pairs"]})
        case_dir = folder / name
        case_dir.mkdir(exist_ok=True)
        for key in ("similarity_review_packet", "similarity_decisions_template", "replenishment_request"):
            if key in result:
                (case_dir / f"{key}.json").write_text(json.dumps(result[key], ensure_ascii=False, indent=2), encoding="utf-8")
        (case_dir / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["cases"].append(dict(name=name, status=result["status"], report=str(case_dir / "report.json")))
    pair_examples = [
        dict(case="changed_numbers", left=a, right=b, expected="SUSPECTED_DUPLICATE"),
        dict(case="option_reorder", left=a, right=shuffle, expected="CONFIRMED_DUPLICATE"),
        dict(case="same_topic_distinct_task", left=a, right=c, expected="NO_LEXICAL_FLAG"),
        dict(case="similar_wording", left=question("TEST_ONLY_d", "使用顺序栈存放元素时，哪一项描述了栈的操作规则？"),
             right=question("TEST_ONLY_e", "采用顺序栈存放元素时，下面哪项描述了栈的操作规则？"), expected="SUSPECTED_DUPLICATE"),
        dict(case="negation", left=question("TEST_ONLY_f", "下列关于顺序栈操作和存储特点的描述中，正确的是哪一项？"),
             right=question("TEST_ONLY_g", "下列关于顺序栈操作和存储特点的描述中，不正确的是哪一项？"), expected="SUSPECTED_DUPLICATE"),
    ]
    for item in pair_examples:
        item["actual"] = inspect_pair(item["left"], item["right"])
        assert item["actual"]["classification"] == item["expected"]
    (folder / "pair_cases.json").write_text(json.dumps(dict(mode="SYNTHETIC_TEST_EXPECTATIONS", cases=pair_examples),
                                                                  ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
