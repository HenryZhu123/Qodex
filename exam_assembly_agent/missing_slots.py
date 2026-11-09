"""将重复题冲突转成可交给命题/审校模块的补题建议。"""
from collections import Counter


def build_duplicate_replenishment(request, selected, conflicts):
    by_id = {q["question_id"]: q for q in selected}
    # 每组保留首题，其余题按原来的主知识点、难度和分值补齐。
    # 这是固定保留方案的建议，不声称是整个候选池的全局最少补题数。
    replace_ids = [qid for group in conflicts for qid in group["question_ids"][1:]]
    kept = [q for q in selected if q["question_id"] not in set(replace_ids)]
    counts = Counter((by_id[qid]["topic"], by_id[qid]["difficulty"], by_id[qid]["score"])
                     for qid in replace_ids)
    slots = [{"slot_id": f"slot_{i}", "subject": request["subject"],
              "question_type": request["question_type"], "topic": topic,
              "difficulty": difficulty, "score_per_question": score, "count": count}
             for i, ((topic, difficulty, score), count) in enumerate(counts.items(), 1)]
    return {
        "request_id": request.get("request_id"),
        "reason": "DUPLICATE_STEMS_NO_REPLACEMENT",
        "plan_status": "PROPOSED_NOT_EXECUTED",
        "suggested_additional_count": len(replace_ids),
        "count_basis": "保留当前候选卷每组重复题中的第一题，为其余位置补题；不是全局最小值证明。",
        "keep_question_ids": [q["question_id"] for q in kept],
        "replace_question_ids": replace_ids,
        "slots": slots,
        "avoid_stems": list(dict.fromkeys(q["stem"] for q in selected)),
        "requirements": {
            "new_unique_ids": True,
            "mutually_distinct_stems": True,
            "review_status": "PASS",
            "review_must_match_version": True,
            "student_content_separate_from_answers": True,
        },
        "next_action": "REQUEST_GENERATION_THEN_INDEPENDENT_REVIEW",
        "resume_action": "REASSEMBLE_AND_VALIDATE_WHOLE_EXAM",
        "note": "不调用命题或审校服务，不伪造通过状态。新题符合槽位及不重复要求后，仍需独立审校并重新验证整卷。",
    }
