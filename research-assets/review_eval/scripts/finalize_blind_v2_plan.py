import json
from collections import Counter
from pathlib import Path

ROOT = Path("hku_agent/research-assets/review_eval/blind_test_v2")
man = [json.loads(l) for l in (ROOT / "phase2" / "mutation_manifest.jsonl").open(encoding="utf-8") if l.strip()]
counts = Counter(r["error_type"] for r in man)
subtypes = {}
for r in man:
    if r["error_type"] == "none":
        continue
    subtypes.setdefault(r["error_type"], Counter())[r["error_detailed_type"]] += 1

plan_path = ROOT / "phase1" / "plan.json"
plan = json.loads(plan_path.read_text(encoding="utf-8"))
plan["actual_counts"] = dict(counts)
plan["actual_subtypes"] = {k: dict(v) for k, v in subtypes.items()}
plan["constructed_total"] = len(man)
plan["shortfalls"] = {
    k: v for k, v in plan["quota"].items()
    if counts.get(k, 0) != v
}
plan["shortfall_reason"] = (
    "Some source stems do not contain a span that can carry the assigned error "
    "type (no numeric value for a placeholder, no qualifying clause to delete, "
    "no candidate pronoun). Those items were rejected rather than coerced into a "
    "dubious label, so per-type counts are slightly below quota."
)
plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"actual_counts": dict(counts), "shortfalls": plan["shortfalls"]},
                 ensure_ascii=False, indent=2))
