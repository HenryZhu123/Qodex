from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "训练集" / "标点符号错误_训练集.jsonl"
RESULTS = (
    ROOT
    / "模型输出"
    / "Qwen3.8-Max_标点符号缺完整标准答案_8并发_20260824"
    / "answers.jsonl"
)
OUTPUT = RESULTS.parent / "33条新旧标签冲突题复核报告.md"

GROUPS = {
    "一、名词解释或术语题末标点（7条）": {549, 550, 551, 552, 553, 554, 555},
    "二、题干、选项或判断作答位末尾标点（16条）": {
        660, 743, 744, 757, 819, 880, 886, 887, 897, 977, 983, 987, 988,
        990, 1031, 1032,
    },
    "三、选项编号后的标点样式（2条）": {739, 741},
    "四、冒号、逗号、分号及分句层级（6条）": {828, 829, 893, 968, 969, 1027},
    "五、引号或引文出处边界（2条）": {693, 805},
}


def esc(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


source_rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
result_rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line]
conflicts = [row for row in result_rows if row["status"] == "success" and not row["answer"]["has_error"]]
by_line = {int(row["line_number"]): row for row in conflicts}

lines = [
    "# 标点符号：33 条新旧标签冲突题复核报告",
    "",
    "## 结论",
    "",
    "Qwen 的无错误结论主要来自当前提示词的功能性门槛：只有标点改变题意、句法关系或答题边界才报告；仅违反书面规范、出版习惯或样式统一要求时必须不报告。旧答案的理由则大量使用‘书面规范明显不成立’‘应使用句号/冒号’等规范性标准，因此产生系统性冲突。",
    "",
    "当前提示词中直接导致拒判的规则包括：",
    "",
    "- 孤立术语、题名式题干或普通指令句末的逗号、句号、问号或无标点，只要不改变作答要求，均不报告。",
    "- 题干进入选项前使用何种句末标点不作机械要求；边界仍清楚时不报告。",
    "- 判断题作答位前后的轻微标点差异，只要作答位清楚就不报告。",
    "- 选项编号后的标点字形或样式不同，只有导致选项边界无法识别时才报告。",
    "- 逗号、顿号、分号之间的选择，只有改变并列层级或分句归属时才报告。",
    "- 修改只让文字更规范、更统一或更符合出版习惯时，不成立为错误。",
    "",
]

for heading, line_numbers in GROUPS.items():
    lines.extend(
        [
            f"## {heading}",
            "",
            "| 数据行 | 题型与来源 | 题目 | 旧答案依据 | Qwen 拒判理由 |",
            "|---:|---|---|---|---|",
        ]
    )
    for line_number in sorted(line_numbers):
        result = by_line[line_number]
        source = source_rows[line_number - 1]
        user_text = next(message["content"] for message in source["messages"] if message["role"] == "user")
        payload = json.loads(user_text.split("\n", 1)[1])
        expected_text = next(message["content"] for message in source["messages"] if message["role"] == "assistant")
        expected = json.loads(expected_text)
        old_description = (expected.get("errors") or [{}])[0].get("description", "")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(line_number),
                    esc(payload.get("reference")),
                    esc(payload.get("detection_content")),
                    esc(old_description),
                    esc(result["answer"].get("reason")),
                ]
            )
            + " |"
        )
    lines.append("")

lines.extend(
    [
        "## 初步复核建议",
        "",
        "- 如果目标是检查所有国家标准或出版规范层面的标点错误，应放宽提示词中的‘实际功能影响’门槛；否则这 33 条中的多数应改为负样本。",
        "- 数据行 805 缺少右引号，可能使直接引语范围包含后续作答指令，按现有提示词也有报告依据，建议重点人工复核。",
        "- 数据行 550—553 出现连续两个分号；它们属于明显规范错误，但按当前‘功能性错误’口径仍可能判为无错误，需要先确定产品口径。",
        "- 不建议直接用旧标签覆盖模型结果，也不建议直接接受模型结果；应先统一‘功能性错误’与‘规范性错误’的定义。",
        "",
    ]
)

OUTPUT.write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({"output": str(OUTPUT), "conflicts": len(conflicts)}, ensure_ascii=False))
