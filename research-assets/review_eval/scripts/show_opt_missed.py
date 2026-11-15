import json, sys
sys.path.insert(0, 'hku_agent/pi-coding-agent/services/exam-checker/src')
from exam_checker.parsing.rule_checker import check_deterministic_rules

samples = [json.loads(line) for line in open('hku_agent/research-assets/review_eval/dataset/review_eval_full.jsonl', encoding='utf-8')]
opt_samples = [s for s in samples if s.get('error_type') == 'option_structure']
for s in opt_samples:
    if not check_deterministic_rules(s['full_text']):
        print(s['sample_id'], "|", s.get('error_detailed_type'), "|", repr(s['full_text'][-120:]))
