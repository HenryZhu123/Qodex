"""Generate a bounded candidate pool and allocate distinct questions to slots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from random import Random
from unicodedata import normalize

from .generation import SCHEMA_VERSION, failure_result, generate_question

MAX_QUESTIONS = 100
ATTEMPTS_PER_QUESTION = 8
METADATA_FIELDS = ("subject", "topic", "question_type")
BATCH_FIELDS = {"schema_version", "request_id", "seed", "question_count", "total_score", "slots"}
SLOT_FIELDS = {"slot_id", "count", "score_per_question", *METADATA_FIELDS}
REFERENCE_FIELDS = {"reference_id", "stem", "source", "license"}
TERMINAL_STATUSES = {"INVALID_REQUEST", "UNSUPPORTED_REQUEST", "NEEDS_MATERIAL", "KNOWLEDGE_BASE_UNAVAILABLE"}


@dataclass
class SlotSample:
    candidates: dict[str, dict]
    attempts: int
    failure: dict | None
    blocked_attempts: int
    matched_references: dict[str, dict]


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate(payload: object) -> None:
    if (
        not isinstance(payload, dict)
        or not BATCH_FIELDS <= payload.keys()
        or payload.keys() - BATCH_FIELDS - {"reference_questions"}
    ):
        raise ValueError("批量请求必须包含 schema_version、request_id、seed、question_count、total_score 和 slots。")
    if payload["schema_version"] != SCHEMA_VERSION or not _is_text(payload["request_id"]):
        raise ValueError("schema_version 必须为 0.1，request_id 须为非空字符串。")
    seed = payload["seed"]
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed 必须是 0 至 4294967295 的整数。")
    count = payload["question_count"]
    if type(count) is not int or not 1 <= count <= MAX_QUESTIONS:
        raise ValueError(f"question_count 必须是 1 至 {MAX_QUESTIONS} 的整数。")
    score = payload["total_score"]
    if type(score) is not int or score < 1:
        raise ValueError("total_score 必须是正整数。")
    slots = payload["slots"]
    if not isinstance(slots, list) or not 1 <= len(slots) <= count:
        raise ValueError("slots 必须是非空数组，槽位数不能超过题量。")

    seen = set()
    for slot in slots:
        if (
            not isinstance(slot, dict)
            or not SLOT_FIELDS <= slot.keys()
            or slot.keys() - SLOT_FIELDS - {"constraints", "evidence"}
        ):
            raise ValueError("槽位必须提供 slot_id、count、score_per_question、subject、topic 和 question_type。")
        if not all(_is_text(slot[key]) for key in ("slot_id", *METADATA_FIELDS)):
            raise ValueError("槽位 ID、科目、考点和题型必须是非空字符串。")
        if slot["slot_id"] in seen:
            raise ValueError("slot_id 在同一批次内必须唯一。")
        seen.add(slot["slot_id"])
        if any(type(slot[key]) is not int or slot[key] < 1 for key in ("count", "score_per_question")):
            raise ValueError("槽位题量和每题分值必须是正整数。")
    if sum(slot["count"] for slot in slots) != count:
        raise ValueError("各槽位题量之和必须等于 question_count。")
    if sum(slot["count"] * slot["score_per_question"] for slot in slots) != score:
        raise ValueError("各槽位分值之和必须等于 total_score。")


def _stem_key(stem: str) -> str:
    return " ".join(normalize("NFKC", stem).split())


def _reference_index(references: object) -> dict[str, list[dict]]:
    if not isinstance(references, list):
        raise ValueError("reference_questions 必须是参考题数组。")
    index = {}
    seen = set()
    for reference in references:
        if (
            not isinstance(reference, dict)
            or reference.keys() != REFERENCE_FIELDS
            or not all(_is_text(value) for value in reference.values())
        ):
            raise ValueError("每道参考题必须提供 reference_id、stem、source 和 license。")
        reference_id = reference["reference_id"]
        if reference_id in seen:
            raise ValueError("reference_id 在同一批次内必须唯一。")
        seen.add(reference_id)
        ref = {key: reference[key] for key in ("reference_id", "source", "license")}
        index.setdefault(_stem_key(reference["stem"]), []).append(ref)
    return index


def _matches(question: dict, slot: dict) -> bool:
    metadata = question["metadata"]
    if any(metadata.get(key) != slot[key] for key in METADATA_FIELDS):
        return False
    score = metadata.get("score", slot["score_per_question"])
    return type(score) is int and score == slot["score_per_question"]


def _sample_slot(
    slot: dict, request_id: str, index: int, rng: Random, reference_index: dict[str, list[dict]],
    single_generator: Callable[[object], dict],
) -> SlotSample:
    base = {key: slot[key] for key in (*METADATA_FIELDS, "constraints", "evidence") if key in slot}
    candidates = {}
    last_failure = None
    blocked_attempts = 0
    matched_references = {}
    for attempt in range(1, ATTEMPTS_PER_QUESTION * slot["count"] + 1):
        result = single_generator({
            **base,
            "schema_version": SCHEMA_VERSION,
            "request_id": f"{request_id}/batch/{index}/{attempt}",
            "seed": rng.randrange(2**32),
        })
        status = result["status"]
        if status != "GENERATED":
            last_failure = {"code": status, "message": result["message"]}
            if "missing_rules" in result:
                last_failure["missing_rules"] = result["missing_rules"]
            if status in TERMINAL_STATUSES:
                break
            continue
        questions = result["questions"]
        if len(questions) != 1 or not _matches(questions[0], slot):
            last_failure = {"code": "SLOT_MISMATCH", "message": "候选题与槽位的题量、科目、考点、题型或分值不符。"}
            continue
        question = questions[0]
        if question["self_check"]["status"] != "PASSED":
            last_failure = {"code": "SELF_CHECK_FAILED", "message": "候选题未通过自检。"}
            continue
        key = _stem_key(question["student_view"]["stem"])
        refs = reference_index.get(key)
        if refs:
            blocked_attempts += 1
            matched_references.update((ref["reference_id"], ref) for ref in refs)
            continue
        candidates.setdefault(key, question)
    return SlotSample(candidates, attempt, last_failure, blocked_attempts, matched_references)


def _allocate(slots: list[dict], pools: list[dict]) -> dict[str, int]:
    owners = {}

    def assign(slot_index: int, visited: set[str]) -> bool:
        # Move an already assigned question only if its current slot can
        # take a different question, preserving that slot's filled count.
        for key in pools[slot_index]:
            owner = owners.get(key)
            if key in visited or owner == slot_index:
                continue
            visited.add(key)
            if owner is None or assign(owner, visited):
                owners[key] = slot_index
                return True
        return False

    for index, slot in enumerate(slots):
        for _ in range(slot["count"]):
            if not assign(index, set()):
                break
    return owners


def generate_batch(
    payload: object, *, single_generator: Callable[[object], dict] | None = None,
    reserved_stems: tuple[str, ...] = (),
) -> dict:
    """Fill a batch of scored slots using self-checked single questions."""
    try:
        _validate(payload)
        reference_index = _reference_index(payload.get("reference_questions", []))
    except ValueError as error:
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        return failure_result("INVALID_REQUEST", str(error), request_id if _is_text(request_id) else None)

    request_id = payload["request_id"]
    for index, stem in enumerate(reserved_stems, 1):
        reference_index.setdefault(_stem_key(stem), []).append({
            "reference_id": f"reserved-stem-{index}",
            "source": request_id,
        })
    slots = payload["slots"]
    rng = Random(payload["seed"])
    generator = single_generator if single_generator is not None else generate_question
    samples = [_sample_slot(slot, request_id, index, rng, reference_index, generator)
               for index, slot in enumerate(slots)]
    owners = _allocate(slots, [sample.candidates for sample in samples])
    questions = []
    deficits = []
    reference_matches = []
    for index, (slot, sample) in enumerate(zip(slots, samples)):
        candidates = sample.candidates
        failure = sample.failure
        selected = [question for key, question in candidates.items() if owners.get(key) == index]
        score = slot["score_per_question"]
        questions.extend({
            **question,
            "slot_id": slot["slot_id"],
            "metadata": {**question["metadata"], "score": score},
        } for question in selected)
        if sample.blocked_attempts:
            reference_matches.append({
                "slot_id": slot["slot_id"],
                "blocked_attempts": sample.blocked_attempts,
                "references": list(sample.matched_references.values()),
            })
        missing = slot["count"] - len(selected)
        if missing:
            reason = {
                "code": "INSUFFICIENT_UNIQUE_CANDIDATES",
                "message": "在本次尝试预算内，去重后可分配给该槽位的合格题不足。",
            }
            if sample.blocked_attempts:
                reason = {
                    "code": "REFERENCE_DUPLICATE",
                    "message": "部分候选与参考题题干重复，剩余合格题未填满槽位。",
                    "reference_ids": list(sample.matched_references),
                }
            elif not candidates and failure is not None:
                reason = failure
            if failure is not None and reason is not failure:
                reason["last_candidate_failure"] = failure
            deficits.append({
                **{key: slot[key] for key in ("slot_id", *METADATA_FIELDS, "score_per_question")},
                "requested_count": slot["count"],
                "generated_count": len(selected),
                "missing_count": missing,
                "attempts": sample.attempts,
                "unique_candidate_count": len(candidates),
                "reason": reason,
            })

    status = "GENERATED"
    if deficits:
        status = "PARTIAL" if questions else "NO_QUESTIONS"
    result = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "status": status,
        "requested_count": payload["question_count"],
        "generated_count": len(questions),
        "requested_score": payload["total_score"],
        "generated_score": sum(question["metadata"]["score"] for question in questions),
        "questions": questions,
        "deficits": deficits,
    }
    if "reference_questions" in payload or reserved_stems:
        result["reference_matches"] = reference_matches
    return result
