import json
from collections import Counter

P = "hku_agent/research-assets/review_eval/blind_test_v2/phase2/mutation_manifest.jsonl"
man = [json.loads(l) for l in open(P, encoding="utf-8") if l.strip()]
errs = [r for r in man if r["error_type"] != "none"]
cln = [r for r in man if r["error_type"] == "none"]

bad_rt = bad_anchor = bad_empty = 0
for r in errs:
    o, c = r["original_text"], r["correction"]
    e, k = r["error_text"], r["clean_text"]
    if o:
        if e.replace(o, c, 1) != k:
            bad_rt += 1
        if e.count(o) != 1:
            bad_anchor += 1
    if not o and e != k:
        # deletion: re-insert must restore
        if c not in k:
            bad_empty += 1

print(f"records            : {len(man)}  (errors {len(errs)}, clean {len(cln)})")
print(f"round-trip failures: {bad_rt}")
print(f"anchor not unique  : {bad_anchor}")
print(f"deletion anomalies : {bad_empty}")
print(f"clean modified     : {sum(1 for r in cln if r['error_text'] != r['clean_text'])}")

ids = [r["sample_id"] for r in man]
print(f"duplicate ids      : {len(ids) - len(set(ids))}")
src = [r["source_record_id"] for r in man]
print(f"duplicate sources  : {len(src) - len(set(src))}")

print("\nper-type subtype concentration:")
for t in sorted({r['error_type'] for r in errs}):
    c = Counter(r["error_detailed_type"] for r in errs if r["error_type"] == t)
    tot = sum(c.values())
    over = [k for k, v in c.items() if v / tot > 0.25]
    print(f"  {t:<18} n={tot:<3} subtypes={len(c):<3} max={max(c.values())/tot*100:.0f}%"
          + (f"  OVER-CAP: {over}" if over else ""))
