import json

for line in open('hku_agent/research-assets/review_eval/dataset/review_eval_gold.jsonl', encoding='utf-8'):
    d = json.loads(line)
    if d['error_type'] in ('missing_info', 'unsolvable'):
        err = d['errors'][0]
        print(f"[{d['error_type']:<16}] ID:{d['sample_id']} | orig:'{err['original_text']}' | desc:{err['description']}")
