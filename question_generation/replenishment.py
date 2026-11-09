"""Translate a v1.0 exam assembly shortage plan into a pending question batch."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json

from .batch import MAX_QUESTIONS, generate_batch
from .generation import SCHEMA_VERSION, failure_result

SUBJECTS = {
    "数据结构": "data_structures",
    "操作系统": "operating_systems",
    "计算机组成原理": "computer_organization",
    "计算机网络": "computer_networks",
}
SLOT_TEXT_FIELDS = ("subject", "knowledge_point", "question_type", "difficulty")
SLOT_NUMBER_FIELDS = ("score_per_question", "missing_count")


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _batch_request(payload: dict) -> tuple[dict, dict[str, dict], tuple[str, ...]]:
    if payload.keys() - {"replenishment_request", "seed", "slot_profiles"}:
        raise ValueError("仅接受 replenishment_request、seed 和 slot_profiles。")
    seed = payload.get("seed")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed 必须是 0 至 4294967295 的整数。")
    plan = payload.get("replenishment_request")
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != "1.0"
        or plan.get("plan_status") != "PROPOSED_NOT_EXECUTED"
        or plan.get("scope") != "CURRENT_VERIFIED_CANDIDATE_POOL"
        or not _text(plan.get("request_id"))
    ):
        raise ValueError("replenishment_request 必须是带请求 ID 的 v1.0 联合缺题建议。")
    requested_count = plan.get("suggested_additional_count")
    deficits = plan.get("deficits")
    if (
        type(requested_count) is not int or not 1 <= requested_count <= MAX_QUESTIONS
        or not isinstance(deficits, list) or not 1 <= len(deficits) <= requested_count
    ):
        raise ValueError("联合缺题建议须包含 1 至 100 道缺题。")
    avoid_stems = plan.get("avoid_stems")
    if not isinstance(avoid_stems, list) or len(avoid_stems) > MAX_QUESTIONS or not all(map(_text, avoid_stems)):
        raise ValueError("avoid_stems 须为至多 100 个非空题干的数组。")
    profiles = payload.get("slot_profiles", {})
    slot_ids = [f"assembly-{index}" for index in range(1, len(deficits) + 1)]
    if not isinstance(profiles, dict) or profiles.keys() - set(slot_ids):
        raise ValueError("slot_profiles 的键须对应联合缺题位置，例如 assembly-1。")

    slots = []
    sources = {}
    for slot_id, deficit in zip(slot_ids, deficits):
        if (
            not isinstance(deficit, dict)
            or not all(_text(deficit.get(key)) for key in SLOT_TEXT_FIELDS)
            or deficit["difficulty"] not in {"easy", "medium", "hard"}
            or any(type(deficit.get(key)) is not int or deficit[key] < 1 for key in SLOT_NUMBER_FIELDS)
        ):
            raise ValueError(f"{slot_id} 须包含科目、考点、题型、有效难度、单题分值和缺题数量。")
        profile = profiles.get(slot_id, {})
        if slot_id in profiles and (
            not isinstance(profile, dict)
            or profile.keys() - {"topic", "constraints", "evidence"}
            or not _text(profile.get("topic"))
        ):
            raise ValueError(f"{slot_id} 的配置须提供 topic，可附带 constraints 和 evidence。")
        slots.append({
            "slot_id": slot_id,
            "count": deficit["missing_count"],
            "score_per_question": deficit["score_per_question"],
            "subject": SUBJECTS.get(deficit["subject"], f"assembly:{deficit['subject']}"),
            "question_type": deficit["question_type"],
            "topic": f"assembly:{deficit['knowledge_point']}",
            **profile,
        })
        sources[slot_id] = {
            "request_id": plan["request_id"],
            **{key: deficit[key] for key in (*SLOT_TEXT_FIELDS, *SLOT_NUMBER_FIELDS)},
        }
    if sum(slot["count"] for slot in slots) != requested_count:
        raise ValueError("各联合槽位缺题数量之和须等于 suggested_additional_count。")

    # Keep request IDs in a separate namespace and include the slot contract so
    # different score or difficulty targets cannot collide in the pending queue.
    digest = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    batch = {
        "schema_version": SCHEMA_VERSION,
        "request_id": f"assembly:{digest}",
        "seed": seed,
        "question_count": requested_count,
        "total_score": sum(slot["count"] * slot["score_per_question"] for slot in slots),
        "slots": slots,
    }
    return batch, sources, tuple(avoid_stems)


def generate_replenishment(payload: dict, *, single_generator: Callable[[object], dict] | None = None) -> dict:
    try:
        batch, sources, reserved_stems = _batch_request(payload)
    except ValueError as error:
        return failure_result("INVALID_REQUEST", str(error))
    result = generate_batch(batch, single_generator=single_generator, reserved_stems=reserved_stems)
    for question in result["questions"]:
        question["assembly_slot"] = {**sources[question["slot_id"]], "difficulty_status": "REVIEW_REQUIRED"}
    for deficit in result["deficits"]:
        deficit["assembly_slot"] = sources[deficit["slot_id"]]
    return {**result, "assembly_request_id": sources["assembly-1"]["request_id"]}
