import json
import sys

sys.path.insert(0, "hku_agent/research-assets/review_eval/scripts")
from router_and_retriever import targeted_retrieve

P = "hku_agent/research-assets/review_eval/blind_test_set/runs/factual_ab/v2_results.jsonl"
recs = [json.loads(l) for l in open(P, encoding="utf-8") if l.strip()]
fact = [r for r in recs if not r["is_clean"]]

with_ev = 0
total_claims = 0
for r in fact:
    for c in r.get("claims") or []:
        total_claims += 1
        evs, _ = targeted_retrieve(r["subject"], [c], top_k=2)
        if evs:
            with_ev += 1

print(f"claims total            : {total_claims}")
print(f"claims with evidence now: {with_ev}  ({with_ev / max(total_claims, 1) * 100:.0f}%)")
