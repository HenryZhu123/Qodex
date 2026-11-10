"""离线补题恢复演示：不调用命题/审校，不连接数据库。"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from .main import assemble_exam
from .question_bank import load_questions


def run_demo(output_dir):
    output_dir = Path(output_dir)
    # 避免旧成功文件留在本次失败目录，让每次演示有独立快照。
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("演示输出目录已有内容，请选择新的空目录")
    root = Path(__file__).parent / "examples"
    request = json.loads((root / "repair_request.json").read_text(encoding="utf-8"))
    bank = load_questions(root / "repair_no_alternative_bank.json")
    initial = assemble_exam(request, bank)
    plan = initial["replenishment_request"]

    # 固定开发样例模拟命题输出；不是自动生成，也不是真实审校结论。
    new_question = json.loads((root / "question.json").read_text(encoding="utf-8"))
    new_question["question_id"] = "MOCK_NEW_STACK_001"
    new_question["source"] = "固定离线补题演示样例，非命题服务输出"
    new_question["review"] = {"status": "NOT_REVIEWED", "question_version": 1,
                              "is_mock": True, "note": "开发演示：尚未审校"}
    pending_bank = bank + [deepcopy(new_question)]
    pending = assemble_exam(request, pending_bank)

    # 模拟上游返回独立审校结果；此处只构造 fixture，不执行真实审校。
    reviewed = deepcopy(new_question)
    reviewed["review"].update(status="PASS", note="模拟上游审校通过 fixture；未经真实审校")
    reviewed_bank = bank + [reviewed]
    resumed = assemble_exam(request, reviewed_bank)

    # 内容版本变化，但审校仍指向旧版本，必须不能通过。
    stale = deepcopy(reviewed)
    stale["version"] = 2
    stale["stem"] += "（版本变更演示）"
    stale_bank = bank + [stale]
    stale_result = assemble_exam(request, stale_bank)

    checks = {
        "initial_requests_replenishment": initial["status"] == "NEEDS_QUESTIONS",
        "pending_question_excluded": any(x["question_id"] == new_question["question_id"]
                                          for x in pending.get("excluded_questions", [])),
        "pending_no_final_exam": pending["status"] == "NEEDS_QUESTIONS" and "student_exam" not in pending,
        "reviewed_resume_passes": resumed["status"] == "STRUCTURAL_PASS",
        "resumed_whole_exam_revalidated": all(resumed.get("validation", {}).get("checks", {}).values())
                                           and bool(resumed.get("validation", {}).get("checks")),
        "new_question_selected": any(q["question_id"] == reviewed["question_id"]
                                      for q in resumed.get("student_exam", [])),
        "stale_review_excluded": stale_result["status"] == "NEEDS_QUESTIONS"
                                 and "student_exam" not in stale_result,
    }
    summary = {"mode": "OFFLINE_MOCK_DEMO", "passed": all(checks.values()), "checks": checks,
               "statuses": {"initial": initial["status"], "pending": pending["status"],
                            "reviewed": resumed["status"], "stale": stale_result["status"]},
               "note": "全部题目使用模拟审校。本演示验证组卷流程，不能证明题目质量或真实服务可用。"}

    output_dir.mkdir(parents=True, exist_ok=True)
    def save(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    save(output_dir / "replenishment_request.json", plan)
    for name, input_bank, result in (("01_initial", bank, initial),
                                      ("02_pending_review", pending_bank, pending),
                                      ("03_mock_review_passed", reviewed_bank, resumed),
                                      ("04_stale_review", stale_bank, stale_result)):
        folder = output_dir / name
        folder.mkdir()
        save(folder / "request.json", request)
        save(folder / "input_bank.json", input_bank)
        save(folder / "report.json", result)
        for key in ("student_exam", "answer_key"):
            if key in result:
                save(folder / f"{key}.json", result[key])
    save(output_dir / "summary.json", summary)
    return summary


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = run_demo(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
