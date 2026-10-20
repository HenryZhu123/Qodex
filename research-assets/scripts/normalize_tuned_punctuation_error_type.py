from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "训练集-微调版提示词" / "标点符号错误_训练集.jsonl"
FIXED_TYPE = "标点符号错误"

rows: list[dict] = []
changed_answers = 0
changed_errors = 0

for line_number, line in enumerate(DATASET.read_text(encoding="utf-8").splitlines(), 1):
    if not line.strip():
        continue
    row = json.loads(line)
    assistant = next(
        (message for message in row.get("messages", []) if message.get("role") == "assistant"),
        None,
    )
    if assistant is None:
        raise ValueError(f"line {line_number}: assistant message missing")
    answer = json.loads(assistant["content"])
    answer_changed = False
    for error in answer.get("errors", []):
        if error.get("error_type") != FIXED_TYPE:
            error["error_type"] = FIXED_TYPE
            changed_errors += 1
            answer_changed = True
    if answer_changed:
        assistant["content"] = json.dumps(
            answer, ensure_ascii=False, separators=(",", ":")
        )
        changed_answers += 1
    rows.append(row)

tmp = DATASET.with_suffix(DATASET.suffix + ".tmp")
with tmp.open("w", encoding="utf-8", newline="\n") as handle:
    for row in rows:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
os.replace(tmp, DATASET)

print(
    json.dumps(
        {
            "dataset": str(DATASET),
            "rows": len(rows),
            "changed_answers": changed_answers,
            "changed_errors": changed_errors,
            "fixed_error_type": FIXED_TYPE,
        },
        ensure_ascii=False,
    )
)
