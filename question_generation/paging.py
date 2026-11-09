"""Single-level paging instances, answer choices, and deterministic checks."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random


@dataclass(frozen=True)
class PagingInstance:
    page_size: int
    virtual_address: int
    page_table: dict[int, int]


@dataclass(frozen=True)
class Choice:
    address: int
    explanation: str


def create_instance(rng: Random, page_size: int, offset: int | None) -> PagingInstance:
    virtual_page = rng.randint(1, 15)
    frames = rng.sample(range(16, 64), 3)
    page_table = dict(zip(range(virtual_page - 1, virtual_page + 2), frames))
    if offset is None:
        offset = rng.randrange(page_size)
    return PagingInstance(page_size, virtual_page * page_size + offset, page_table)


def translate(instance: PagingInstance, address: int) -> tuple[int, int, int, int]:
    page, offset = divmod(address, instance.page_size)
    frame = instance.page_table[page]
    return page, offset, frame, frame * instance.page_size + offset


def recompute_translation(instance: PagingInstance, address: int) -> tuple[int, int, int, int]:
    """Independently extract address fields and replace the page number."""
    offset_bits = instance.page_size.bit_length() - 1
    page = address >> offset_bits
    offset = address & (instance.page_size - 1)
    frame = instance.page_table[page]
    return page, offset, frame, (frame << offset_bits) | offset


def build_choices(instance: PagingInstance, rng: Random) -> tuple[dict[str, Choice], str]:
    size = instance.page_size
    virtual_page, offset, frame, answer = translate(instance, instance.virtual_address)

    correct = Choice(
        answer,
        f"虚页号为 {virtual_page}，页内偏移为 0x{offset:X}。"
        f"查有效页表项得物理页框号 {frame}，"
        f"物理地址为 {frame} × {size} + 0x{offset:X} = 0x{answer:X}。",
    )
    distractors = (
        Choice(instance.virtual_address, "跳过页表转换，把虚拟地址当成物理地址。"),
        Choice(frame * size, "查得正确的物理页框号，但丢弃了页内偏移。"),
        Choice(
            instance.page_table[virtual_page + 1] * size + offset,
            "页表索引误加 1，使用了下一虚页的物理页框号。",
        ),
        Choice(
            instance.page_table[virtual_page - 1] * size + offset,
            "页表索引误减 1，使用了上一虚页的物理页框号。",
        ),
    )
    choices = [correct]
    used_addresses = {answer}
    for distractor in distractors:
        if distractor.address not in used_addresses:
            choices.append(distractor)
            used_addresses.add(distractor.address)
        if len(choices) == 4:
            break

    rng.shuffle(choices)
    options = {f"option-{index}": choice for index, choice in enumerate(choices, 1)}
    answer_id = next(key for key, choice in options.items() if choice is correct)
    return options, answer_id


def check_choices(
    instance: PagingInstance, choices: dict[str, Choice], answer_id: str
) -> str | None:
    if len(choices) != 4 or len({choice.address for choice in choices.values()}) != 4:
        return "选项必须包含四个不同的物理地址值。"

    _, _, _, expected = recompute_translation(instance, instance.virtual_address)
    if answer_id not in choices or choices[answer_id].address != expected:
        return "答案 ID 与独立复算的物理地址不一致。"
    return None


def render_page_table(instance: PagingInstance) -> str:
    return "，".join(
        f"虚页 {page} 对应物理页框 {frame}"
        for page, frame in instance.page_table.items()
    )


def render_stem(instance: PagingInstance) -> str:
    return (
        f"某系统按字节寻址，使用单级页表，页大小为 {instance.page_size} B。"
        f"以下页表项均有效：{render_page_table(instance)}。"
        f"虚拟地址 0x{instance.virtual_address:X} 对应的物理地址是什么？"
    )
