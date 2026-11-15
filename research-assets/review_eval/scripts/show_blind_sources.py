import json

records = [json.loads(line) for line in open('hku_agent/research-assets/review_eval/blind_test_set/phase1/source_selection.jsonl', encoding='utf-8')]

for t in ['type_mismatch', 'option_structure', 'factual_logical']:
    ts = [r for r in records if r['error_type'] == t and r['provenance'] == 'new_synthesis']
    print(f"=== {t} ({len(ts)} questions) ===")
    for idx, r in enumerate(ts, 1):
        print(f"{idx}. [{r['source_record_id']}] ({r['source_subject']}) {r['question_text'][:70]}...")
