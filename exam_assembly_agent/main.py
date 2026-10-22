"""第二步：读取、检查需求、筛选候选题和统计缺口。仅使用 Python 标准库。"""

import argparse
import sys
from collections import Counter
import json
from pathlib import Path

if __package__:
    from .question_bank import load_questions
    from .assembly import select_questions, validate_selection, find_duplicate_stems
    from .missing_slots import build_duplicate_replenishment
    from .exam_export import export_exam
else:
    from question_bank import load_questions
    from assembly import select_questions, validate_selection, find_duplicate_stems
    from missing_slots import build_duplicate_replenishment
    from exam_export import export_exam


def validate_request(request):
    """先检查用户要求本身是否自洽。"""
    errors = []
    rounds = request.get("max_repair_rounds", 3)
    if type(rounds) is not int or rounds < 0 or rounds > 10:
        errors.append("max_repair_rounds 必须为 0 到 10 的整数")
    for field in ("question_count", "score_per_question", "total_score"):
        value = request.get(field)
        if type(value) is not int or value <= 0:
            errors.append(f"{field} 必须是正整数")
    for field in ("subject", "question_type"):
        if not isinstance(request.get(field), str) or not request[field].strip():
            errors.append(f"{field} 必须是非空字符串")
    if "allow_mock_reviews" in request and type(request["allow_mock_reviews"]) is not bool:
        errors.append("allow_mock_reviews 必须为 true 或 false")
    for field in ("topic_counts", "difficulty_counts"):
        counts = request.get(field)
        if not isinstance(counts, dict) or not counts:
            errors.append(f"{field} 必须是非空对象")
            continue
        if any(not isinstance(k, str) or not k.strip() or type(v) is not int or v < 0
               for k, v in counts.items()):
            errors.append(f"{field} 的名称必须非空，题数必须是非负整数")
        elif sum(counts.values()) != request.get("question_count"):
            errors.append(f"{field} 的题数之和必须等于 question_count")
    if not errors and request["question_count"] * request["score_per_question"] != request["total_score"]:
        errors.append("题数乘以每题分值必须等于总分")
    return errors


def inspect_candidates(request, questions):
    """本阶段只检查候选池，不将候选充足误认为已经完成组卷。"""
    errors = validate_request(request)
    if errors:
        return {"request_id": request.get("request_id"), "status": "INVALID_REQUEST", "errors": errors}

    eligible, excluded, seen = [], [], set()
    for index, question in enumerate(questions):
        reasons = []
        question_id = question.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            reasons.append("题目缺少有效编号")
        elif question_id in seen:
            reasons.append("题目编号重复，请为每个编号提供唯一版本")
        if isinstance(question_id, str) and question_id:
            seen.add(question_id)
        review = question.get("review", {})
        if not isinstance(review, dict):
            review = {}
        for field in ("subject", "question_type"):
            if question.get(field) != request[field]:
                reasons.append(f"{field} 不匹配")
        if question.get("score") != request["score_per_question"]:
            reasons.append("分值不匹配")
        options = question.get("options")
        if (not isinstance(question.get("stem"), str) or not question["stem"].strip()
                or not isinstance(options, dict) or set(options) != {"A", "B", "C", "D"}
                or any(not isinstance(v, str) or not v.strip() for v in options.values())
                or not isinstance(question.get("answer"), str)
                or question.get("answer") not in options
                or not isinstance(question.get("explanation"), str)):
            reasons.append("单选题内容、选项、答案或解析不完整")
        if question.get("topic") not in request["topic_counts"]:
            reasons.append("知识点不在要求范围")
        if question.get("difficulty") not in request["difficulty_counts"]:
            reasons.append("难度不在要求范围")
        version = question.get("version")
        valid_version = (type(version) is int and version > 0) or (isinstance(version, str) and bool(version.strip()))
        if not valid_version or review.get("question_version") != version:
            reasons.append("缺少有效版本或审校版本已失效")
        if review.get("status") != "PASS":
            reasons.append("审校未通过")
        if type(review.get("is_mock")) is not bool:
            reasons.append("审校记录未明确是否为模拟数据")
        elif review["is_mock"] and not request.get("allow_mock_reviews", False):
            reasons.append("当前要求禁止模拟审校记录")
        if reasons:
            excluded.append({"index": index, "question_id": question_id, "reasons": reasons})
        else:
            eligible.append(question)

    topic_counts = Counter(q["topic"] for q in eligible)
    difficulty_counts = Counter(q["difficulty"] for q in eligible)
    topic_deficits = {k: max(0, v - topic_counts[k]) for k, v in request["topic_counts"].items()}
    difficulty_deficits = {k: max(0, v - difficulty_counts[k]) for k, v in request["difficulty_counts"].items()}
    shortage = (len(eligible) < request["question_count"]
                or any(topic_deficits.values()) or any(difficulty_deficits.values()))
    return {
        "request_id": request.get("request_id"),
        "status": "NEEDS_QUESTIONS" if shortage else "READY_FOR_SELECTION",
        "eligible_candidate_count": len(eligible),
        "eligible_question_ids": [q["question_id"] for q in eligible],
        "uses_mock_reviews": any(q["review"]["is_mock"] for q in eligible),
        "topic_deficits": topic_deficits,
        "difficulty_deficits": difficulty_deficits,
        "excluded_questions": excluded,
        "note": "各维度缺口不能相加。候选数充足也不保证知识点和难度能同时满足；下一步需要联合选题。",
    }


def assemble_exam(request, questions):
    report = inspect_candidates(request, questions)
    if report["status"] != "READY_FOR_SELECTION":
        return report
    excluded = {item["index"] for item in report["excluded_questions"]}
    candidates = [q for i, q in enumerate(questions) if i not in excluded]
    selected, trace = select_questions(request, candidates)
    report["selection_trace"] = trace
    if selected is None:
        report["status"] = "INCOMPLETE" if trace["budget_exhausted"] else "NEEDS_QUESTIONS"
        report["message"] = ("搜索预算耗尽，尚不能判断是否有可行组合。" if trace["budget_exhausted"]
                             else "候选数量充足，但知识点和难度配额无法同时满足。")
        return report
    report["repair_history"] = []
    report["initial_question_ids"] = [q["question_id"] for q in selected]
    for repair_round in range(request.get("max_repair_rounds", 3) + 1):
        validation = validate_selection(request, selected)
        conflicts = find_duplicate_stems(selected)
        validation["checks"]["unique_stems"] = not conflicts
        validation["passed"] = all(validation["checks"].values())
        report["validation"] = validation
        report["conflicts"] = conflicts
        if validation["passed"]:
            break
        if not conflicts:
            report.update(status="INCOMPLETE", message="结构复核失败，停止输出试卷。")
            return report
        if repair_round == request.get("max_repair_rounds", 3):
            report.update(status="INCOMPLETE", message="达到修复轮数上限，未输出最终试卷。")
            return report
        # 联合重选允许同时替换多题，避免局部换题破坏难度或知识点配额。
        repaired, repair_trace = select_questions(request, candidates, unique_stems=True)
        event = {"round": repair_round + 1, "action": "RESELECT_WITH_UNIQUE_STEMS",
                 "conflicts": conflicts, "search": repair_trace}
        report["repair_history"].append(event)
        if repaired is None:
            event["outcome"] = "BUDGET_EXHAUSTED" if repair_trace["budget_exhausted"] else "NO_FEASIBLE_REPLACEMENT"
            report.update(status="INCOMPLETE" if repair_trace["budget_exhausted"] else "NEEDS_QUESTIONS",
                          message="修复搜索预算耗尽，不能断言无解。" if repair_trace["budget_exhausted"] else
                          "现有候选题无法同时满足配额和题干不重复要求，需要补充不同题干的候选题。")
            if not repair_trace["budget_exhausted"]:
                report["replenishment_request"] = build_duplicate_replenishment(request, selected, conflicts)
            return report
        old_ids = {q["question_id"] for q in selected}
        new_ids = {q["question_id"] for q in repaired}
        event.update(outcome="REVALIDATE", removed_question_ids=sorted(old_ids - new_ids),
                     added_question_ids=sorted(new_ids - old_ids))
        selected = repaired
    report["status"] = "STRUCTURAL_PASS" if validation["passed"] else "INCOMPLETE"
    report["validation"] = validation
    report["note"] = "已检查结构及相同题干，并支持有预算的联合重选修复；语义去重、跨题提示和真实审校对接尚未实现。"
    report["student_exam"] = [{k: q[k] for k in ("question_id", "score", "stem", "options")} for q in selected]
    report["answer_key"] = [{k: q[k] for k in ("question_id", "answer", "explanation")} for q in selected]
    return report


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=root / "examples/request.json")
    parser.add_argument("--bank", type=Path, default=root / "examples/question_bank.json")
    parser.add_argument("--output-dir", type=Path, help="可选：保存学生卷、答案和运行报告")
    parser.add_argument("--pdf", action="store_true", help="同时导出 PDF，需要安装 requirements-pdf.txt")
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8-sig"))
        questions = load_questions(args.bank)
        if not isinstance(request, dict):
            raise ValueError("需求必须是对象")
        result = assemble_exam(request, questions)
    except (OSError, ValueError, TypeError) as exc:
        result = {"status": "INPUT_ERROR", "message": str(exc)}
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if any(args.output_dir.iterdir()):
            raise ValueError("输出目录已有内容，请使用新目录保存同一份试卷和答案，避免混用旧文件")
        for name in ("student_exam", "answer_key", "replenishment_request"):
            if name in result:
                (args.output_dir / f"{name}.json").write_text(
                    json.dumps(result[name], ensure_ascii=False, indent=2), encoding="utf-8")
            elif (args.output_dir / f"{name}.json").exists():
                raise ValueError("输出目录包含旧试卷，请使用新的输出目录，避免混淆失败结果。")
        if result["status"] == "STRUCTURAL_PASS":
            result["artifacts"] = export_exam(request, result, args.output_dir, pdf=args.pdf)
        (args.output_dir / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": result["status"], "output_dir": str(args.output_dir)}, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
