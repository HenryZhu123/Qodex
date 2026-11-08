"""A scored paging problem and a bounded, version-checked local revision."""

from __future__ import annotations

from random import Random

from .comprehensive import (
    build_views, check_snapshot, check_views, checked_package, generated, read_generator, read_revision, request_id,
    revised,
)
from .generation import REQUIRED_RULES, SUPPORTED_FIELDS, RequestError, _evidence_refs, _read_request, failure_result
from .paging import PagingInstance, create_instance, recompute_translation, render_page_table, translate

GENERATOR_VERSION = "paging-comprehensive-v1"
FIELDS = {**SUPPORTED_FIELDS, "question_type": "comprehensive_application"}
METADATA = {**FIELDS, "score": 10}
CROSS_PAGE = "cross-page"

# (ID, student prompt, rubric rows, primary method, equivalent method)
PARTS = (
    (
        "split-address", "拆分虚拟地址 A，求虚页号与页内字节偏移。",
        (
            ("virtual-page", 1, "给出正确的虚页号。"),
            ("page-offset", 1, "给出正确的页内字节偏移。"),
        ),
        "用 A 除以页大小，商为虚页号，余数为页内偏移。",
        ("bit-split", "可按页大小确定低位位数，低位为偏移，其余高位为虚页号，两个数值与对应评分点一致即可。"),
    ),
    (
        "physical-address", "查页表，写出虚拟地址 A 对应的物理页框号及物理地址。",
        (
            ("page-frame", 1, "查出正确的物理页框号。"),
            ("translated-address", 2, "给出正确的物理字节地址。"),
        ),
        "查出物理页框号，用页框号乘页大小再加页内偏移。",
        ("bit-assembly", "可用物理页框号替换虚地址的虚页号字段并保留低位偏移，所得地址和所报页框号按对应评分点独立判分。"),
    ),
    (
        CROSS_PAGE,
        "设 B 是 A 所在虚页的最后一个虚拟字节地址。求 B 与 B+1 对应的物理地址，"
        "写出 B+1 的虚页号、页内偏移与物理页框号。判断两物理地址是否按递增方向连续，并说明依据。",
        (
            ("before-address", 1, "求出 B 的物理地址。"),
            ("next-page-offset", 1, "同时写出 B+1 的虚页号和页内偏移。"),
            ("next-frame", 1, "查出 B+1 对应的物理页框号。"),
            ("after-address", 1, "求出 B+1 的物理地址。"),
            ("increasing-contiguity", 1, "结论正确，并说明后一物理地址是否等于前一地址加 1，或给出等价的页框判据。"),
        ),
        "分别翻译页尾及下一页页首，计算后一物理地址减前一物理地址，差为 1 时按递增方向连续。",
        ("frame-adjacency", "可用页尾偏移为页大小减 1、页首偏移为 0 证明后一页框号等于前一页框号加 1 时才连续。其余数值按对应评分点独立判分。"),
    ),
)


def _build_views(instance: PagingInstance) -> tuple[dict, dict]:
    address = instance.virtual_address
    page, offset, frame, physical = translate(instance, address)
    after_virtual = (page + 1) * instance.page_size
    _, _, _, before = translate(instance, after_virtual - 1)
    after_page, after_offset, after_frame, after = translate(instance, after_virtual)
    values = (
        (page, offset),
        (frame, physical),
        (before, {"virtual_page": after_page, "offset": after_offset}, after_frame, after, after - before == 1),
    )
    stem = (
        f"某系统按字节寻址，使用单级页表，页大小为 {instance.page_size} B。"
        f"以下页表项均有效：{render_page_table(instance)}。给定虚拟地址 A = 0x{address:X}。"
    )
    return build_views(stem, "各评分点以题设独立判分。十进制及注明进制的其他等值表示均可接受。", PARTS, values)


def _check(instance: PagingInstance, student: dict, instructor: dict) -> None:
    address = instance.virtual_address
    page, offset, frame, physical = recompute_translation(instance, address)
    last_virtual = address | (instance.page_size - 1)
    _, _, before_frame, before = recompute_translation(instance, last_virtual)
    after_page, after_offset, after_frame, after = recompute_translation(instance, last_virtual + 1)
    expected = (
        (page, offset),
        (frame, physical),
        (before, {"virtual_page": after_page, "offset": after_offset}, after_frame, after, after_frame == before_frame + 1),
    )
    check_views(PARTS, METADATA["score"], student, instructor, expected)


def _checked_question(instance: PagingInstance, seed: int, evidence_refs: list[dict]) -> dict:
    student, instructor = _build_views(instance)
    _check(instance, student, instructor)
    generator = {
        "version": GENERATOR_VERSION,
        "seed": seed,
        "parameters": {
            "page_size": instance.page_size,
            "virtual_address": instance.virtual_address,
            "page_table": {str(page): frame for page, frame in instance.page_table.items()},
        },
    }
    return checked_package(
        METADATA, student, instructor, evidence_refs, generator,
        ["part_and_rubric_scores", "independent_address_recomputation", "cross_page_contiguity"],
    )


def generate_comprehensive(payload: object) -> dict:
    """Generate a three-part paging problem."""
    try:
        request = _read_request(payload, comprehensive_fields=FIELDS)
        base = create_instance(Random(request.seed), **request.constraints)
        page = base.virtual_address // base.page_size
        instance = PagingInstance(base.page_size, base.virtual_address,
                                  {key: base.page_table[key] for key in (page, page + 1)})
        question = _checked_question(instance, request.seed, request.evidence_refs)
    except RequestError as error:
        return failure_result(error.status, str(error), request_id(payload), missing_rules=error.missing_rules)
    return generated(request.request_id, "paging-comp", question)


def _valid_frame(value: object) -> bool:
    return type(value) is int and 0 <= value <= 63


def _read_snapshot(question: dict) -> tuple[PagingInstance, int, list[dict]]:
    problem = RequestError("当前题目包与分页综合题的已自检快照不一致。")
    seed, params = read_generator(question, GENERATOR_VERSION, problem)
    size = params.get("page_size")
    address = params.get("virtual_address")
    table = params.get("page_table")
    if type(size) is not int or not 2 <= size <= 65536 or size & (size - 1):
        raise problem
    if type(address) is not int or not size <= address < 16 * size or not isinstance(table, dict):
        raise problem
    page = address // size
    keys = (str(page), str(page + 1))
    if table.keys() != set(keys) or not all(_valid_frame(value) for value in table.values()):
        raise problem
    if table[keys[0]] == table[keys[1]]:
        raise problem
    instance = PagingInstance(size, address, {int(key): table[key] for key in keys})
    refs = _evidence_refs(question.get("evidence_refs"), REQUIRED_RULES, "分页", require_summary=False)
    expected = _checked_question(instance, seed, refs)
    check_snapshot(question, expected, problem)
    return instance, seed, refs


def revise_comprehensive(payload: object) -> dict:
    """Apply one supported feedback action to the caller's current snapshot."""
    identifier = request_id(payload)
    try:
        current, feedback = read_revision(payload, "replacement_frame", "替换页框")
        if feedback["part_id"] != CROSS_PAGE or feedback["action"] != "replace_next_frame":
            raise RequestError("当前支持对 cross-page 使用 replace_next_frame。", "UNSUPPORTED_FEEDBACK")

        instance, seed, refs = _read_snapshot(current)
        page = instance.virtual_address // instance.page_size
        old_frame = instance.page_table[page + 1]
        frame = feedback["replacement_frame"]
        if not _valid_frame(frame) or frame in (instance.page_table[page], old_frame):
            raise RequestError("替换页框须为 0 至 63 的整数，且与两个现有页框都不同。")
        updated = PagingInstance(instance.page_size, instance.virtual_address,
                                 {**instance.page_table, page + 1: frame})
        question = _checked_question(updated, seed, refs)
    except RequestError as error:
        return failure_result(error.status, str(error), identifier, missing_rules=error.missing_rules)
    return revised(identifier, question, current, feedback, {"old_frame": old_frame, "replacement_frame": frame})
