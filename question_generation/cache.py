"""Direct-mapped cache address fields for a 16-bit byte address."""

ADDRESS_BITS = 16
METADATA = {
    "subject": "computer_organization",
    "topic": "direct_mapped_cache",
    "question_type": "single_choice",
}
REQUIRED_RULES = {"cache_byte_offset", "cache_line_index", "cache_tag"}
MATERIAL_NAME = "直接映射 Cache"
PREFIX = "cache"
CHECK = "independent_cache_bit_fields"


def read_constraints(constraints):
    if not isinstance(constraints, dict) or constraints.keys() - {"cache_size", "block_size", "address"}:
        raise ValueError("constraints 只支持 cache_size、block_size 和 address。")
    size = constraints.get("cache_size", 256)
    block = constraints.get("block_size", 16)
    for name, value, minimum, maximum in (
        ("cache_size", size, 16, 4096),
        ("block_size", block, 4, 256),
    ):
        if type(value) is not int or not minimum <= value <= maximum or value & (value - 1):
            raise ValueError(f"{name} 必须是 {minimum} 至 {maximum} 字节之间的 2 的幂。")
    if block >= size:
        raise ValueError("Cache 数据容量必须至少容纳两块。")
    address = constraints.get("address")
    if "address" in constraints and (type(address) is not int or not 0 <= address < 2**ADDRESS_BITS):
        raise ValueError("address 必须是 0 至 65535 的整数。")
    return {"cache_size": size, "block_size": block, "address": address}


def build(rng, cache_size, block_size, address):
    if address is None:
        address = rng.randrange(2**ADDRESS_BITS)
    lines = cache_size // block_size
    memory_block, offset = divmod(address, block_size)
    tag, index = divmod(memory_block, lines)

    # Each distractor changes one field. Use an in-range bit error when
    # the misconception would coincide with the answer or exceed the field.
    tag_error = (memory_block, "误把完整的主存块号当作标记。")
    if memory_block == tag or memory_block >= 2**ADDRESS_BITS // cache_size:
        tag_error = (tag ^ 1, "误读了标记的最低位。")
    index_error = (offset % lines, "误用块内偏移对行数取余来选行。")
    if index_error[0] == index:
        index_error = (index ^ 1, "误读了行号的最低位。")
    offset_error = (offset + 1, "误把块内偏移从 1 开始计数。")
    if offset + 1 == block_size:
        offset_error = (offset ^ 1, "误读了块内偏移的最低位。")

    choices = [
        ((tag, index, offset),
         f"Cache 有 {cache_size} ÷ {block_size} = {lines} 行。"
         f"地址除以块大小得主存块号 {memory_block}，余数为 {offset}。"
         f"主存块号除以行数，商为标记 {tag}，余数为行号 {index}。"),
        ((tag_error[0], index, offset), tag_error[1]),
        ((tag, index_error[0], offset), index_error[1]),
        ((tag, index, offset_error[0]), offset_error[1]),
    ]

    offset_bits = block_size.bit_length() - 1
    tag_shift = cache_size.bit_length() - 1
    index_mask = (1 << (tag_shift - offset_bits)) - 1
    expected = (address >> tag_shift, (address >> offset_bits) & index_mask, address & ((1 << offset_bits) - 1))
    stem = (
        f"某系统按字节寻址，地址宽度为 {ADDRESS_BITS} 位。直接映射 Cache 的数据容量为 {cache_size} B，"
        f"每块 {block_size} B，每行存放一块，行号和块内字节偏移均从 0 开始。"
        f"地址 0x{address:04X} 的标记、行号、块内字节偏移分别是多少？各选项均为十进制。"
    )
    params = {"address_bits": ADDRESS_BITS, "cache_size": cache_size, "block_size": block_size, "address": address}
    return stem, choices, expected, params


def format_choice(value):
    return "、".join(map(str, value))
