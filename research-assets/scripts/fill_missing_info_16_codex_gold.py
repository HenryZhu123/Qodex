from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "训练集-微调版提示词" / "信息缺失_训练集.jsonl"
OUTPUT_DIR = ROOT / "outputs" / "qwen38_missing_info_new_prompt_full_20260827"
MANIFEST = OUTPUT_DIR / "request_manifest.jsonl"
BACKUP = OUTPUT_DIR / "信息缺失_训练集_Codex补写16条前备份.jsonl"
REPORT = OUTPUT_DIR / "Codex补写16条报告.json"


AUTHORED: dict[int, dict[str, str]] = {
    218: {
        "reason": "条件说明后缺少待求物理量，作答横线的对象不明确。",
        "position": "题干末尾逗号后、作答横线前",
        "description": "题干给出总能量与静止能量的关系后直接接“为”及横线，未说明要求填写哪个物理量。",
        "suggestion": "在作答横线前补充待求物理量及其表示要求。",
    },
    301: {
        "reason": "第一步反应箭头的试剂条件槽为空，反应链信息不完整。",
        "position": "第一步反应箭头的方括号内",
        "description": "第一步箭头仅保留空条件槽，而生成物另以(A)作为作答位，缺少驱动该步反应的试剂或条件。",
        "suggestion": "在第一步箭头的方括号内补充缺失的试剂或反应条件。",
    },
    306: {
        "reason": "反应箭头的条件槽为空，无法确定该步反应条件。",
        "position": "反应箭头的方括号内",
        "description": "底物与产物作答位之间的箭头没有任何试剂或条件，反应式的条件结构残缺。",
        "suggestion": "在箭头方括号内补充该反应所需的条件。",
    },
    307: {
        "reason": "反应物结构中出现相邻连接符，中间的结构片段缺失。",
        "position": "反应物“Ph--CO2H”的两个连接符之间",
        "description": "苯基与羧基之间只剩连续两个连接符，表明反应物的中间基团没有显示。",
        "suggestion": "在两个连接符之间补充缺失的结构基团。",
    },
    356: {
        "reason": "句首缺少原则所针对的事项，后续要求没有明确主语。",
        "position": "题干开头“必须坚持”之前",
        "description": "题干直接从“必须坚持”开始列举原则，没有说明这些原则用于制定或处理什么事项。",
        "suggestion": "在句首补充这些原则所对应的对象或工作事项。",
    },
    371: {
        "reason": "判断题的结论部分缺失，题干在逗号后直接进入判断位。",
        "position": "“配水流速小”之后、判断括号之前",
        "description": "题干只给出沉淀池的配水特征，末尾逗号后没有完整陈述其作用或结果。",
        "suggestion": "在判断括号前补充由上述配水特征得出的完整结论。",
    },
    372: {
        "reason": "预处理的具体操作或目的缺失，判断陈述没有结束。",
        "position": "“一般需要采用预处理”之后、判断括号之前",
        "description": "题干提出需要预处理后以逗号中断，未说明预处理需要去除的对象或采取的操作。",
        "suggestion": "补充预处理的具体内容，使判断陈述完整后再接判断括号。",
    },
    379: {
        "reason": "分类对象的承接成分缺失，四种类型所指对象不够明确。",
        "position": "条件状语结束后、“可分为”之前",
        "description": "题干给出分类依据后直接出现“可分为”，缺少被分类对象及必要的承接表达。",
        "suggestion": "在“可分为”之前补充分类对象和承接成分。",
    },
    403: {
        "reason": "定义句缺少主语，无法确定何种对象由数字化得到。",
        "position": "题干开头“是由”之前",
        "description": "题干从“是由”开始，缺少被定义对象，后文的图像数字化步骤无法与句首建立完整关系。",
        "suggestion": "在句首补充被定义的对象名称。",
    },
    437: {
        "reason": "作答位要求填写的内容类型缺失，题目任务不明确。",
        "position": "化合物名称之后、“为”之前",
        "description": "题干只给出化合物名称和作答位，没有说明要求填写结构式、分子式或其他内容。",
        "suggestion": "在“为”之前补充明确的作答内容类型。",
    },
    438: {
        "reason": "加成反应加号后的第二反应物缺失，反应式不完整。",
        "position": "反应式加号之后、反应箭头之前",
        "description": "反应式保留了加号，却没有显示与丁二烯共同反应的另一反应物。",
        "suggestion": "在加号后补充缺失的第二反应物。",
    },
    456: {
        "reason": "第一个作答位前缺少比较维度，无法判断应填写哪种传动。",
        "position": "“三种齿轮传动中”之后、第④作答位之前",
        "description": "后半句明确询问承载能力最低者，但与之对应的第一个作答位前没有说明要比较的另一极值。",
        "suggestion": "在第④作答位前补充完整的比较项目。",
    },
    458: {
        "reason": "判断题在逗号后截断，棉纤维形态的后续特征缺失。",
        "position": "“纵向呈棒状”之后、判断括号之前",
        "description": "题干在形态描述后保留逗号，却直接进入判断位，表明并列的后续特征没有显示。",
        "suggestion": "在判断括号前补充缺失的后续形态描述并结束句子。",
    },
    459: {
        "reason": "并列比较的第二项缺失，判断陈述在逗号后中断。",
        "position": "“具有‘合成羊毛’之称的纤维是腈纶”之后",
        "description": "题干给出第一组纤维别称关系后保留逗号，却没有出现与之并列的另一组陈述。",
        "suggestion": "在判断括号前补充缺失的并列陈述并结束句子。",
    },
    460: {
        "reason": "判断陈述的并列后半句缺失，题干在逗号后直接结束。",
        "position": "“主要成分相同”之后、判断括号之前",
        "description": "当前文本只保留第一项比较结论，末尾逗号显示后续并列性质被截断。",
        "suggestion": "在逗号后补充缺失的并列性质，再接判断括号。",
    },
    465: {
        "reason": "适用场合的举例内容缺失，题干在逗号后直接进入判断位。",
        "position": "“拉伸性和弹性大的场合”之后",
        "description": "题干以逗号引出后续内容，但没有给出具体场合或例子，陈述结构没有正常结束。",
        "suggestion": "在判断括号前补充缺失的适用场合示例并结束句子。",
    },
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def insertion_diff(detection: str, restored: str) -> tuple[int, str]:
    prefix = 0
    while prefix < min(len(detection), len(restored)) and detection[prefix] == restored[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < len(detection) - prefix
        and suffix < len(restored) - prefix
        and detection[-1 - suffix] == restored[-1 - suffix]
    ):
        suffix += 1
    visible = detection[prefix:len(detection) - suffix if suffix else len(detection)]
    missing = restored[prefix:len(restored) - suffix if suffix else len(restored)]
    if visible:
        raise ValueError("expected a pure insertion construction")
    return prefix, missing


def unique_context(text: str, point: int, left: int, right: int) -> tuple[str, int, int]:
    start = max(0, point - left)
    end = min(len(text), point + right)
    while text.count(text[start:end]) != 1 and (start > 0 or end < len(text)):
        start = max(0, start - 2)
        end = min(len(text), end + 2)
    return text[start:end], start, end


def build_answer(gold: dict[str, Any]) -> dict[str, Any]:
    source_line = int(gold["source_line"])
    authored = AUTHORED[source_line]
    detection = str(gold["detection_content"])
    point, missing = insertion_diff(detection, str(gold["restored_content"]))
    if missing != str(gold["removed_text"]):
        raise ValueError(f"line {source_line}: manifest deletion mismatch")

    original, start, end = unique_context(detection, point, 8, 8)
    relative = point - start
    correction = original[:relative] + "[缺失内容]" + original[relative:]
    anchor, _, _ = unique_context(detection, point, 22, 22)
    if original not in detection or anchor not in detection:
        raise ValueError(f"line {source_line}: generated context is not searchable")

    return {
        "reason": authored["reason"],
        "has_error": True,
        "total_errors": 1,
        "errors": [{
            "error_type": "信息缺失",
            "position": authored["position"],
            "original_text": original,
            "anchor_text": anchor,
            "correction": correction,
            "description": authored["description"],
            "suggestion": authored["suggestion"],
        }],
    }


def main() -> None:
    rows = read_jsonl(DATASET)
    before_rows = json.loads(json.dumps(rows, ensure_ascii=False))
    manifest = {int(row["source_line"]): row for row in read_jsonl(MANIFEST)}
    target_ids = sorted(AUTHORED)
    if set(target_ids) - set(manifest):
        raise ValueError("target id missing from request manifest")

    shutil.copy2(DATASET, BACKUP)
    before_hash = digest(DATASET)
    answers: dict[int, dict[str, Any]] = {}
    for source_line in target_ids:
        gold = manifest[source_line]
        answer = build_answer(gold)
        answers[source_line] = answer
        messages = rows[source_line - 1]["messages"]
        user = next(message for message in messages if message["role"] == "user")
        assistant = next(message for message in messages if message["role"] == "assistant")
        user["content"] = gold["user_content"]
        assistant["content"] = json.dumps(answer, ensure_ascii=False, separators=(",", ":"))

    for index, (before, after) in enumerate(zip(before_rows, rows), 1):
        if index not in AUTHORED and before != after:
            raise ValueError(f"unexpected change outside target rows: {index}")

    for source_line, answer in answers.items():
        gold = manifest[source_line]
        detection = str(gold["detection_content"])
        error = answer["errors"][0]
        if error["original_text"] not in detection or error["anchor_text"] not in detection:
            raise ValueError(f"line {source_line}: final localization invalid")
        if "[缺失内容]" not in error["correction"]:
            raise ValueError(f"line {source_line}: placeholder missing")

    temporary = DATASET.with_suffix(DATASET.suffix + ".tmp")
    write_jsonl(temporary, rows)
    temporary.replace(DATASET)
    after_hash = digest(DATASET)
    report = {
        "written": True,
        "dataset": str(DATASET),
        "backup": str(BACKUP),
        "updated_count": len(target_ids),
        "updated_source_lines": target_ids,
        "unchanged_non_target_rows": len(rows) - len(target_ids),
        "sha256_before": before_hash,
        "sha256_after": after_hash,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
