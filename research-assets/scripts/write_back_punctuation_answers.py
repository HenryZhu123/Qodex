from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "训练集-微调版提示词" / "标点符号错误_训练集.jsonl"
RESULT_DIR = ROOT / "模型输出" / "Qwen3.8-Max_标点符号规则修订验证_20260824"
BASE_RESULTS = RESULT_DIR / "conflicts_37.jsonl"
OVERRIDE_RESULTS = RESULT_DIR / "remaining_5_retest.jsonl"
BACKUP = RESULT_DIR / "标点符号错误_训练集_标准答案写回前备份.jsonl"
REPORT = RESULT_DIR / "标准答案写回报告.json"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


rows = read_jsonl(DATASET)
base = read_jsonl(BASE_RESULTS)
overrides = read_jsonl(OVERRIDE_RESULTS)

answers: dict[int, dict] = {}
for result in base:
    if result.get("status") == "success":
        answers[int(result["line_number"])] = result["answer"]
for result in overrides:
    if result.get("status") == "success":
        answers[int(result["line_number"])] = result["answer"]

# Normalize model fields that changed escaping, omitted the surrounding text for a
# deletion, or classified a sentence-boundary error as a width/style difference.
repairs = {
    741: {"original_text": "A，", "anchor_text": "变换为\nA，"},
    744: {"original_text": "，", "anchor_text": "图形，"},
    819: {"original_text": "，", "anchor_text": "( )$，", "correction": "。"},
    886: {"original_text": "，", "anchor_text": "正确的是（"},
    887: {"original_text": "，", "anchor_text": "解空间的维数为（"},
    893: {
        "original_text": ";",
        "anchor_text": "a)^T$;",
        "correction": "。",
        "description": "条件陈述结束后即进入编号作答任务，句末误用分号，题干边界不清。",
        "suggestion": "将英文分号改为句号。",
    },
    977: {
        "original_text": "（  ），",
        "anchor_text": "最终选择的一般都是最优方案。（  ），",
        "correction": "（  ）",
    },
}
for line_number, fields in repairs.items():
    error = answers[line_number]["errors"][0]
    error.update(fields)

expected_lines = {
    549, 550, 551, 552, 553, 554, 555, 632, 660, 693, 739, 741, 742,
    743, 744, 757, 805, 819, 828, 829, 862, 880, 885, 886, 887, 893,
    897, 968, 969, 977, 983, 987, 988, 990, 1027, 1031, 1032,
}
issues: list[str] = []
if set(answers) != expected_lines:
    issues.append(
        f"answer line set mismatch: missing={sorted(expected_lines - set(answers))}, "
        f"extra={sorted(set(answers) - expected_lines)}"
    )

required_top = {"reason", "has_error", "total_errors", "errors"}
required_error = {
    "error_type", "position", "original_text", "anchor_text", "correction",
    "description", "suggestion",
}

for line_number, answer in sorted(answers.items()):
    if not required_top.issubset(answer):
        issues.append(f"line {line_number}: missing top-level fields")
        continue
    errors = answer.get("errors")
    if not isinstance(errors, list):
        issues.append(f"line {line_number}: errors is not a list")
        continue
    if answer.get("has_error") is not True:
        issues.append(f"line {line_number}: expected a positive standard answer")
    if answer.get("total_errors") != len(errors) or not errors:
        issues.append(f"line {line_number}: inconsistent total_errors")

    source = rows[line_number - 1]
    user = next((m for m in source.get("messages", []) if m.get("role") == "user"), None)
    if not user or "\n" not in user.get("content", ""):
        issues.append(f"line {line_number}: invalid user payload")
        continue
    payload = json.loads(user["content"].split("\n", 1)[1])
    content = str(payload.get("detection_content", ""))

    for index, error in enumerate(errors, 1):
        if not required_error.issubset(error):
            issues.append(f"line {line_number} error {index}: missing fields")
            continue
        if error.get("error_type") != "标点符号错误":
            issues.append(f"line {line_number} error {index}: invalid error_type")
        original = str(error.get("original_text", ""))
        anchor = str(error.get("anchor_text", ""))
        if original and original not in content:
            issues.append(f"line {line_number} error {index}: original_text not found")
        if not anchor or anchor not in content:
            issues.append(f"line {line_number} error {index}: anchor_text not found")
        if not str(error.get("correction", "")).strip():
            issues.append(f"line {line_number} error {index}: empty correction")

if issues:
    REPORT.write_text(
        json.dumps({"written": False, "issues": issues}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    raise SystemExit("validation failed; see write-back report")

before = DATASET.read_bytes()
shutil.copy2(DATASET, BACKUP)
for line_number, answer in sorted(answers.items()):
    messages = rows[line_number - 1].get("messages", [])
    assistant = next((m for m in messages if m.get("role") == "assistant"), None)
    if assistant is None:
        raise ValueError(f"line {line_number}: assistant message missing")
    assistant["content"] = json.dumps(answer, ensure_ascii=False, separators=(",", ":"))

tmp = DATASET.with_suffix(DATASET.suffix + ".tmp")
with tmp.open("w", encoding="utf-8", newline="\n") as handle:
    for row in rows:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
tmp.replace(DATASET)
after = DATASET.read_bytes()

report = {
    "written": True,
    "dataset": str(DATASET),
    "backup": str(BACKUP),
    "updated_rows": len(answers),
    "updated_line_numbers": sorted(answers),
    "validation_issues": [],
    "sha256_before": digest(before),
    "sha256_after": digest(after),
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
