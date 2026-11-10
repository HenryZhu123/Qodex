import json
import sys
from pathlib import Path

p = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase1\source_selection.jsonl")
rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

task = sys.argv[1] if len(sys.argv) > 1 else "typo"
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20

pool = [r for r in rows if r["task_type"] == task][:limit]
print(f"task={task} sources={len(pool)}")
for i, r in enumerate(pool):
    rid = r["source_record_id"]
    ans = r["source_answer"]
    text = r["source_text"].replace("\n", " | ")
    print(f"[{i}] {rid} ans={ans}")
    print(f"    {text[:200]}")
