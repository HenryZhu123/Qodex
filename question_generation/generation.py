"""Validate a local request and return a question package or a typed failure."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from random import Random

from .paging import build_choices, check_choices, create_instance, render_stem

SCHEMA_VERSION = "0.1"
GENERATOR_VERSION = "paging-v1"
SUPPORTED_FIELDS = {
    "subject": "operating_systems",
    "topic": "single_level_paging",
    "question_type": "single_choice",
}
REQUEST_FIELDS = {
    "schema_version", "request_id", "seed", "constraints", "evidence", *SUPPORTED_FIELDS,
}
EVIDENCE_TEXT_FIELDS = ("id", "source", "version", "anchor", "summary")
REQUIRED_RULES = {"split_address", "map_virtual_page", "preserve_offset"}


class RequestError(ValueError):
    def __init__(
        self, message: str, status: str = "INVALID_REQUEST", *, missing_rules: tuple[str, ...] = ()
    ):
        super().__init__(message)
        self.status = status
        self.missing_rules = missing_rules


@dataclass(frozen=True)
class PagingRequest:
    request_id: str
    seed: int
    page_size: int
    offset: int | None
    evidence_refs: list[dict]


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _evidence_refs(evidence: object) -> list[dict]:
    if not isinstance(evidence, list):
        raise RequestError("evidence 必须是材料数组。")

    refs = []
    seen_ids = set()
    covered_rules = set()
    for item in evidence:
        if not isinstance(item, dict) or item.keys() != {*EVIDENCE_TEXT_FIELDS, "rules"}:
            raise RequestError("每条材料必须包含 id、source、version、anchor、summary 和 rules。")
        if not all(_is_text(item[field]) for field in EVIDENCE_TEXT_FIELDS):
            raise RequestError("材料的来源、定位、摘要等文本字段须为非空字符串。")
        rules = item["rules"]
        if not isinstance(rules, list) or not all(_is_text(rule) for rule in rules):
            raise RequestError("材料 rules 必须是规则标记的字符串数组。")

        evidence_id = item["id"]
        if evidence_id in seen_ids:
            raise RequestError("材料 ID 必须唯一。")
        seen_ids.add(evidence_id)

        used_rules = REQUIRED_RULES.intersection(rules)
        if used_rules:
            refs.append({
                "id": evidence_id,
                "source": item["source"],
                "version": item["version"],
                "anchor": item["anchor"],
                "rules": sorted(used_rules),
            })
            covered_rules.update(used_rules)

    missing = REQUIRED_RULES - covered_rules
    if missing:
        raise RequestError(
            "材料未覆盖命题所需的分页规则。",
            "NEEDS_MATERIAL",
            missing_rules=tuple(sorted(missing)),
        )
    return refs


def _read_request(payload: object) -> PagingRequest:
    if not isinstance(payload, dict) or payload.keys() - REQUEST_FIELDS:
        raise RequestError("请求必须是 JSON 对象，且只包含已定义的字段。")

    for field in ("schema_version", "request_id", *SUPPORTED_FIELDS):
        if not _is_text(payload.get(field)):
            raise RequestError(f"{field} 必须是非空字符串。")

    for field, expected in {"schema_version": SCHEMA_VERSION, **SUPPORTED_FIELDS}.items():
        if payload[field] != expected:
            raise RequestError(f"{field} 当前仅支持 {expected}。", "UNSUPPORTED_REQUEST")

    seed = payload.get("seed")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise RequestError("seed 必须是 0 至 4294967295 的整数。")

    constraints = payload.get("constraints", {})
    if not isinstance(constraints, dict) or constraints.keys() - {"page_size", "offset"}:
        raise RequestError("constraints 只支持 page_size 和 offset。")

    page_size = constraints.get("page_size", 256)
    if type(page_size) is not int or not 2 <= page_size <= 65536 or page_size & (page_size - 1):
        raise RequestError("page_size 必须是 2 至 65536 字节之间的 2 的幂。")
    offset = constraints.get("offset")
    if "offset" in constraints and (type(offset) is not int or not 0 <= offset < page_size):
        raise RequestError("offset 必须是大于等于 0 且小于页大小的整数。")

    refs = _evidence_refs(payload.get("evidence", []))
    return PagingRequest(payload["request_id"], seed, page_size, offset, refs)


def failure_result(
    status: str, message: str, request_id: str | None = None, *, missing_rules: tuple[str, ...] = ()
) -> dict:
    result = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "status": status,
        "questions": [],
        "message": message,
    }
    if missing_rules:
        result["missing_rules"] = list(missing_rules)
    return result


def generate_question(payload: object) -> dict:
    """Generate one self-checked question using pre-labelled evidence."""
    try:
        request = _read_request(payload)
    except RequestError as error:
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        return failure_result(
            error.status,
            str(error),
            request_id if _is_text(request_id) else None,
            missing_rules=error.missing_rules,
        )

    rng = Random(request.seed)
    instance = create_instance(rng, request.page_size, request.offset)
    choices, answer_id = build_choices(instance, rng)
    problem = check_choices(instance, choices, answer_id)
    if problem is not None:
        return failure_result("SELF_CHECK_FAILED", problem, request.request_id)

    question = {
        "version": 1,
        "metadata": SUPPORTED_FIELDS.copy(),
        "student_view": {
            "stem": render_stem(instance),
            "options": [
                {"id": option_id, "text": f"0x{choice.address:X}"}
                for option_id, choice in choices.items()
            ],
        },
        "instructor_view": {
            "correct_option_id": answer_id,
            "explanation": choices[answer_id].explanation,
            "option_explanations": {
                option_id: choice.explanation for option_id, choice in choices.items()
            },
        },
        "evidence_refs": request.evidence_refs,
        "generator": {
            "version": GENERATOR_VERSION,
            "seed": request.seed,
            "parameters": {
                "page_size": instance.page_size,
                "virtual_address": instance.virtual_address,
                "page_table": {str(page): frame for page, frame in instance.page_table.items()},
            },
        },
        "self_check": {
            "status": "PASSED",
            "checks": ["distinct_options", "independent_address_recomputation"],
        },
        "review_status": "PENDING",
    }
    identity = json.dumps([request.request_id, question], sort_keys=True).encode("utf-8")
    question["question_id"] = f"paging-{hashlib.sha256(identity).hexdigest()[:24]}"
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request.request_id,
        "status": "GENERATED",
        "questions": [question],
    }
