import json
from collections import Counter
from pathlib import Path

PHASE1 = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase1")
PHASE2M = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase2_manual")

sel = [json.loads(l) for l in (PHASE1 / "source_selection.jsonl")
       .read_text(encoding="utf-8").splitlines() if l.strip()]

used = set()
for f in PHASE2M.glob("*_manifest.jsonl"):
    for l in f.read_text(encoding="utf-8").splitlines():
        if l.strip():
            used.add(json.loads(l)["source_record_id"])

print("total selected     :", len(sel))
print("used in phase2     :", len(used))
print("remaining unused   :", len([r for r in sel if r["source_record_id"] not in used]))
print()
print("by type (selected / used / remaining):")
for t in ["typo", "punctuation", "option_structure", "missing_info", "type_mismatch",
          "answer_leakage", "ambiguity", "unsolvable", "factual_logical"]:
    pool = [r for r in sel if r["task_type"] == t]
    u = [r for r in pool if r["source_record_id"] in used]
    print(f"  {t:<18} {len(pool):>4} / {len(u):>3} / {len(pool) - len(u):>4}")
