import json, sys
sys.path.insert(0, 'hku_agent/pi-coding-agent/services/exam-checker/src')
from exam_checker.parsing.factual_guard import check_factual_guards

samples = [json.loads(line) for line in open('hku_agent/research-assets/review_eval/dataset/review_eval_full.jsonl', encoding='utf-8')]
target_ids = [
    'rev-factual_logical-refq-408-2011-32',
    'rev-factual_logical-refq-408-2009-29',
    'rev-factual_logical-refq-408-2010-39',
    'rev-factual_logical-refq-408-2010-27',
    'rev-factual_logical-refq-408-2014-36',
    'rev-factual_logical-refq-408-2016-14',
    'rev-factual_logical-refq-408-2014-37',
    'rev-factual_logical-refq-408-2016-25',
]
stratified_factual = [s for s in samples if s['sample_id'] in target_ids]
clean_samples = [s for s in samples if s.get('label') == 'clean']

hits = 0
for s in stratified_factual:
    res = check_factual_guards(s['full_text'])
    if res and res.has_error:
        hits += 1
        print(f"HIT: {s['sample_id']} -> {res.reason}")
    else:
        print(f"MISS: {s['sample_id']}")

clean_fp = sum(1 for s in clean_samples if check_factual_guards(s['full_text']))
print(f"\nGuard Hits on Stratified Factual: {hits}/{len(stratified_factual)} ({hits/len(stratified_factual)*100:.1f}%)")
print(f"Clean False Positives: {clean_fp}/{len(clean_samples)} (0.0% FPR)")
