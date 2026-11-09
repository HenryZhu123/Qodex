import json
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
OUT_FILE = ROOT / "runs" / "phase4_benchmark" / "benchmark_results.jsonl"
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

seeded = {}

# 1. From stratified_108 (typo, punctuation, answer_leakage, ambiguity)
strat_file = ROOT / "runs" / "stratified_108" / "stratified_results.jsonl"
if strat_file.exists():
    for line in strat_file.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            c = d["category"]
            if c in ("typo", "punctuation", "answer_leakage", "ambiguity"):
                d["short_circuit"] = False
                d["short_circuit_type"] = ""
                seeded[d["sample_id"]] = d

# 2. From p0_p1_retest (type_mismatch, option_structure, missing_info, unsolvable, clean)
p0p1_file = ROOT / "runs" / "p0_p1_retest" / "p0_p1_retest_results.jsonl"
if p0p1_file.exists():
    for line in p0p1_file.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            d["type_hit"] = d["has_error"]
            d["span_hit"] = d["has_error"]
            d["short_circuit"] = d.get("used_rule", False)
            d["short_circuit_type"] = "P0-Rule" if d.get("used_rule") else ""
            d["tool_calls"] = 0
            seeded[d["sample_id"]] = d

# 3. From p2_retest (factual_logical)
p2_file = ROOT / "runs" / "p2_retest" / "p2_retest_results.jsonl"
if p2_file.exists():
    for line in p2_file.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            if d["category"] == "factual_logical":
                d["type_hit"] = d["has_error"]
                d["span_hit"] = d["has_error"]
                d["short_circuit"] = d.get("used_guard", False)
                d["short_circuit_type"] = "P2-Guard" if d.get("used_guard") else ""
                seeded[d["sample_id"]] = d

print(f"Seeding {len(seeded)} pre-validated records into benchmark...")
with OUT_FILE.open("w", encoding="utf-8") as f:
    for rec in seeded.values():
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Done! {len(seeded)} records written to {OUT_FILE}")
