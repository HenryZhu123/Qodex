"""Single-stack output permutations and independent push/pop verification."""

from __future__ import annotations

from itertools import combinations, permutations
from random import Random

Sequence = tuple[int, ...]


def _blocking_triple(output: Sequence) -> Sequence:
    for first, second, third in combinations(output, 3):
        if second < third < first:
            return first, second, third
    return ()


def build_choices(count: int, rng: Random) -> tuple[dict[str, Sequence], str]:
    possible = []
    impossible = []
    for output in permutations(range(1, count + 1)):
        if _blocking_triple(output):
            impossible.append(output)
        else:
            possible.append(output)

    answer = rng.choice(possible)
    candidates = [answer, *rng.sample(impossible, 3)]
    rng.shuffle(candidates)
    options = {f"option-{index}": output for index, output in enumerate(candidates, 1)}
    return options, next(key for key, output in options.items() if output == answer)


def _replay(count: int, output: Sequence) -> list[str] | None:
    stack = []
    steps = []
    next_input = 1
    for target in output:
        while (not stack or stack[-1] != target) and next_input <= count:
            stack.append(next_input)
            steps.append(f"入栈 {next_input}")
            next_input += 1
        if not stack or stack[-1] != target:
            return None
        steps.append(f"出栈 {stack.pop()}")
    return steps


def check_choices(count: int, choices: dict[str, Sequence], answer_id: str) -> str | None:
    expected_items = tuple(range(1, count + 1))
    if len(choices) != 4 or len(set(choices.values())) != 4 or any(
        tuple(sorted(output)) != expected_items for output in choices.values()
    ):
        return "选项必须是由全部入栈元素构成的四个不同排列。"

    reachable = [key for key, output in choices.items() if _replay(count, output) is not None]
    if reachable != [answer_id]:
        return "独立模拟未得到唯一可行的出栈序列，或答案 ID 与该序列不一致。"
    return None


def explain_choice(count: int, output: Sequence) -> str:
    blocking = _blocking_triple(output)
    if blocking:
        first, second, third = blocking
        return (
            f"弹出 {first} 时，{second} 和 {third} 都已入栈。"
            f"按候选顺序轮到 {second} 时，尚未出栈的 {third} 位于它上方，"
            f"因此无法弹出 {second}。"
        )
    steps = _replay(count, output)
    assert steps is not None, "Expected a verified, reachable sequence"
    return "一种可行的操作顺序是" + "、".join(steps) + "。"


def render_stem(count: int) -> str:
    return (
        f"一个初始为空且容量足够的栈，元素按 1 到 {count} 的顺序各入栈一次。"
        "入栈和出栈可交替进行，每次只能弹出栈顶元素。以下哪个完整出栈序列可能出现？"
    )
