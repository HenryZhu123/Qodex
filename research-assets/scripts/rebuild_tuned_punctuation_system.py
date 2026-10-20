from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "训练集-微调版提示词" / "标点符号错误_训练集.jsonl"
PARTS = [
    ROOT / "提示词-微调版" / "共享核心.txt",
    ROOT / "提示词-微调版" / "标点符号错误.txt",
    ROOT / "提示词-微调版" / "JSON约束.txt",
]

system_prompt = "\n".join(path.read_text(encoding="utf-8").strip() for path in PARTS)
rows: list[dict] = []
for line_number, line in enumerate(DATASET.read_text(encoding="utf-8").splitlines(), 1):
    if not line.strip():
        continue
    row = json.loads(line)
    messages = row.get("messages", [])
    system_messages = [message for message in messages if message.get("role") == "system"]
    if len(system_messages) != 1:
        raise ValueError(f"line {line_number}: expected exactly one system message")
    system_messages[0]["content"] = system_prompt
    rows.append(row)

tmp = DATASET.with_suffix(DATASET.suffix + ".tmp")
with tmp.open("w", encoding="utf-8", newline="\n") as handle:
    for row in rows:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
os.replace(tmp, DATASET)

digest = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
print(
    json.dumps(
        {
            "dataset": str(DATASET),
            "rows": len(rows),
            "system_chars": len(system_prompt),
            "system_sha256": digest,
        },
        ensure_ascii=False,
    )
)
