import json, sys
sys.path.insert(0, 'hku_agent/pi-coding-agent/services/exam-checker/src')
from exam_checker.parsing.rule_checker import check_deterministic_rules

clean_samples = [json.loads(line) for line in open('hku_agent/research-assets/review_eval/dataset/review_eval_full.jsonl', encoding='utf-8') if json.loads(line).get('label') == 'clean']

for s in clean_samples:
    res = check_deterministic_rules(s['full_text'])
    if res:
        err = res.errors[0]
        print(f"ID: {s['sample_id']} -> {err.error_type} | '{err.original_text}' | {res.reason}")
