import json

records = [json.loads(l) for l in open("hku_agent/research-assets/review_eval/blind_test_set/runs/blind_evaluation/blind_results.jsonl", encoding="utf-8") if l.strip()]
tm = [r for r in records if r["category"] == "type_mismatch"]
opt = [r for r in records if r["category"] == "option_structure"]
print(f"type_mismatch: {sum(1 for r in tm if r['has_error'])}/{len(tm)}")
print(f"option_structure: {sum(1 for r in opt if r['has_error'])}/{len(opt)}")
