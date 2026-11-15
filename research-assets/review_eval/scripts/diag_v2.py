import json
from collections import Counter

p = "hku_agent/research-assets/review_eval/blind_test_set/runs/factual_ab/v2_results.jsonl"
recs = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
fact = [r for r in recs if not r["is_clean"]]
cln = [r for r in recs if r["is_clean"]]

print("=== factual stage distribution ===")
for k, v in Counter(r["stage"] for r in fact).most_common():
    print(f"  {k:<20} {v}")
print("=== clean stage distribution ===")
for k, v in Counter(r["stage"] for r in cln).most_common():
    print(f"  {k:<20} {v}")

print("\n=== factual details ===")
for r in fact:
    claims = r.get("claims") or []
    print(f"\n[{r['has_error']}] {r['sample_id']}  stage={r['stage']} calls={r['llm_calls']}")
    print(f"   reason: {r['reason'][:110]}")
    for c in claims:
        print(f"   claim: {c[:90]}")
