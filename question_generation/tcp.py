"""Conceptual single-choice items about TCP byte-stream boundaries."""

METADATA = {
    "subject": "computer_networks",
    "topic": "tcp_message_boundaries",
    "question_type": "single_choice",
}
REQUIRED_RULES = {"tcp_ordered_byte_stream", "tcp_no_message_boundaries"}
MATERIAL_NAME = "TCP 字节流"
PREFIX = "tcp"
CHECK = "unique_supported_tcp_claim"

# These proposition IDs are supported by RFC 9293 §2.2 and §3.7.
SUPPORTED_CLAIMS = {"ordered_stream", "application_length_field"}
SCENARIOS = {
    "reads": (
        "在一条正常工作的 TCP 连接上，发送应用先后两次写入非空数据。"
        "接收应用可多次读取。以下哪项是 TCP 对应用提供的保证？",
        (
            (("ordered_stream", "已交付的字节保持发送顺序，接收方每次读到的边界可以不同于发送方的写入边界。"),
             "TCP 按序交付字节流。一次读取可能得到一次写入的一部分，也可能跨越写入边界。"),
            (("one_read_per_write", "接收应用必须恰好读取两次，每次对应发送方的一次写入。"),
             "读取次数由可读数据、缓冲区等因素决定，TCP 没有读写次数一一对应的保证。"),
            (("one_segment_per_write", "发送方每次写入的数据一定由一个独立的 TCP 段承载。"),
             "TCP 根据字节流分段，可以拆分一次写入，也可以把多次写入的数据放在同一段。"),
            (("receive_out_of_order", "接收应用可能先读到后一次写入的字节，再读到前一次写入的字节。"),
             "网络中的 TCP 段可能乱序到达，但 TCP 向应用按字节顺序交付。"),
        ),
    ),
    "framing": (
        "某应用在同一条持续打开的 TCP 连接上传输多条变长二进制消息，"
        "接收端需要逐条恢复原始消息。以下哪种约定能可靠确定消息边界？",
        (
            (("application_length_field", "每条消息前附固定宽度的长度字段，接收方累计读取并按该长度提取消息。"),
             "接收方先累计读足长度字段，再累计读足对应负载，读取边界变化也能恢复消息。"),
            (("segment_delimiter", "把每个 TCP 段的最后一个字节作为一条应用消息的结尾。"),
             "TCP 分段边界与应用消息无固定对应关系。"),
            (("read_delimiter", "把每次读取返回的全部字节作为一条完整的应用消息。"),
             "一次读取可能只有部分消息，也可能包含多条消息的字节。"),
            (("delay_delimiter", "把接收端两次成功读取之间的时间间隔作为消息分隔符。"),
             "发送和到达的时间间隔会变化，TCP 不保证可凭该间隔定位应用消息。"),
        ),
    ),
}


def read_constraints(constraints):
    if not isinstance(constraints, dict) or constraints.keys() - {"scenario"}:
        raise ValueError("constraints 只支持 scenario。")
    scenario = constraints.get("scenario")
    if "scenario" in constraints and (not isinstance(scenario, str) or scenario not in SCENARIOS):
        raise ValueError("scenario 必须是 reads 或 framing。")
    return {"scenario": scenario}


def build(rng, scenario):
    if scenario is None:
        scenario = rng.choice(tuple(SCENARIOS))
    stem, choices = SCENARIOS[scenario]
    supported = [value for value, _ in choices if value[0] in SUPPORTED_CLAIMS]
    expected = supported[0] if len(supported) == 1 else None
    return stem, list(choices), expected, {"scenario": scenario}


def format_choice(value):
    return value[1]
