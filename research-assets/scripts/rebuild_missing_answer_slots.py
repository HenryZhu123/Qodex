#!/usr/bin/env python3
"""Rebuild invalid answer-slot positives in the missing-information workbook."""

from __future__ import annotations

import argparse
import collections
import json
import random
import re
import shutil
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET


NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
FORMULA_ANSWER_SLOT_IDS = {
    "218", "232", "254", "276", "299", "300", "301",
    "303", "304", "306", "307", "377", "436", "438",
}
ANSWER_SLOT_TYPES = {"下划线缺失", "括号或作答标记缺失"}
FORMULA_DELETIONS = {
    "218": r"\mathrm{d}t",
    "254": r"j\omega",
    "276": r"\vec{b}",
    "299": "NaOH-H_2O_2",
    "300": "NBS",
    "301": "Li",
    "303": "Al2O3",
    "304": "Br2",
    "306": "Heating",
    "307": "CO-R",
    "436": r"0.771\ \text{V}",
    "438": "NC-CH=CH2",
}


def column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref)
    if not letters:
        raise ValueError(f"Invalid cell reference: {cell_ref}")
    value = 0
    for char in letters.group():
        value = value * 26 + ord(char) - 64
    return value - 1


def column_letters(index: int) -> str:
    value = index + 1
    chars: list[str] = []
    while value:
        value, rem = divmod(value - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    value = cell.find(NS + "v")
    if cell.get("t") == "s" and value is not None:
        return shared_strings[int(value.text or "0")]
    if cell.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(NS + "t"))
    return value.text if value is not None and value.text is not None else ""


def load_workbook_rows(path: Path) -> tuple[dict[str, bytes], ET.Element, list[str], list[dict[str, str]]]:
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    shared_root = ET.fromstring(members["xl/sharedStrings.xml"])
    shared_strings = [
        "".join(node.text or "" for node in item.iter(NS + "t"))
        for item in shared_root.findall(NS + "si")
    ]
    sheet_root = ET.fromstring(members["xl/worksheets/sheet1.xml"])
    xml_rows = sheet_root.findall(".//" + NS + "row")
    raw_rows: list[dict[int, str]] = []
    for row in xml_rows:
        raw_rows.append({
            column_index(cell.get("r", "")): cell_value(cell, shared_strings)
            for cell in row.findall(NS + "c")
        })
    header = [raw_rows[0].get(i, "") for i in range(max(raw_rows[0]) + 1)]
    records = [
        {header[i]: raw.get(i, "") for i in range(len(header))}
        for raw in raw_rows[1:]
    ]
    return members, sheet_root, header, records


def set_cell(row: ET.Element, index: int, value: str | int) -> None:
    row_number = row.get("r")
    ref = f"{column_letters(index)}{row_number}"
    cells = list(row.findall(NS + "c"))
    target = next((cell for cell in cells if cell.get("r") == ref), None)
    if target is None:
        target = ET.Element(NS + "c", {"r": ref})
        insert_at = len(cells)
        for position, cell in enumerate(cells):
            if column_index(cell.get("r", "")) > index:
                insert_at = position
                break
        row.insert(insert_at, target)
    for child in list(target):
        target.remove(child)
    if isinstance(value, int):
        target.set("t", "n")
        ET.SubElement(target, NS + "v").text = str(value)
    else:
        target.set("t", "inlineStr")
        inline = ET.SubElement(target, NS + "is")
        text = ET.SubElement(inline, NS + "t")
        if value[:1].isspace() or value[-1:].isspace() or "\n" in value:
            text.set(XML_SPACE, "preserve")
        text.text = value


OPTION_PATTERN = re.compile(
    r"(?:[（(]\s*(?P<paren>[A-EＡ-Ｅ])\s*[）)]|"
    r"(?<![A-Za-z0-9])(?P<plain>[A-EＡ-Ｅ])\s*[、.．])"
)


def option_matches(content: str) -> list[tuple[str, re.Match[str]]]:
    matches: list[tuple[str, re.Match[str]]] = []
    for match in OPTION_PATTERN.finditer(content):
        label = match.group("paren") or match.group("plain") or ""
        label = chr(ord(label) - 0xFEE0) if "Ａ" <= label <= "Ｅ" else label
        matches.append((label, match))
    # Use the final complete A-B-C-D chain to avoid formula variables earlier in the stem.
    for start in range(len(matches)):
        chain = matches[start:start + 4]
        if [label for label, _ in chain] == ["A", "B", "C", "D"]:
            return chain + ([matches[start + 4]] if start + 4 < len(matches) and matches[start + 4][0] == "E" else [])
    return []


def rebuild_option(record: dict[str, str], target_label: str) -> dict[str, str] | None:
    content = record["content"]
    matches = option_matches(content)
    if len(matches) < 4:
        return None
    target_index = next((i for i, (label, _) in enumerate(matches) if label == target_label), -1)
    if target_index < 0:
        return None
    _, target = matches[target_index]
    end = matches[target_index + 1][1].start() if target_index + 1 < len(matches) else len(content)
    removed = content[target.end():end]
    if not removed.strip():
        return None
    error_content = content[:target.end()] + content[end:]
    label_text = content[target.start():target.end()]
    return {
        "error_content": error_content,
        "error_detailed_type": "选项信息缺失",
        "correction": f"原文：{label_text}{removed} -> 错误：{label_text}",
        "design_reason": f"选项{target_label}的标号仍在，但其内容整体缺失，当前题面可直接看到选项结构断档。",
        "removed_text": removed,
        "option_label": target_label,
    }


ANSWER_SLOT_PATTERN = re.compile(
    r"[_＿]{2,}|\\underline\s*\{|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫]|[（(]\s*[）)]"
)


def rebuild_core_question(record: dict[str, str]) -> dict[str, str] | None:
    content = record["content"]
    slot = ANSWER_SLOT_PATTERN.search(content)
    removed = ""
    start = end = -1
    if "填空" in record["title"] and slot:
        # “____称为术语”类：保留作答位，删除被定义的核心对象。
        after_slot = content[slot.end():]
        definition = re.search(r"称为(?P<term>[^，。；,;]+)", after_slot)
        if definition and definition.group("term").strip():
            start = slot.end() + definition.start("term")
            end = slot.end() + definition.end("term")
        else:
            prefix = content[:slot.start()]
            connectors = list(re.finditer(r"又称为|称为|可分为|分为|主要包括|包括|必须坚持|主要是|是|为|有", prefix))
            if connectors:
                connector = connectors[-1]
                if slot.start() - connector.end() <= 40 and record["id"] not in {"316"}:
                    boundary = max(prefix.rfind(mark, 0, connector.start()) for mark in "，。；,;\n")
                    start = boundary + 1
                    end = connector.start()
    elif "判断" in record["title"] and slot:
        prefix = content[:slot.start()]
        boundary = max(prefix.rfind(mark) for mark in "，,；;" )
        if boundary >= 0:
            start = boundary + 1
            end = slot.start()
    if start < 0 or end <= start:
        return None
    removed = content[start:end]
    if len(re.sub(r"\s+", "", removed)) < 2 or is_answer_slot_only(removed):
        return None
    error_content = content[:start] + content[end:]
    valid, actual_removed = one_block_deletion(content, error_content)
    if not valid or actual_removed != removed:
        return None
    return {
        "error_content": error_content,
        "error_detailed_type": "题干核心提问成分缺失",
        "correction": f"原文：{removed} -> 错误：[该核心提问成分缺失]",
        "design_reason": "题干保留了作答位置，但被问对象或待判断的核心陈述成分整块缺失，仅补作答位仍无法恢复完整题意。",
        "removed_text": removed,
    }


def one_block_deletion(original: str, broken: str) -> tuple[bool, str]:
    prefix = 0
    limit = min(len(original), len(broken))
    while prefix < limit and original[prefix] == broken[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < len(original) - prefix
        and suffix < len(broken) - prefix
        and original[-1 - suffix] == broken[-1 - suffix]
    ):
        suffix += 1
    original_end = len(original) - suffix if suffix else len(original)
    reconstructed = original[:prefix] + original[original_end:]
    return reconstructed == broken, original[prefix:original_end]


def is_answer_slot_only(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    compact = re.sub(r"\\(?:underline|quad|qquad|hspace)\b", "", compact)
    compact = compact.replace("{", "").replace("}", "")
    compact = re.sub(r"^[（(\[【]?[A-EＡ-Ｅ①②③④⑤⑥⑦⑧⑨⑩⑪⑫][）)\]】]?$", "", compact)
    compact = re.sub(r"[_＿—－（）()\[\]【】①②③④⑤⑥⑦⑧⑨⑩⑪⑫、.．:：;；$]", "", compact)
    return not compact


def rebuild_formula(record: dict[str, str]) -> dict[str, str] | None:
    removed = FORMULA_DELETIONS.get(record["id"])
    if not removed or record["content"].count(removed) != 1:
        return None
    error_content = record["content"].replace(removed, "", 1)
    valid, actual_removed = one_block_deletion(record["content"], error_content)
    if not valid or actual_removed != removed or is_answer_slot_only(removed):
        return None
    return {
        "error_content": error_content,
        "error_detailed_type": "公式缺失",
        "correction": f"原文：{removed} -> 错误：[该公式成分缺失]",
        "design_reason": "已给公式中的必要结构成分被整段删除，形成可直接观察到的运算项、关系项或反应结构断档。",
        "removed_text": removed,
    }


def counts(records: list[dict[str, str]]) -> dict[str, object]:
    positives = [record for record in records if str(record["error_cnt"]) != "0"]
    subtype_counts = dict(sorted(collections.Counter(
        record["error_detailed_type"] for record in positives
    ).items()))
    return {
        "total": len(records),
        "positive": len(positives),
        "negative": len(records) - len(positives),
        "positive_ratio": round(len(positives) / len(records), 6),
        "negative_ratio": round((len(records) - len(positives)) / len(records), 6),
        "subtypes": subtype_counts,
        "subtype_ratios_within_positive": {
            key: round(value / len(positives), 6) for key, value in subtype_counts.items()
        },
    }


def write_workbook(path: Path, members: dict[str, bytes], sheet_root: ET.Element) -> None:
    members = dict(members)
    members["xl/worksheets/sheet1.xml"] = ET.tostring(sheet_root, encoding="utf-8", xml_declaration=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, default=Path("数据集/信息缺失完整数据集.xlsx"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/missing_answer_slot_rebuild_20260827"))
    args_cli = parser.parse_args()

    workbook = args_cli.workbook.resolve()
    output_dir = args_cli.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    backup = workbook.with_name(workbook.stem + "_正常作答位改造前备份_20260827.xlsx")
    if not backup.exists():
        shutil.copy2(workbook, backup)

    source_workbook = backup if backup.exists() else workbook
    members, sheet_root, header, records = load_workbook_rows(source_workbook)
    before = counts(records)
    affected = [
        record for record in records
        if record["error_detailed_type"] in ANSWER_SLOT_TYPES or record["id"] in FORMULA_ANSWER_SLOT_IDS
    ]

    record_by_id = {record["id"]: record for record in records}
    changes: list[dict[str, object]] = []
    formula_candidates = set(FORMULA_DELETIONS)
    option_ids = [record["id"] for record in affected if len(option_matches(record["content"])) >= 4]
    shuffled_option_ids = option_ids[:]
    random.Random(20260827).shuffle(shuffled_option_ids)
    option_assignment = {
        record_id: "ABCD"[index % 4]
        for index, record_id in enumerate(shuffled_option_ids)
    }

    for position, record in enumerate(affected, 1):
        old = {
            "error_content": record["error_content"],
            "error_detailed_type": record["error_detailed_type"],
            "error_cnt": record["error_cnt"],
        }
        replacement = rebuild_option(record, option_assignment.get(record["id"], "D"))
        action = "reconstructed_option"
        if replacement is None and record["id"] in formula_candidates:
            print(f"[{position}/{len(affected)}] formula rebuild id={record['id']}", flush=True)
            replacement = rebuild_formula(record)
            action = "reconstructed_formula"
        if replacement is None:
            replacement = rebuild_core_question(record)
            action = "reconstructed_core_question"
        if replacement is None:
            action = "converted_to_negative"
            record.update({
                "error_content": record["content"],
                "error_cnt": "0",
                "error_detailed_type": "",
                "correction": "",
                "design_reason": "",
                "is_content_same": "1",
                "is_real_error": "0",
                "corrected_content": record["content"],
                "model_name": "Codex规则清洗-20260827",
            })
            removed_text = ""
        else:
            record.update({
                "error_content": replacement["error_content"],
                "error_cnt": "1",
                "error_detailed_type": replacement["error_detailed_type"],
                "correction": replacement["correction"],
                "design_reason": replacement["design_reason"],
                "is_content_same": "0",
                "is_real_error": "1",
                "corrected_content": record["content"],
                "model_name": "Codex规则清洗-20260827",
            })
            removed_text = replacement["removed_text"]
        changes.append({
            "id": record["id"],
            "action": action,
            "old": old,
            "new_error_detailed_type": record["error_detailed_type"],
            "removed_text": removed_text,
            "option_label": replacement.get("option_label", "") if replacement else "",
            "new_error_content": record["error_content"],
            "standard_answer": record["corrected_content"],
        })

    xml_rows = sheet_root.findall(".//" + NS + "row")
    header_index = {name: i for i, name in enumerate(header)}
    changed_ids = {str(change["id"]) for change in changes}
    for row_element, original_record in zip(xml_rows[1:], records):
        if original_record["id"] not in changed_ids:
            continue
        record = record_by_id[original_record["id"]]
        for field in (
            "error_content", "error_cnt", "error_detailed_type", "correction",
            "design_reason", "is_content_same", "is_real_error", "corrected_content", "model_name",
        ):
            value: str | int = record[field]
            if field in {"error_cnt", "is_content_same", "is_real_error"}:
                value = int(value)
            set_cell(row_element, header_index[field], value)

    after = counts(records)
    report = {
        "workbook": str(workbook),
        "backup": str(backup),
        "images_modified": 0,
        "affected_answer_slot_records": len(changes),
        "actions": dict(collections.Counter(str(change["action"]) for change in changes)),
        "deleted_option_labels": dict(sorted(collections.Counter(
            str(change["option_label"]) for change in changes if change["option_label"]
        ).items())),
        "standard_answers_filled": len(changes),
        "before": before,
        "after": after,
    }
    write_workbook(workbook, members, sheet_root)
    (output_dir / "changes.jsonl").write_text(
        "".join(json.dumps(change, ensure_ascii=False) + "\n" for change in changes),
        encoding="utf-8",
    )
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
