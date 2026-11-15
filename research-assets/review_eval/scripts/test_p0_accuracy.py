import json, sys
sys.path.insert(0, 'hku_agent/pi-coding-agent/services/exam-checker/src')
from exam_checker.parsing.rule_checker import check_deterministic_rules

samples = [json.loads(line) for line in open('hku_agent/research-assets/review_eval/dataset/review_eval_full.jsonl', encoding='utf-8')]
tm_samples = [s for s in samples if s.get('error_type') == 'type_mismatch']
opt_samples = [s for s in samples if s.get('error_type') == 'option_structure']
clean_samples = [s for s in samples if s.get('label') == 'clean']

tm_hits = sum(1 for s in tm_samples if check_deterministic_rules(s['full_text']))
opt_hits = sum(1 for s in opt_samples if check_deterministic_rules(s['full_text']))
clean_fps = sum(1 for s in clean_samples if check_deterministic_rules(s['full_text']))

print(f"type_mismatch Recall: {tm_hits}/{len(tm_samples)} ({tm_hits/len(tm_samples)*100:.1f}%)")
print(f"option_structure Recall: {opt_hits}/{len(opt_samples)} ({opt_hits/len(opt_samples)*100:.1f}%)")
print(f"clean FPR: {clean_fps}/{len(clean_samples)} ({clean_fps/len(clean_samples)*100:.1f}%)")
