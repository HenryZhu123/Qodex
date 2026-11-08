"""Validate a local request and return a question package or a typed failure."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from random import Random

from . import cache, stack, subnet, tcp
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
STACK_FIELDS = {
    "subject": "data_structures",
    "topic": "stack_pop_sequence",
    "question_type": "single_choice",
}
STACK_RULES = {"stack_push_top", "stack_pop_top"}
RULE_TOPICS = {module.METADATA["topic"]: module for module in (cache, subnet, tcp)}
SUBJECT_DEFAULTS = {module.METADATA["subject"]: module for module in (cache, subnet)}


class RequestError(ValueError):
    def __init__(
        self, message: str, status: str = "INVALID_REQUEST", *, missing_rules: tuple[str, ...] = ()
    ):
        super().__init__(message)
        self.status = status
        self.missing_rules = missing_rules


@dataclass(frozen=True)
class Request:
    request_id: str
    seed: int
    metadata: dict[str, str]
    constraints: dict
    evidence_refs: list[dict]


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _evidence_refs(
    evidence: object, required_rules: set[str], topic_name: str, *, require_summary: bool = True
) -> list[dict]:
    if not isinstance(evidence, list):
        raise RequestError("evidence 必须是材料数组。")

    refs = []
    seen_ids = set()
    covered_rules = set()
    text_fields = EVIDENCE_TEXT_FIELDS if require_summary else EVIDENCE_TEXT_FIELDS[:-1]
    for item in evidence:
        if not isinstance(item, dict) or item.keys() != {*text_fields, "rules"}:
            expected = "id、source、version、anchor、summary" if require_summary else "id、source、version、anchor"
            raise RequestError(f"每条材料必须包含 {expected} 和 rules。")
        if not all(_is_text(item[field]) for field in text_fields):
            raise RequestError("材料的来源、定位、摘要等文本字段须为非空字符串。")
        rules = item["rules"]
        if not isinstance(rules, list) or not all(_is_text(rule) for rule in rules):
            raise RequestError("材料 rules 必须是规则标记的字符串数组。")

        evidence_id = item["id"]
        if evidence_id in seen_ids:
            raise RequestError("材料 ID 必须唯一。")
        seen_ids.add(evidence_id)

        used_rules = required_rules.intersection(rules)
        if used_rules:
            refs.append({
                "id": evidence_id,
                "source": item["source"],
                "version": item["version"],
                "anchor": item["anchor"],
                "rules": sorted(used_rules),
            })
            covered_rules.update(used_rules)

    missing = required_rules - covered_rules
    if missing:
        raise RequestError(
            f"材料未覆盖命题所需的{topic_name}规则。",
            "NEEDS_MATERIAL",
            missing_rules=tuple(sorted(missing)),
        )
    return refs


def _read_request(payload: object, *, comprehensive_fields: dict[str, str] | None = None) -> Request:
    if not isinstance(payload, dict) or payload.keys() - REQUEST_FIELDS:
        raise RequestError("请求必须是 JSON 对象，且只包含已定义的字段。")

    for field in ("schema_version", "request_id", *SUPPORTED_FIELDS):
        if not _is_text(payload.get(field)):
            raise RequestError(f"{field} 必须是非空字符串。")

    rule_topic = None
    if comprehensive_fields is not None:
        metadata = comprehensive_fields
    else:
        rule_topic = RULE_TOPICS.get(payload["topic"])
        if rule_topic is None or rule_topic.METADATA["subject"] != payload["subject"]:
            rule_topic = SUBJECT_DEFAULTS.get(payload["subject"])
        metadata = STACK_FIELDS if payload["subject"] == STACK_FIELDS["subject"] else SUPPORTED_FIELDS
        if rule_topic is not None:
            metadata = rule_topic.METADATA
    for field, expected in {"schema_version": SCHEMA_VERSION, **metadata}.items():
        if payload[field] != expected:
            raise RequestError(f"{field} 当前仅支持 {expected}。", "UNSUPPORTED_REQUEST")

    seed = payload.get("seed")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise RequestError("seed 必须是 0 至 4294967295 的整数。")

    constraints = payload.get("constraints", {})
    evidence = payload.get("evidence", [])
    if rule_topic is not None:
        try:
            constraints = rule_topic.read_constraints(constraints)
        except ValueError as error:
            raise RequestError(str(error)) from error
        refs = _evidence_refs(evidence, rule_topic.REQUIRED_RULES, rule_topic.MATERIAL_NAME)
        return Request(payload["request_id"], seed, metadata, constraints, refs)
    if metadata["topic"] == STACK_FIELDS["topic"]:
        if not isinstance(constraints, dict) or constraints.keys() - {"element_count"}:
            raise RequestError("constraints 只支持 element_count。")
        count = constraints.get("element_count", 5)
        if type(count) is not int or not 4 <= count <= 6:
            raise RequestError("element_count 必须是 4 至 6 的整数。")
        refs = _evidence_refs(evidence, STACK_RULES, "栈")
        return Request(payload["request_id"], seed, metadata, {"element_count": count}, refs)

    if not isinstance(constraints, dict) or constraints.keys() - {"page_size", "offset"}:
        raise RequestError("constraints 只支持 page_size 和 offset。")

    page_size = constraints.get("page_size", 256)
    if type(page_size) is not int or not 2 <= page_size <= 65536 or page_size & (page_size - 1):
        raise RequestError("page_size 必须是 2 至 65536 字节之间的 2 的幂。")
    offset = constraints.get("offset")
    if "offset" in constraints and (type(offset) is not int or not 0 <= offset < page_size):
        raise RequestError("offset 必须是大于等于 0 且小于页大小的整数。")

    refs = _evidence_refs(evidence, REQUIRED_RULES, "分页")
    return Request(payload["request_id"], seed, metadata, {"page_size": page_size, "offset": offset}, refs)


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
    rule_topic = RULE_TOPICS.get(request.metadata["topic"])
    if rule_topic is not None:
        stem, candidates, expected, parameters = rule_topic.build(rng, **request.constraints)
        values = [value for value, _ in candidates]
        option_texts = {rule_topic.format_choice(value) for value in values}
        if len(values) != 4 or len(option_texts) != 4 or values[0] != expected:
            return failure_result("SELF_CHECK_FAILED", "选项重复或答案与校验结果不一致。", request.request_id)
        prefix = rule_topic.PREFIX
        generator_version = f"{prefix}-v1"
        check = rule_topic.CHECK
        rng.shuffle(candidates)
        options = {f"option-{index}": choice for index, choice in enumerate(candidates, 1)}
        answer_id = next(key for key, (value, _) in options.items() if value == expected)
        texts = {key: rule_topic.format_choice(value) for key, (value, _) in options.items()}
        explanations = {key: explanation for key, (_, explanation) in options.items()}
    elif request.metadata is STACK_FIELDS:
        count = request.constraints["element_count"]
        sequences, answer_id = stack.build_choices(count, rng)
        problem = stack.check_choices(count, sequences, answer_id)
        if problem is not None:
            return failure_result("SELF_CHECK_FAILED", problem, request.request_id)
        prefix = "stack"
        generator_version = "stack-v1"
        stem = stack.render_stem(count)
        texts = {key: "、".join(map(str, output)) for key, output in sequences.items()}
        explanations = {key: stack.explain_choice(count, output) for key, output in sequences.items()}
        parameters = {"element_count": count, "input_sequence": list(range(1, count + 1))}
        check = "independent_stack_replay"
    else:
        instance = create_instance(rng, **request.constraints)
        choices, answer_id = build_choices(instance, rng)
        problem = check_choices(instance, choices, answer_id)
        if problem is not None:
            return failure_result("SELF_CHECK_FAILED", problem, request.request_id)
        prefix = "paging"
        generator_version = GENERATOR_VERSION
        stem = render_stem(instance)
        texts = {key: f"0x{choice.address:X}" for key, choice in choices.items()}
        explanations = {key: choice.explanation for key, choice in choices.items()}
        parameters = {
            "page_size": instance.page_size,
            "virtual_address": instance.virtual_address,
            "page_table": {str(page): frame for page, frame in instance.page_table.items()},
        }
        check = "independent_address_recomputation"

    question = {
        "version": 1,
        "metadata": request.metadata.copy(),
        "student_view": {
            "stem": stem,
            "options": [
                {"id": option_id, "text": option_text} for option_id, option_text in texts.items()
            ],
        },
        "instructor_view": {
            "correct_option_id": answer_id,
            "explanation": explanations[answer_id],
            "option_explanations": explanations,
        },
        "evidence_refs": request.evidence_refs,
        "generator": {
            "version": generator_version,
            "seed": request.seed,
            "parameters": parameters,
        },
        "self_check": {
            "status": "PASSED",
            "checks": ["distinct_options", check],
        },
        "review_status": "PENDING",
    }
    identity = json.dumps([request.request_id, question], sort_keys=True).encode("utf-8")
    question["question_id"] = f"{prefix}-{hashlib.sha256(identity).hexdigest()[:24]}"
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request.request_id,
        "status": "GENERATED",
        "questions": [question],
    }
