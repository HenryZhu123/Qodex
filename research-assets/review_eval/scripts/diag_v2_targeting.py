import json

AB = "hku_agent/research-assets/review_eval/blind_test_set/runs/factual_ab/v2_results.jsonl"
GOLD = "hku_agent/research-assets/review_eval/blind_test_set/dataset/blind_test_gold.jsonl"

gold = {}
for line in open(GOLD, encoding="utf-8"):
    if line.strip():
        d = json.loads(line)
        gold[d["sample_id"]] = d

recs = [json.loads(l) for l in open(AB, encoding="utf-8") if l.strip()]
fact = [r for r in recs if not r["is_clean"]]

targeted = 0
partial = 0
missed = 0
for r in fact:
    g = gold.get(r["sample_id"], {})
    errs = g.get("errors") or []
    mut = (errs[0].get("original_text") or "").strip() if errs else ""
    claims = " ".join(r.get("claims") or [])
    # crude overlap: any 4-char window of the mutation appearing in a claim
    hit = False
    if mut and len(mut) >= 4:
        for i in range(0, len(mut) - 3):
            if mut[i : i + 4] in claims:
                hit = True
                break
    elif mut and mut in claims:
        hit = True
    if hit:
        targeted += 1
    elif claims:
        partial += 1
    else:
        missed += 1

print(f"claims covering the mutated span : {targeted}/20")
print(f"claims extracted but off-target  : {partial}/20")
print(f"no claim extracted               : {missed}/20")
