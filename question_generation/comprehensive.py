"""Shared structure and version checks for local comprehensive questions."""

from __future__ import annotations

import hashlib
import json

from .generation import SCHEMA_VERSION, RequestError, _is_text

MAX_REVISIONS = 2
FEEDBACK_FIELDS = {"feedback_id", "question_id", "target_version", "part_id", "action", "comment"}


def build_views(stem, grading_policy, parts, values):
    prompts = []
    solutions = []
    for (part_id, prompt, rubric, primary, (method_id, acceptance)), answers in zip(parts, values):
        prompts.append({"id": part_id, "prompt": prompt, "score": sum(points for _, points, _ in rubric)})
        solutions.append({
            "part_id": part_id,
            "solution": primary,
            "scoring_points": [
                {"id": point_id, "points": points, "criterion": criterion, "expected": answer}
                for (point_id, points, criterion), answer in zip(rubric, answers)
            ],
            "equivalent_methods": [{"id": method_id, "acceptance": acceptance}],
        })
    return {"stem": stem, "parts": prompts}, {"grading_policy": grading_policy, "parts": solutions}


def check_views(parts, total_score, student, instructor, expected):
    if (
        len(student["parts"]) != len(parts)
        or len(instructor["parts"]) != len(parts)
        or len(expected) != len(parts)
        or sum(part["score"] for part in student["parts"]) != total_score
    ):
        raise RequestError("小问数或总分与契约不符。", "SELF_CHECK_FAILED")
    for spec, prompt, solution, values in zip(parts, student["parts"], instructor["parts"], expected):
        part_id, _, rubric, _, _ = spec
        points = solution["scoring_points"]
        if (
            prompt["id"] != part_id
            or solution["part_id"] != part_id
            or [(point["id"], point["points"]) for point in points] != [(key, score) for key, score, _ in rubric]
            or sum(point["points"] for point in points) != prompt["score"]
            or not solution["equivalent_methods"]
        ):
            raise RequestError(f"小问 {part_id} 的评分结构无效。", "SELF_CHECK_FAILED")
        if json.dumps([point["expected"] for point in points], sort_keys=True) != json.dumps(values, sort_keys=True):
            raise RequestError(f"小问 {part_id} 的评分点与独立复算不一致。", "SELF_CHECK_FAILED")


def checked_package(metadata, student, instructor, evidence_refs, generator, checks):
    return {
        "metadata": metadata.copy(),
        "student_view": student,
        "instructor_view": instructor,
        "evidence_refs": evidence_refs,
        "generator": generator,
        "self_check": {"status": "PASSED", "checks": checks},
        "review_status": "PENDING",
    }


def request_id(payload: object) -> str | None:
    value = payload.get("request_id") if isinstance(payload, dict) else None
    return value if _is_text(value) else None


def _result(identifier: str, status: str, question: dict) -> dict:
    return {"schema_version": SCHEMA_VERSION, "request_id": identifier, "status": status, "questions": [question]}


def generated(identifier: str, prefix: str, question: dict) -> dict:
    identity = json.dumps([identifier, question], sort_keys=True).encode("utf-8")
    question.update(question_id=f"{prefix}-{hashlib.sha256(identity).hexdigest()[:24]}", version=1)
    return _result(identifier, "GENERATED", question)


def read_revision(payload: object, action_field: str, action_label: str) -> tuple[dict, dict]:
    if (
        request_id(payload) is None or payload.keys() != {"schema_version", "request_id", "current_question", "feedback"}
        or payload["schema_version"] != SCHEMA_VERSION
    ):
        raise RequestError("修订请求须包含 schema_version、request_id、current_question 和 feedback。")
    current = payload["current_question"]
    feedback = payload["feedback"]
    if not isinstance(current, dict) or not _is_text(current.get("question_id")):
        raise RequestError("current_question 必须包含题目 ID 和当前版本。")
    if not isinstance(feedback, dict) or feedback.keys() != FEEDBACK_FIELDS | {action_field} or not all(
        _is_text(feedback[key]) for key in ("feedback_id", "question_id", "part_id", "action", "comment")
    ):
        raise RequestError(f"feedback 必须包含反馈 ID、题目 ID、目标版本、小问、动作、{action_label}和说明。")
    version = current.get("version")
    target_version = feedback["target_version"]
    if type(version) is not int or type(target_version) is not int or min(version, target_version) < 1:
        raise RequestError("当前版本和目标版本必须是正整数。")
    if current["question_id"] != feedback["question_id"]:
        raise RequestError("反馈的题目 ID 与当前题目不一致。", "FEEDBACK_TARGET_MISMATCH")
    if version != target_version:
        raise RequestError(f"反馈针对 v{target_version}，当前题目为 v{version}。", "STALE_FEEDBACK")
    if version > MAX_REVISIONS:
        raise RequestError("此题已达到两轮修订上限。", "REVISION_LIMIT")
    return current, feedback


def read_generator(question: dict, generator_version: str, problem: RequestError) -> tuple[int, dict]:
    generator = question.get("generator")
    if not isinstance(generator, dict) or generator.get("version") != generator_version:
        raise problem
    seed = generator.get("seed")
    params = generator.get("parameters")
    if type(seed) is not int or not 0 <= seed < 2**32 or not isinstance(params, dict):
        raise problem
    return seed, params


def check_snapshot(question: dict, expected: dict, problem: RequestError) -> None:
    # Review is external to the canonical generated fields.
    fields = expected.keys() - {"review_status"}
    try:
        snapshot = json.dumps({key: question.get(key) for key in fields}, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise problem from error
    if snapshot != json.dumps({key: expected[key] for key in fields}, sort_keys=True):
        raise problem


def revised(identifier: str, question: dict, current: dict, feedback: dict, changes: dict) -> dict:
    question.update(
        question_id=current["question_id"], version=current["version"] + 1,
        revision={
            "from_version": current["version"], "feedback_id": feedback["feedback_id"],
            "part_id": feedback["part_id"], "action": feedback["action"], "comment": feedback["comment"],
            **changes,
        },
    )
    return _result(identifier, "REVISED", question)


def generate_comprehensive(payload: object) -> dict:
    from . import paging_comprehensive, stack_comprehensive

    if isinstance(payload, dict) and payload.get("topic") == stack_comprehensive.METADATA["topic"]:
        return stack_comprehensive.generate_comprehensive(payload)
    return paging_comprehensive.generate_comprehensive(payload)


def revise_comprehensive(payload: object) -> dict:
    from . import paging_comprehensive, stack_comprehensive

    current = payload.get("current_question") if isinstance(payload, dict) else None
    metadata = current.get("metadata") if isinstance(current, dict) else None
    if isinstance(metadata, dict) and metadata.get("topic") == stack_comprehensive.METADATA["topic"]:
        return stack_comprehensive.revise_comprehensive(payload)
    return paging_comprehensive.revise_comprehensive(payload)
