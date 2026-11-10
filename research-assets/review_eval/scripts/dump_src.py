import json
from pathlib import Path

src = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase1\source_selection.jsonl")
used = set()
for f in Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase2_manual").glob("*_manifest.jsonl"):
    for l in f.read_text(encoding="utf-8").splitlines():
        if l.strip():
            used.add(json.loads(l)["source_record_id"])

rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
typo = [r for r in rows if r["task_type"] == "typo" and r["source_record_id"] not in used]

print(f"unused typo sources: {len(typo)}")
for i, r in enumerate(typo):
    print(f"--- [{i}] {r['source_record_id']} ans={r['source_answer']}")
    print(r["source_text"])
    print()
