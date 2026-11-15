import json

target_ids = {
    'rev-factual_logical-refq-408-2011-32',
    'rev-factual_logical-refq-408-2009-29',
    'rev-factual_logical-refq-408-2010-39',
    'rev-factual_logical-refq-408-2010-27',
    'rev-factual_logical-refq-408-2014-36',
    'rev-factual_logical-refq-408-2016-14',
    'rev-factual_logical-refq-408-2014-37',
    'rev-factual_logical-refq-408-2016-25',
}

for line in open('hku_agent/research-assets/review_eval/dataset/review_eval_gold.jsonl', encoding='utf-8'):
    d = json.loads(line)
    if d['sample_id'] in target_ids:
        err = d['errors'][0]
        print(f"[{d['sample_id']}]")
        print(f"  original_text: {err['original_text']}")
        print(f"  correction:    {err['correction']}")
        print(f"  description:   {err['description']}")
