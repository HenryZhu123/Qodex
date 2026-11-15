import json

for line in open('hku_agent/research-assets/review_eval/blind_test_set/runs/blind_evaluation/blind_results.jsonl', encoding='utf-8'):
    d = json.loads(line)
    cat = d['category']
    if cat in ('factual_logical', 'type_mismatch', 'ambiguity') and not d['has_error']:
        print(f"[{cat:<16}] {d['sample_id']}")
        print(f"  Reason: {d.get('reason')}")
