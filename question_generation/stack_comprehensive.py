"""Construct and verify a stack trace and a minimum-capacity proof."""

from __future__ import annotations

from itertools import accumulate, permutations
from random import Random

from .comprehensive import (
    build_views, check_snapshot, check_views, checked_package, generated, read_generator, read_revision,
    request_id, revised,
)
from .generation import STACK_FIELDS, STACK_RULES, RequestError, _evidence_refs, _read_request, failure_result
from .stack import Operation, Sequence, blocking_triple, replay

GENERATOR_VERSION = "stack-comprehensive-v1"
FIELDS = {**STACK_FIELDS, "question_type": "comprehensive_application"}
METADATA = {**FIELDS, "score": 8}
MINIMUM_CAPACITY = "minimum-capacity"

PARTS = (
    (
        "operation-trace", "写出实现目标出栈序列的一组完整入栈、出栈操作，并标明每步操作的元素。",
        (
            ("input-order", 2, "每个元素恰好入栈一次，且入栈次序正确。"),
            ("lifo-output-trace", 2, "每次弹出当前栈顶且完整生成目标出栈序列。"),
        ),
        "目标元素在栈顶时立即弹出，否则按题设入栈顺序推进。依次处理所有目标元素。",
        ("stack-state-table", "可逐步写出栈状态并标明栈顶方向，只要每次入栈和出栈都能从相邻状态还原，并满足对应评分点。"),
    ),
    (
        MINIMUM_CAPACITY,
        "求实现该序列所需的最小栈容量。指出在哪次出栈之前必须达到这个栈深，并说明该容量足以完成整段操作。",
        (
            ("capacity-value", 2, "给出正确的最小容量。"),
            ("capacity-lower-bound", 1, "指出任一达到峰值的出栈位置，并证明当时至少有这么多元素同时在栈中。"),
            ("capacity-witness", 1, "给出或引用一条不超过该容量的合法操作轨迹。"),
        ),
        "从操作轨迹找出峰值。若第 k 次出栈前必须已压入至少 m 个元素，此时仅弹出 k−1 个，至少需要 m−k+1 个位置。",
        ("prefix-maximum", "可取目标序列前 k 个元素的最大编号为 m，计算各 m−k+1 的最大值证明下界，再给出不超过该容量的合法轨迹。"),
    ),
)


def _values(count: int, steps: list[Operation], capacity: int, witness: int) -> tuple:
    return (
        (list(range(1, count + 1)), [{"action": action, "value": value} for action, value in steps]),
        (capacity, {"output_position": witness, "height": capacity}, capacity),
    )


def _build_views(count: int, output: Sequence) -> tuple[dict, dict]:
    steps = replay(count, output)
    if steps is None:
        raise RequestError("目标出栈序列无法实现。", "SELF_CHECK_FAILED")
    depths = list(accumulate(1 if action == "push" else -1 for action, _ in steps))
    before_pops = [depths[index - 1] for index, (action, _) in enumerate(steps) if action == "pop"]
    capacity = max(before_pops)
    witness = before_pops.index(capacity) + 1
    sequence = "、".join(map(str, output))
    stem = (
        f"一个初始为空的栈，元素按 1 到 {count} 的顺序各入栈一次。"
        f"入栈和出栈可以交替，每次只允许弹出栈顶。目标完整出栈序列为 {sequence}。"
        "栈容量按能够同时容纳的元素个数计算。"
    )
    return build_views(stem, "各评分点独立判分。容量下界可使用任一个达到同一峰值的出栈位置。",
                       PARTS, _values(count, steps, capacity, witness))


def _enumerate_traces(count: int, output: Sequence):
    """Explore legal operations independently of the greedy replay."""
    def visit(next_item, pending, emitted, trace, peak):
        if emitted == count:
            yield peak, trace
            return
        if next_item <= count:
            pushed = pending + (next_item,)
            yield from visit(next_item + 1, pushed, emitted, trace + [("push", next_item)], max(peak, len(pushed)))
        if pending and pending[-1] == output[emitted]:
            yield from visit(next_item, pending[:-1], emitted + 1, trace + [("pop", pending[-1])], peak)

    return visit(1, (), 0, [], 0)


def _checked_question(count: int, output: Sequence, seed: int, refs: list[dict]) -> dict:
    student, instructor = _build_views(count, output)
    capacity, trace = min(_enumerate_traces(count, output), default=(0, []))
    bounds = [maximum - index for index, maximum in enumerate(accumulate(output, max))]
    if capacity != max(bounds):
        raise RequestError("穷举得到的最小栈容量与出栈前缀下界不一致。", "SELF_CHECK_FAILED")
    expected = _values(count, trace, capacity, bounds.index(capacity) + 1)
    check_views(PARTS, METADATA["score"], student, instructor, expected)
    generator = {
        "version": GENERATOR_VERSION, "seed": seed,
        "parameters": {"element_count": count, "output_sequence": list(output)},
    }
    return checked_package(
        METADATA, student, instructor, refs, generator,
        ["part_and_rubric_scores", "exhaustive_stack_trace", "minimum_capacity_lower_bound"],
    )


def generate_comprehensive(payload: object) -> dict:
    try:
        request = _read_request(payload, comprehensive_fields=FIELDS)
        count = request.constraints["element_count"]
        outputs = [output for output in permutations(range(1, count + 1)) if not blocking_triple(output)]
        output = Random(request.seed).choice(outputs)
        question = _checked_question(count, output, request.seed, request.evidence_refs)
    except RequestError as error:
        return failure_result(error.status, str(error), request_id(payload), missing_rules=error.missing_rules)
    return generated(request.request_id, "stack-comp", question)


def _read_output(value: object, count: int) -> Sequence:
    if (
        not isinstance(value, list) or len(value) != count
        or not all(type(item) is int for item in value)
        or set(value) != set(range(1, count + 1))
    ):
        raise RequestError("出栈序列必须由全部入栈元素组成，且元素不能重复。")
    output = tuple(value)
    if blocking_triple(output):
        raise RequestError("出栈序列违反后进先出规则。")
    return output


def _read_snapshot(question: dict) -> tuple[int, Sequence, int, list[dict]]:
    problem = RequestError("当前题目包与栈综合题的已自检快照不一致。")
    seed, params = read_generator(question, GENERATOR_VERSION, problem)
    count = params.get("element_count")
    if type(count) is not int or not 4 <= count <= 6:
        raise problem
    output = _read_output(params.get("output_sequence"), count)
    refs = _evidence_refs(question.get("evidence_refs"), STACK_RULES, "栈", require_summary=False)
    check_snapshot(question, _checked_question(count, output, seed, refs), problem)
    return count, output, seed, refs


def revise_comprehensive(payload: object) -> dict:
    identifier = request_id(payload)
    try:
        current, feedback = read_revision(payload, "replacement_output", "替换出栈序列")
        if feedback["part_id"] != MINIMUM_CAPACITY or feedback["action"] != "replace_output_sequence":
            raise RequestError("当前支持对 minimum-capacity 使用 replace_output_sequence。", "UNSUPPORTED_FEEDBACK")
        count, output, seed, refs = _read_snapshot(current)
        updated = _read_output(feedback["replacement_output"], count)
        if updated == output:
            raise RequestError("替换出栈序列必须与当前序列不同。")
        question = _checked_question(count, updated, seed, refs)
    except RequestError as error:
        return failure_result(error.status, str(error), identifier, missing_rules=error.missing_rules)
    return revised(identifier, question, current, feedback, {
        "old_output": list(output),
        "replacement_output": list(updated),
        "affected_parts": ["operation-trace", MINIMUM_CAPACITY],
    })
