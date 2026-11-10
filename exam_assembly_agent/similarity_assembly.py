"""Production selection followed by lexical flags and content-bound human review."""
from .assembly import select_questions, stem_key, validate_selection
from .main import assemble_exam
from .similarity import decisions_template, inspect_pair, review_packet, screen, validate_human_decisions


def withhold_exam(result):
    result.pop("student_exam", None)
    result.pop("answer_key", None)
    if "validation" in result:
        result["validation"]["checks"]["similarity_review_complete"] = False
        result["validation"]["passed"] = False
    return result


def assemble_with_similarity(request, questions, *, decisions=None):
    result = assemble_exam(request, questions)
    if result["status"] == "INVALID_REQUEST":
        return result
    excluded = {item["index"] for item in result.get("excluded_questions", [])}
    candidates = [q for i, q in enumerate(questions) if i not in excluded]
    by_id = {q["question_id"]: q for q in candidates}
    accepted, errors = validate_human_decisions(candidates, decisions or [])
    forbidden = {frozenset(d["question_ids"]) for d in accepted.values() if d["verdict"] == "DUPLICATE"}
    result["confirmed_duplicate_pairs"] = [sorted(pair) for pair in sorted(forbidden, key=lambda p: sorted(p))]
    result["accepted_similarity_decisions"] = list(accepted.values())
    initial = [by_id[qid] for qid in result.get("initial_question_ids", [])]
    result["initial_similarity_screen"] = screen(initial)
    if errors:
        result.update(status="UNRESOLVED", message="复核结论缺失有效依据或内容已变化，请基于当前题目重新复核。",
                      similarity_review=dict(status="INVALID_OR_STALE_DECISIONS", errors=errors))
        return withhold_exam(result)
    if result["status"] != "STRUCTURAL_PASS":
        return result
    selected = [{**by_id[q["question_id"]]} for q in result["student_exam"]]
    # Recover quota assignments for multi-label records using an independent re-selection.
    selected_ids = {q["question_id"] for q in selected}
    selected, trace = select_questions(request, [q for q in candidates if q["question_id"] in selected_ids])
    if selected is None:
        result.update(status="UNRESOLVED", message="无法重建选题分配", similarity_search=trace)
        return withhold_exam(result)
    history = result.setdefault("repair_history", [])
    while True:
        audit = screen(selected)
        selected_by_id = {q["question_id"]: q for q in selected}
        confirmed = [p for p in audit["flagged_pairs"] if p["classification"] == "CONFIRMED_DUPLICATE"]
        for pair in forbidden:
            if pair <= selected_by_id.keys():
                a, b = sorted(pair)
                confirmed.append({**inspect_pair(selected_by_id[a], selected_by_id[b]), "classification": "HUMAN_CONFIRMED_DUPLICATE"})
        if confirmed:
            result["similarity_review"] = {**audit, "status": "CONFIRMED_DUPLICATES", "duplicate_pairs": confirmed}
            if len(history) >= request.get("max_repair_rounds", 3):
                result.update(status="UNRESOLVED", message="已达到换题轮数上限，未输出试卷。")
                break
            replacement, repair_trace = select_questions(request, candidates, unique_stems=True, forbidden_pairs=forbidden)
            event = dict(round=len(history)+1, action="RESELECT_WITH_CONFIRMED_PAIR_CONSTRAINTS",
                         conflicts=confirmed, search=repair_trace)
            history.append(event)
            if replacement is None:
                result.update(status="UNRESOLVED" if repair_trace["budget_exhausted"] else "NEEDS_QUESTIONS",
                              message="现有候选池无法避开已确认重复题对，或搜索预算耗尽。")
                event["outcome"] = "BUDGET_EXHAUSTED" if repair_trace["budget_exhausted"] else "NO_FEASIBLE_REPLACEMENT"
                break
            event.update(outcome="REVALIDATE", removed_question_ids=sorted(set(selected_by_id)-{q["question_id"] for q in replacement}),
                         added_question_ids=sorted({q["question_id"] for q in replacement}-set(selected_by_id)))
            selected = replacement
            continue
        pending = [p for p in audit["flagged_pairs"] if p["classification"] == "SUSPECTED_DUPLICATE"
                   and accepted.get(p["pair_id"], {}).get("verdict") != "DISTINCT"]
        result["similarity_review"] = {**audit, "status": "NEEDS_REVIEW" if pending else "NO_PENDING_LEXICAL_FLAGS",
                                       "pending_pair_count": len(pending)}
        if pending:
            result.update(status="UNRESOLVED", message="发现疑似重复题对，等待人工复核；尚未生成完整试卷。",
                          similarity_review_packet=review_packet(selected, pending),
                          similarity_decisions_template=decisions_template(pending))
            break
        validation = validate_selection(request, selected)
        validation["checks"].update(unique_stems=len({stem_key(q["stem"]) for q in selected}) == len(selected),
                                    confirmed_duplicate_pairs_absent=True, no_pending_lexical_flags=True)
        validation["passed"] = all(validation["checks"].values())
        validation["semantic_checks"] = "LEXICAL_SCREEN_AND_SUPPLIED_HUMAN_DECISIONS_ONLY"
        result["validation"] = validation
        result["student_exam"] = [{k: q[k] for k in ("question_id", "score", "stem", "options")} for q in selected]
        result["answer_key"] = [{k: q[k] for k in ("question_id", "answer", "explanation")} for q in selected]
        result["status"] = "STRUCTURAL_PASS" if validation["passed"] else "UNRESOLVED"
        if result["status"] == "STRUCTURAL_PASS":
            return result
        break
    return withhold_exam(result)
