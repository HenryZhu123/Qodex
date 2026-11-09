import json
import sys
from pathlib import Path

PHASE1 = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase1")
PHASE2M = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase2_manual")

task = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 40

sel = [json.loads(l) for l in (PHASE1 / "source_selection.jsonl")
       .read_text(encoding="utf-8").splitlines() if l.strip()]
used = set()
for f in PHASE2M.glob("*_manifest.jsonl"):
    for l in f.read_text(encoding="utf-8").splitlines():
        if l.strip():
            used.add(json.loads(l)["source_record_id"])

pool = [r for r in sel if r["task_type"] == task and r["source_record_id"] not in used][:limit]
print(f"task={task} unused={len(pool)}")
for i, r in enumerate(pool):
    txt = r["source_text"].replace("\n", " | ")
    print(f"[{i}] {r['source_record_id']} ans={r['source_answer']}")
    print(f"    {txt[:230]}")
