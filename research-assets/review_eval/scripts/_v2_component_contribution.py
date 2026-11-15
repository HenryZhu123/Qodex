import json
from collections import Counter, defaultdict

P = "hku_agent/research-assets/review_eval/blind_test_v2/runs/frozen_eval/v2_results.jsonl"
recs = [json.loads(l) for l in open(P, encoding="utf-8") if l.strip()]
errs = [r for r in recs if not r["is_clean"]]

tp_by_stage = Counter()
for r in errs:
    if r["has_error"]:
        tp_by_stage[r["stage"] or "no_result"] += 1

print("TP contribution by component:")
for k, v in tp_by_stage.most_common():
    print(f"  {k:<22} {v:>3}  ({v / max(sum(tp_by_stage.values()), 1) * 100:.0f}% of detected)")

print("\nper-category TP by stage:")
by = defaultdict(Counter)
for r in errs:
    if r["has_error"]:
        by[r["category"]][r["stage"] or "no_result"] += 1
for c in sorted(by):
    print(f"  {c:<18} {dict(by[c])}")

print("\nno-result (invalid API) per category:")
nr = Counter(r["category"] for r in errs if r["stage"] == "")
print(" ", dict(nr))
