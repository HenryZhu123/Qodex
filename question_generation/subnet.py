"""IPv4 network addresses from a given address and CIDR prefix length."""

from ipaddress import IPv4Address, IPv4Network

METADATA = {
    "subject": "computer_networks",
    "topic": "ipv4_subnet_network_address",
    "question_type": "single_choice",
}
REQUIRED_RULES = {"ipv4_cidr_prefix", "ipv4_subnet_alignment"}
MATERIAL_NAME = "IPv4 子网"
PREFIX = "subnet"
CHECK = "independent_ipv4_network_address"
ADDRESS_COUNT = 2**32
PRIVATE_START = int(IPv4Address("10.0.0.0"))


def read_constraints(constraints):
    if not isinstance(constraints, dict) or constraints.keys() - {"prefix_length", "ipv4_address"}:
        raise ValueError("constraints 只支持 prefix_length 和 ipv4_address。")
    prefix = constraints.get("prefix_length", 26)
    if type(prefix) is not int or not 16 <= prefix <= 30:
        raise ValueError("prefix_length 必须是 16 至 30 的整数。")

    address = None
    if "ipv4_address" in constraints:
        text = constraints["ipv4_address"]
        message = "ipv4_address 必须是标准点分十进制 IPv4 地址，例如 10.23.45.77。"
        if not isinstance(text, str):
            raise ValueError(message)
        try:
            parsed = IPv4Address(text)
        except ValueError as error:
            raise ValueError(message) from error
        if str(parsed) != text:
            raise ValueError(message)
        address = int(parsed)
    return {"prefix_length": prefix, "address": address}


def build(rng, prefix_length, address):
    block_size = 2 ** (32 - prefix_length)
    if address is None:
        address = PRIVATE_START + rng.randrange(2**24)
    network = (address // block_size) * block_size
    adjacent = network + block_size
    direction = "下一"
    if adjacent == ADDRESS_COUNT:
        adjacent = network - block_size
        direction = "上一"

    address_text = format_choice(address)
    stem = (
        f"给定 IPv4 地址 {address_text}/{prefix_length}，"
        "该地址所属子网的网络地址是什么？"
    )
    choices = [
        (network, f"主机位有 {32 - prefix_length} 位，每个地址块有 {block_size} 个地址。"
         f"将地址按块大小向下对齐，等同于把主机位全置 0，得到 {format_choice(network)}。"),
        (network + block_size - 1, "把主机位全置 1 得到的是该地址块的末地址。"),
        (network + 1, "取了地址块起点之后的第一个地址。"),
        (adjacent, f"把{direction}个同样大小的地址块起点当作本子网的网络地址。"),
    ]
    expected = int(IPv4Network((address, prefix_length), strict=False).network_address)
    return stem, choices, expected, {"ipv4_address": address_text, "prefix_length": prefix_length}


def format_choice(value):
    return str(IPv4Address(value))
