from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "训练集-微调版提示词" / "信息缺失_训练集.jsonl"
CHANGES = ROOT / "outputs" / "missing_answer_slot_rebuild_20260827" / "changes.jsonl"
PROMPT_DIR = ROOT / "提示词-新版"
DEFAULT_OUTPUT = ROOT / "outputs" / "qwen38_missing_info_new_prompt_full_20260827"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def compose_prompt() -> str:
    return "\n".join(
        (PROMPT_DIR / name).read_text(encoding="utf-8").strip()
        for name in ("共享核心.txt", "信息缺失.txt", "JSON约束.txt")
    )


def parse_payload(user_content: str) -> dict[str, Any]:
    if "\n" not in user_content:
        raise ValueError("user message has no payload separator")
    return json.loads(user_content.split("\n", 1)[1])


def canonical(value: str) -> str:
    return value.replace("\\n", "\n").replace("\r\n", "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(output_dir: Path) -> None:
    rows = read_jsonl(DATASET)
    changes = sorted(read_jsonl(CHANGES), key=lambda row: int(row["id"]))
    system_prompt = compose_prompt()
    inputs: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []

    for index, change in enumerate(changes, 1):
        source_line = int(change["id"])
        source = rows[source_line - 1]
        source_user = next(message for message in source["messages"] if message["role"] == "user")
        payload = parse_payload(str(source_user["content"]))
        payload["detection_content"] = change["new_error_content"]
        inputs.append({
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": "[INPUT_PAYLOAD]\n" + json.dumps(payload, ensure_ascii=False),
                },
            ]
        })
        manifest.append({
            "request_line": index,
            "source_line": source_line,
            "source_id": str(change["id"]),
            "action": change["action"],
            "expected_has_error": change["action"] != "converted_to_negative",
            "expected_subtype": change.get("new_error_detailed_type", ""),
            "option_label": change.get("option_label", ""),
            "removed_text": change.get("removed_text", ""),
            "detection_content": change["new_error_content"],
            "restored_content": change["standard_answer"],
            "user_content": inputs[-1]["messages"][1]["content"],
        })

    write_jsonl(output_dir / "request_input.jsonl", inputs)
    write_jsonl(output_dir / "request_manifest.jsonl", manifest)
    (output_dir / "prepare_report.json").write_text(
        json.dumps({
            "prepared": len(inputs),
            "positive": sum(row["expected_has_error"] for row in manifest),
            "negative": sum(not row["expected_has_error"] for row in manifest),
            "dataset": str(DATASET),
            "prompt_dir": str(PROMPT_DIR),
            "input": str(output_dir / "request_input.jsonl"),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"prepared": len(inputs), "output_dir": str(output_dir)}, ensure_ascii=False))


def validate_answer(gold: dict[str, Any], answer: Any) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not isinstance(answer, dict):
        return False, ["answer_not_object"]
    if not {"reason", "has_error", "total_errors", "errors"}.issubset(answer):
        return False, ["missing_top_fields"]
    errors = answer.get("errors")
    if not isinstance(errors, list):
        return False, ["errors_not_list"]
    expected = bool(gold["expected_has_error"])
    if answer.get("has_error") is not expected:
        issues.append("false_negative" if expected else "false_positive")
        return False, issues
    if not expected:
        if answer.get("total_errors") != 0 or errors != []:
            issues.append("invalid_negative_shape")
        return not issues, issues
    if answer.get("total_errors") != 1 or len(errors) != 1:
        return False, ["not_single_error"]
    error = errors[0]
    required = {
        "error_type", "position", "original_text", "anchor_text", "correction",
        "description", "suggestion",
    }
    if not required.issubset(error):
        return False, ["missing_error_fields"]
    if error.get("error_type") != "信息缺失":
        issues.append("wrong_error_type")
    content = canonical(str(gold["detection_content"]))
    original = canonical(str(error.get("original_text", "")))
    anchor = canonical(str(error.get("anchor_text", "")))
    correction = str(error.get("correction", "")).strip()
    if not anchor or anchor not in content:
        issues.append("anchor_not_found")
    if original and original not in content:
        issues.append("original_not_found")
    if not correction:
        issues.append("empty_correction")
    removed = str(gold.get("removed_text", ""))
    if removed and removed not in correction and "[缺失内容]" not in correction:
        issues.append("correction_has_neither_target_nor_placeholder")
    return not issues, issues


def evaluate_and_write(output_dir: Path) -> None:
    manifest = read_jsonl(output_dir / "request_manifest.jsonl")
    results = read_jsonl(output_dir / "answers.jsonl")
    latest = {int(row["line_number"]): row for row in results}
    accepted: dict[int, dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []

    for gold in manifest:
        result = latest.get(int(gold["request_line"]), {})
        answer = result.get("answer") if result.get("status") == "success" else None
        valid, issues = validate_answer(gold, answer)
        source_line = int(gold["source_line"])
        if valid:
            accepted[source_line] = {"answer": answer, "user_content": gold["user_content"]}
        audit.append({
            "request_line": gold["request_line"],
            "source_line": source_line,
            "source_id": gold["source_id"],
            "action": gold["action"],
            "expected_has_error": gold["expected_has_error"],
            "status": result.get("status", "missing"),
            "accepted": valid,
            "issues": issues,
            "answer": answer,
        })

    rows = read_jsonl(DATASET)
    backup = output_dir / "信息缺失_训练集_新版提示词写回前备份.jsonl"
    if not backup.exists():
        shutil.copy2(DATASET, backup)
    before_hash = sha256(DATASET)
    system_prompt = compose_prompt()

    for row in rows:
        system = next((message for message in row["messages"] if message["role"] == "system"), None)
        if system is None:
            raise ValueError("system message missing")
        system["content"] = system_prompt

    for source_line, replacement in accepted.items():
        messages = rows[source_line - 1]["messages"]
        user = next(message for message in messages if message["role"] == "user")
        assistant = next(message for message in messages if message["role"] == "assistant")
        user["content"] = replacement["user_content"]
        assistant["content"] = json.dumps(
            replacement["answer"], ensure_ascii=False, separators=(",", ":")
        )

    temp = DATASET.with_suffix(DATASET.suffix + ".tmp")
    write_jsonl(temp, rows)
    temp.replace(DATASET)
    after_hash = sha256(DATASET)
    write_jsonl(output_dir / "writeback_audit.jsonl", audit)

    false_negatives = [row["source_line"] for row in audit if "false_negative" in row["issues"]]
    rejected_other = [
        row["source_line"] for row in audit
        if not row["accepted"] and "false_negative" not in row["issues"]
    ]
    report = {
        "written": True,
        "dataset": str(DATASET),
        "backup": str(backup),
        "requested": len(manifest),
        "accepted_and_written": len(accepted),
        "false_negative_count": len(false_negatives),
        "false_negative_source_lines": false_negatives,
        "other_rejected_count": len(rejected_other),
        "other_rejected_source_lines": rejected_other,
        "sha256_before": before_hash,
        "sha256_after": after_hash,
    }
    (output_dir / "writeback_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "evaluate-write"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "prepare":
        prepare(output_dir)
    else:
        evaluate_and_write(output_dir)


if __name__ == "__main__":
    main()
