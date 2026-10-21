"""小规模教学版：有搜索预算的回溯选题，以及独立的结构约束复核。"""
from collections import Counter
import unicodedata


def stem_key(text):
    # 仅统一 Unicode 全半角和空白，保留标点、数字、字母大小写，避免改变公式含义。
    return " ".join(unicodedata.normalize("NFKC", text).split())


def find_duplicate_stems(questions):
    groups = {}
    for q in questions:
        groups.setdefault(stem_key(q["stem"]), []).append(q["question_id"])
    return [{"check": "duplicate_stem", "question_ids": ids}
            for ids in groups.values() if len(ids) > 1]


def select_questions(request, candidates, max_nodes=50000, unique_stems=False):
    topics = request["topic_counts"].copy()
    levels = request["difficulty_counts"].copy()
    selected = []
    nodes = 0
    exhausted = False

    def search(start):
        nonlocal nodes, exhausted
        if nodes >= max_nodes:
            exhausted = True
            return None
        nodes += 1
        if len(selected) == request["question_count"]:
            return selected.copy() if not any(topics.values()) and not any(levels.values()) else None
        remaining = candidates[start:]
        if len(remaining) < request["question_count"] - len(selected):
            return None
        for field, quotas in (("topic", topics), ("difficulty", levels)):
            available = Counter(q[field] for q in remaining)
            if any(available[k] < count for k, count in quotas.items()):
                return None
        for i in range(start, len(candidates)):
            q = candidates[i]
            topic, level = q["topic"], q["difficulty"]
            if topics[topic] <= 0 or levels[level] <= 0:
                continue
            if unique_stems and any(stem_key(q["stem"]) == stem_key(old["stem"]) for old in selected):
                continue
            topics[topic] -= 1
            levels[level] -= 1
            selected.append(q)
            result = search(i + 1)
            selected.pop()
            topics[topic] += 1
            levels[level] += 1
            if result is not None:
                return result
            if exhausted:
                break
        return None

    result = search(0)
    return result, {"search_nodes": nodes, "budget_exhausted": exhausted, "max_nodes": max_nodes}


def validate_selection(request, questions):
    """不依赖搜索中的计数器，重新核算选题结果。不包含语义质量验证。"""
    topics = Counter(q["topic"] for q in questions)
    levels = Counter(q["difficulty"] for q in questions)
    checks = {
        "question_count": len(questions) == request["question_count"],
        "total_score": sum(q["score"] for q in questions) == request["total_score"],
        "unique_ids": len({q["question_id"] for q in questions}) == len(questions),
        "topic_counts": topics == Counter(request["topic_counts"]),
        "difficulty_counts": levels == Counter(request["difficulty_counts"]),
        "subject_and_type": all(q["subject"] == request["subject"] and
                                q["question_type"] == request["question_type"] for q in questions),
        "individual_scores": all(q["score"] == request["score_per_question"] for q in questions),
        "current_reviews": all(q["review"]["status"] == "PASS" and
                               q["review"]["question_version"] == q["version"] and
                               (q["review"]["is_mock"] is False or request.get("allow_mock_reviews", False))
                               for q in questions),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "actual_total_score": sum(q["score"] for q in questions),
            "actual_topic_counts": dict(topics), "actual_difficulty_counts": dict(levels),
            "semantic_checks": "NOT_IMPLEMENTED"}
