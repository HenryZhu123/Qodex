from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT / "训练集-微调版提示词" / "信息缺失_训练集.jsonl"
CHANGES = ROOT / "outputs" / "missing_answer_slot_rebuild_20260827" / "changes.jsonl"
DEFAULT_PROMPT_DIR = ROOT / "提示词-微调版"
DEFAULT_DIR = ROOT / "outputs" / "qwen38_missing_info_small_test_20260827"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def compose_system_prompt(prompt_dir: Path) -> str:
    names = ["共享核心.txt", "信息缺失.txt", "JSON约束.txt"]
    return "\n".join((prompt_dir / name).read_text(encoding="utf-8").strip() for name in names)


def parse_user(message: dict[str, Any]) -> dict[str, Any]:
    content = str(message["content"])
    if "\n" not in content:
        raise ValueError("invalid user message")
    return json.loads(content.split("\n", 1)[1])


def choose_samples(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    option_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for change in changes:
        action = str(change["action"])
        groups[action].append(change)
        if action == "reconstructed_option":
            option_groups[str(change["option_label"])].append(change)

    selected: list[dict[str, Any]] = []
    for label in "ABCD":
        selected.extend(sorted(option_groups[label], key=lambda row: int(row["id"]))[:2])
    selected.extend(sorted(groups["reconstructed_core_question"], key=lambda row: int(row["id"]))[:6])
    selected.extend(sorted(groups["reconstructed_formula"], key=lambda row: int(row["id"]))[:6])
    selected.extend(sorted(groups["converted_to_negative"], key=lambda row: int(row["id"]))[:4])
    return sorted(selected, key=lambda row: int(row["id"]))


def prepare(output_dir: Path, prompt_dir: Path) -> None:
    training_rows = read_jsonl(TRAINING)
    changes = read_jsonl(CHANGES)
    selected = choose_samples(changes)
    system_prompt = compose_system_prompt(prompt_dir)

    inputs: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for change in selected:
        line_number = int(change["id"])
        source = training_rows[line_number - 1]
        source_system = next(message for message in source["messages"] if message["role"] == "system")
        if prompt_dir.resolve() == DEFAULT_PROMPT_DIR.resolve() and source_system["content"] != system_prompt:
            raise ValueError(f"line {line_number}: system prompt mismatch")
        source_user = next(message for message in source["messages"] if message["role"] == "user")
        payload = parse_user(source_user)
        payload["detection_content"] = change["new_error_content"]
        user_content = "[INPUT_PAYLOAD]\n" + json.dumps(payload, ensure_ascii=False)
        inputs.append({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        })
        gold.append({
            "probe_line": len(inputs),
            "source_line": line_number,
            "source_id": str(change["id"]),
            "action": change["action"],
            "expected_has_error": change["action"] != "converted_to_negative",
            "expected_subtype": change.get("new_error_detailed_type", ""),
            "option_label": change.get("option_label", ""),
            "removed_text": change.get("removed_text", ""),
            "detection_content": change["new_error_content"],
            "restored_content": change["standard_answer"],
        })

    write_jsonl(output_dir / "probe_input.jsonl", inputs)
    write_jsonl(output_dir / "probe_gold.jsonl", gold)
    print(json.dumps({
        "prepared": len(inputs),
        "input": str(output_dir / "probe_input.jsonl"),
        "gold": str(output_dir / "probe_gold.jsonl"),
        "source_lines": [row["source_line"] for row in gold],
    }, ensure_ascii=False, indent=2))


def normalize(value: str) -> str:
    return "".join(value.replace("\\n", "\n").split())


def evaluate(output_dir: Path) -> None:
    gold_rows = read_jsonl(output_dir / "probe_gold.jsonl")
    result_rows = read_jsonl(output_dir / "answers.jsonl")
    latest = {int(row["line_number"]): row for row in result_rows}
    details: list[dict[str, Any]] = []

    for gold in gold_rows:
        probe_line = int(gold["probe_line"])
        result = latest.get(probe_line, {})
        answer = result.get("answer") if result.get("status") == "success" else None
        issues: list[str] = []
        schema_valid = isinstance(answer, dict)
        classification_correct = False
        localization_valid = False
        exact_restoration = False
        if not schema_valid:
            issues.append("generation_failed_or_not_object")
        else:
            required_top = {"reason", "has_error", "total_errors", "errors"}
            if not required_top.issubset(answer) or not isinstance(answer.get("errors"), list):
                schema_valid = False
                issues.append("invalid_top_schema")
            else:
                classification_correct = answer.get("has_error") is gold["expected_has_error"]
                if not classification_correct:
                    issues.append("wrong_has_error")
                errors = answer.get("errors", [])
                if gold["expected_has_error"]:
                    if answer.get("total_errors") != 1 or len(errors) != 1:
                        issues.append("not_single_error")
                    elif errors[0].get("error_type") != "信息缺失":
                        issues.append("wrong_error_type")
                    else:
                        error = errors[0]
                        original = str(error.get("original_text", ""))
                        anchor = str(error.get("anchor_text", ""))
                        correction = str(error.get("correction", ""))
                        content = str(gold["detection_content"])
                        localization_valid = bool(anchor) and anchor in content and (not original or original in content)
                        if not localization_valid:
                            issues.append("invalid_localization")
                        if original and original in content and correction:
                            repaired = content.replace(original, correction, 1)
                            exact_restoration = normalize(repaired) == normalize(str(gold["restored_content"]))
                        if not exact_restoration:
                            issues.append("not_exact_restoration")
                else:
                    if answer.get("total_errors") != 0 or errors != []:
                        issues.append("invalid_negative_shape")
                    localization_valid = classification_correct
                    exact_restoration = classification_correct

        details.append({
            **gold,
            "generation_status": result.get("status", "missing"),
            "schema_valid": schema_valid,
            "classification_correct": classification_correct,
            "localization_valid": localization_valid,
            "exact_restoration": exact_restoration,
            "issues": issues,
            "answer": answer,
        })

    def count(field: str) -> int:
        return sum(bool(row[field]) for row in details)

    by_action: dict[str, dict[str, int]] = {}
    for action in sorted({str(row["action"]) for row in details}):
        scoped = [row for row in details if row["action"] == action]
        by_action[action] = {
            "total": len(scoped),
            "classification_correct": sum(row["classification_correct"] for row in scoped),
            "localization_valid": sum(row["localization_valid"] for row in scoped),
            "exact_restoration": sum(row["exact_restoration"] for row in scoped),
        }
    summary = {
        "total": len(details),
        "generation_success": sum(row["generation_status"] == "success" for row in details),
        "schema_valid": count("schema_valid"),
        "classification_correct": count("classification_correct"),
        "localization_valid": count("localization_valid"),
        "exact_restoration": count("exact_restoration"),
        "by_action": by_action,
    }
    write_jsonl(output_dir / "evaluation_details.jsonl", details)
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "evaluate"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--prompt-dir", type=Path, default=DEFAULT_PROMPT_DIR)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.output_dir.resolve(), args.prompt_dir.resolve())
    else:
        evaluate(args.output_dir.resolve())


if __name__ == "__main__":
    main()
