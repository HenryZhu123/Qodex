import json
from collections import Counter
from pathlib import Path

base = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase2_manual")
types = ["typo", "punctuation", "option_structure", "missing_info", "type_mismatch",
         "answer_leakage", "ambiguity", "unsolvable", "factual_logical"]

total = 0
all_rows = []
print(f"{'type':<18}{'n':>4}{'subtypes':>10}{'max%':>7}  status")
print("-" * 60)
for t in types:
    rows = [json.loads(l) for l in (base / f"{t}_manifest.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    total += len(rows)
    all_rows.extend(rows)
    c = Counter(r["error_detailed_type"] for r in rows)
    top = max(c.values()) / len(rows) if rows else 0
    ok = "OK" if len(rows) == 20 and top <= 0.25 else "CHECK"
    print(f"{t:<18}{len(rows):>4}{len(c):>10}{top:>6.0%}  {ok}")

print("-" * 60)
print("total samples:", total)

# invariant checks
bad_restore = 0
bad_anchor = 0
missing_answer = 0
for r in all_rows:
    if r["original_text"]:
        if r["error_text"].replace(r["original_text"], r["correction"], 1) != r["clean_text"]:
            bad_restore += 1
    else:
        # deletion: reinserting correction at anchor position restores clean
        if r["correction"] not in r["clean_text"]:
            bad_restore += 1
    if not r["anchor_text"] or r["anchor_text"] not in (r["error_text"] or ""):
        if r["anchor_text"] not in r["clean_text"]:
            bad_anchor += 1
    if not r.get("source_answer"):
        missing_answer += 1

print()
print("restoration failures:", bad_restore)
print("anchor failures     :", bad_anchor)
print("missing source answer:", missing_answer)

# diversity across whole set
sig = Counter(r["mutation_signature"] for r in all_rows)
print("distinct signatures :", len(sig))
print("unique sources      :", len({r["source_record_id"] for r in all_rows}))
print("subjects            :", dict(Counter(r["source_subject"] for r in all_rows)))

merged = base / "phase2_all.jsonl"
merged.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in all_rows) + "\n",
                  encoding="utf-8")
print("merged ->", merged)
