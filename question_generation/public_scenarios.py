"""Trusted renderers and solvers for finite, student-visible scenarios."""

from __future__ import annotations

from .verification import integer


FORWARDING = {
    "none": "无转发",
    "alu": "仅 EX/MEM→EX 转发 ALU 结果",
    "full": "EX/MEM→EX 转发 ALU 结果，MEM/WB→EX 转发 ALU 与 Load 结果",
}

ACK_RULES = {
    "packet_sequence": "回收到分组的线上序号",
    "receive_base_minus_one": "回（当前接收窗口基号−1）模 M",
}


def fields(value, expected):
    if not isinstance(value, dict) or value.keys() != expected:
        raise ValueError("可复算场景字段不符合契约。")


def pipeline(inputs):
    fields(inputs, {"instructions", "write_before_read", "forwarding"})
    instructions, write_first, modes = (inputs[k] for k in ("instructions", "write_before_read", "forwarding"))
    if (type(write_first) is not bool or not isinstance(instructions, list) or not 2 <= len(instructions) <= 12
            or not isinstance(modes, list) or not 1 <= len(modes) <= 3
            or any(not isinstance(mode, str) or mode not in FORWARDING for mode in modes)
            or len(set(modes)) != len(modes)):
        raise ValueError("流水线指令数、寄存器读写时序或转发配置无效。")
    rows = []
    for index, instruction in enumerate(instructions, 1):
        fields(instruction, {"op", "dest", "sources"})
        op, dest, sources = (instruction[k] for k in ("op", "dest", "sources"))
        if (op not in ("alu", "load") or not isinstance(sources, list)
                or not 1 <= len(sources) <= (1 if op == "load" else 2)):
            raise ValueError("只支持 ALU 指令及以单寄存器为基址的 Load。")
        integer(dest, 0, 31)
        source_names = "、".join(f"R{integer(reg, 0, 31)}" for reg in sources)
        rows.append(f"I{index}：{'ALU' if op == 'alu' else 'Load'}，读 {source_names}，写 R{dest}。")
    read_rule = "WB 同周期写后 ID 可以读到新值" if write_first else "ID 最早在 WB 的下一周期读到新值"
    stem = (
        "处理器采用 IF、ID、EX、MEM、WB 五级顺序流水线，每级一周期。I1 在第 1 周期进入 IF。"
        "忽略结构与控制冲突，寄存器均可读写，ID 读取操作数，依赖未满足时只停到最早可执行周期。"
        f"{read_rule}。转发值只能在对应流水寄存器持有它的那个周期供 EX 使用，不另行保存。"
        "ALU 结果在 EX 末进入 EX/MEM，Load 结果在 MEM 末进入 MEM/WB。\n"
        + "\n".join(rows) + "\n" + "\n".join(f"配置 {mode}：{FORWARDING[mode]}。" for mode in modes)
    )
    answers = {}
    # If a consumer enters EX at c, its ID read is at c-1. The producer
    # writes in EX+2, so an unforwarded value needs a gap of 3 or 4.
    register_gap = 3 if write_first else 4
    for mode in modes:
        previous, cycles = {}, []
        for instruction in instructions:
            producers = [previous[reg] for reg in instruction["sources"] if reg in previous]
            cycle = cycles[-1] + 1 if cycles else 3
            while not all(
                cycle - issued >= register_gap
                or (cycle - issued == 1 and producer == "alu" and mode in ("alu", "full"))
                or (cycle - issued == 2 and mode == "full")
                for issued, producer in producers
            ):
                cycle += 1
            cycles.append(cycle)
            previous[instruction["dest"]] = (cycle, instruction["op"])
        answers[f"{mode}.ex"] = (f"配置 {mode} 下各指令进入 EX 的周期（按指令顺序）", cycles)
        answers[f"{mode}.total"] = (f"配置 {mode} 下末条指令完成 WB 的周期", cycles[-1] + 2)
    return stem, answers


def selective_repeat(inputs):
    fields(inputs, {"modulus", "window", "outside_ack", "events"})
    modulus = integer(inputs["modulus"], 2, 32)
    width = integer(inputs["window"], 1, modulus - 1)
    ack_rule, events = inputs["outside_ack"], inputs["events"]
    if (not isinstance(ack_rule, str) or ack_rule not in ACK_RULES
            or not isinstance(events, list) or not 2 <= len(events) <= 24):
        raise ValueError("重传场景的窗口外 ACK 规则或事件数无效。")

    send_base = receive_base = next_packet = 0
    acknowledged, buffered, delivered = set(), {}, []
    rows, answers = [], {}
    for step, event in enumerate(events, 1):
        fields(event, {"packet", "ack_lost"})
        packet = integer(event["packet"], 0, next_packet)
        lost = event["ack_lost"]
        if type(lost) is not bool:
            raise ValueError("ACK 丢失标记须为布尔值。")
        rows.append(f"事件 {step}：尝试发送编号 {packet} 的分组；若产生 ACK，则{'丢失' if lost else '立即到达'}。")
        sent = send_base <= packet < send_base + width and packet not in acknowledged
        ack = None
        if sent:
            if packet == next_packet:
                next_packet += 1
            sequence = packet % modulus
            if (sequence - receive_base) % modulus < width:
                ack = sequence
                buffered.setdefault(sequence, packet)
                while receive_base % modulus in buffered:
                    delivered.append(buffered.pop(receive_base % modulus))
                    receive_base += 1
            else:
                ack = sequence if ack_rule == "packet_sequence" else (receive_base - 1) % modulus
            if not lost:
                # The window is smaller than the sequence space, so there is
                # at most one sent packet with this wire sequence in the window.
                match = send_base + (ack - send_base) % modulus
                if match < next_packet:
                    acknowledged.add(match)
                    while send_base in acknowledged:
                        acknowledged.remove(send_base)
                        send_base += 1

        answers[f"e{step}.sent"] = (f"事件 {step} 是否实际发出分组", sent)
        answers[f"e{step}.ack"] = (f"事件 {step} 接收方生成的线上 ACK 序号（没有则写无）", ack)
        answers[f"e{step}.send_base"] = (f"事件 {step} 后发送窗口基号", send_base)
        answers[f"e{step}.receive_base"] = (f"事件 {step} 后接收窗口基号", receive_base)
        answers[f"e{step}.delivered"] = (f"截至事件 {step} 已交付的分组编号（按交付顺序）", delivered.copy())

    stem = (
        f"考虑简化的选择重传机制。线上序号为分组编号模 M，M={modulus}，发送和接收窗口长度均为 {width}。"
        "分组编号与窗口基号从 0 开始按绝对编号计，初始缓存为空，无在途分组。"
        "发送方只能按编号发送窗口内下一个新分组，或重传窗口内已发但未确认的分组；其他发送尝试无效。"
        "接收方按当前窗口基号计算模 M 窗口。收到窗口内分组时按线上序号缓存（已有缓存则保留原包），"
        "回该序号 ACK，并从窗口起点连续交付已有缓存、前移基号。"
        f"收到窗口外分组时丢弃，{ACK_RULES[ack_rule]}。"
        "收到 ACK 后，只标记与该线上序号对应的已发未移出窗口分组；连续确认窗口头部时发送窗口前移。"
        "实际发出的分组在该事件内立即到达，接收方按上述规则处理；ACK 按事件说明到达或丢失。"
        "除列出的事件外没有其他发送、重传或 ACK。\n" + "\n".join(rows)
    )
    return stem, answers


SCENARIOS = {"pipeline": pipeline, "selective_repeat": selective_repeat}

SCENARIO_FORMATS = {
    "pipeline": """inputs={"instructions":[{"op":"load或alu","dest":1,"sources":[2]}],
"write_before_read":false,"forwarding":["none","alu","full"]}。2至12条指令，寄存器编号0至31，Load恰读一个基址寄存器。
流水线依次IF/ID/EX/MEM/WB，首条IF=1。WB先写时ID可同周期读，否则次周期。无结构和控制冲突。
none无转发；alu仅EX/MEM→EX转发ALU；full另有MEM/WB→EX。转发只在对应寄存器持有值的当周期有效。
选用已声明配置的目标，例如full.ex（各指令EX周期数组）、full.total（末条WB周期）。""",
    "selective_repeat": """inputs={"modulus":8,"window":4,"outside_ack":"packet_sequence或receive_base_minus_one",
"events":[{"packet":0,"ack_lost":true}]}。2至24个事件。编号、窗口基号从0开始按绝对编号计，线上序号按modulus取模。
按事件尝试发下一个窗口内新分组，或重传窗口内已发未确认分组，实际发出的分组当场到达。
接收方缓存窗口内序号（已缓存时保留原包），回该序号ACK，连续交付后前移窗口。窗口外丢弃，按outside_ack回收到包的序号或当前接收基号减一取模。
ACK未丢失时标记对应已发分组，发送窗口跳过连续已确认头部。没有其他事件。
第i个事件可问ei.sent（布尔）、ei.ack（整数或null）、ei.send_base、ei.receive_base（整数）、ei.delivered（累计交付的绝对分组编号数组）。
例如第3个事件后发送基号的目标为e3.send_base。避免把一条有限轨迹推广成协议全局活性结论。""",
}
