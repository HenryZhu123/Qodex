import json

with open("hku_agent/research-assets/review_eval/runs/phase1_router/router_eval_results.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        cat = d["category"]
        if cat in ("typo", "option_structure", "factual_logical"):
            print(f"[{cat:16}] {d['sample_id']} | {d['decision']:7} | {d['reason']}")
