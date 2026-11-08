"""Explainable lexical screening. A high score is a review flag, never a semantic verdict."""
from difflib import SequenceMatcher
import hashlib
from itertools import combinations
import json
import re

from .assembly import stem_key
from .semantic_review import content_fingerprint, evaluate_decisions


POLICY_VERSION = "lexical-v1"
NUMBER = re.compile(r"\d+(?:\.\d+)?")
MAX_SCREEN_CHARS = 2000


def inspect_pair(left, right):
    left, right = sorted((left, right), key=lambda q: q["question_id"])
    a, b = stem_key(left["stem"]), stem_key(right["stem"])
    too_long = max(len(a), len(b)) > MAX_SCREEN_CHARS
    score = 1.0 if a == b else None if too_long else SequenceMatcher(None, a, b, autojunk=False).ratio()
    a_options = [stem_key(v) for v in left.get("options", {}).values()]
    b_options = [stem_key(v) for v in right.get("options", {}).values()]
    option_overlap = len(set(a_options) & set(b_options)) / max(1, len(set(a_options) | set(b_options)))
    numbers_a, numbers_b = NUMBER.findall(a), NUMBER.findall(b)
    reasons = []
    if a == b:
        reasons.append("SAME_STEM_POLICY")
        if sorted(a_options) == sorted(b_options) and a_options != b_options:
            reasons.append("OPTION_ORDER_CHANGED")
        verdict = "CONFIRMED_DUPLICATE"
    else:
        if too_long:
            reasons.append("TEXT_EXCEEDS_LEXICAL_SCREEN_LIMIT")
        if (min(len(a), len(b)) >= 12 and numbers_a and numbers_b and numbers_a != numbers_b
                and NUMBER.sub("<NUMBER>", a) == NUMBER.sub("<NUMBER>", b)):
            reasons.append("SAME_TEXT_TEMPLATE_CHANGED_NUMBERS")
        if score is not None and min(len(a), len(b)) >= 12 and score >= 0.86 and option_overlap >= 0.5:
            reasons.append("HIGH_TEXT_AND_OPTION_OVERLAP")
        if score is not None and min(len(a), len(b)) >= 18 and score >= 0.95:
            reasons.append("VERY_HIGH_TEXT_OVERLAP")
        if score is not None and min(len(a), len(b)) >= 12 and score >= 0.65 and option_overlap >= 0.75:
            reasons.append("SHARED_OPTIONS_AND_SIMILAR_WORDING")
        verdict = "SUSPECTED_DUPLICATE" if reasons else "NO_LEXICAL_FLAG"
    ids = [left["question_id"], right["question_id"]]
    pid = hashlib.sha256(json.dumps(ids, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
    return dict(pair_id=pid, question_ids=ids, content_hashes=[content_fingerprint(left), content_fingerprint(right)],
                classification=verdict, reasons=reasons,
                evidence=dict(text_similarity=round(score, 6) if score is not None else None,
                              option_overlap=round(option_overlap, 6), numeric_tokens=[numbers_a, numbers_b],
                              text_lengths=[len(a), len(b)], max_screen_chars=MAX_SCREEN_CHARS), policy_version=POLICY_VERSION)


def screen(questions):
    pairs = [inspect_pair(a, b) for a, b in combinations(questions, 2)]
    flagged = [p for p in pairs if p["classification"] != "NO_LEXICAL_FLAG"]
    return dict(policy_version=POLICY_VERSION, method="ALL_SELECTED_PAIRS_LEXICAL_SCREEN",
                pair_count=len(pairs), flagged_pairs=flagged,
                semantic_quality_certified=False,
                note="字面线索仅用于筛查，可能漏掉改写题或标记正常题；同知识点或同答案本身不构成重复证据。未检测跨题提示。")


def validate_human_decisions(candidates, decisions):
    by_id = {q["question_id"]: q for q in candidates}
    pairs, errors = [], []
    for decision in decisions:
        ids = decision.get("question_ids", []) if isinstance(decision, dict) else []
        if (not isinstance(ids, list) or len(ids) != 2 or any(not isinstance(qid, str) for qid in ids) or len(set(ids)) != 2
                or any(qid not in by_id for qid in ids)):
            errors.append("复核记录引用未知、失效或重复的题号")
            continue
        pair = inspect_pair(by_id[ids[0]], by_id[ids[1]])
        if ids != pair["question_ids"] or decision.get("pair_id") != pair["pair_id"]:
            errors.append("复核记录的题对编号或题号顺序不匹配")
        pairs.append(pair)
    # Deduplicate packet rows, while evaluate_decisions rejects duplicate decisions.
    packet = dict(pairs=list({p["pair_id"]: p for p in pairs}.values()), pair_count=len(pairs))
    result = evaluate_decisions(packet, decisions)
    errors.extend(result["errors"])
    return {d["pair_id"]: d for d in result["accepted_decisions"]}, errors


def review_packet(questions, pending):
    return dict(policy_version=POLICY_VERSION, audience="TEACHER_ONLY", contains_answers=True,
                question_count=len(questions), pair_count=len(pending),
                questions=questions, pairs=pending,
                criteria="比较考查目标、条件和推理任务；仅同知识点不是重复。填写 DISTINCT、DUPLICATE 或 UNRESOLVED，并说明理由。",
                note="人工结论会与当前内容指纹核对；source=human 是调用方声明，不构成人员身份认证。")


def decisions_template(pending):
    return [dict(pair_id=p["pair_id"], question_ids=p["question_ids"], content_hashes=p["content_hashes"],
                 source="human", reviewer="", verdict="UNRESOLVED", reason="") for p in pending]
