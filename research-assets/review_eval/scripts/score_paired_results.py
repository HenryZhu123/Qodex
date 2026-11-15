#!/usr/bin/env python3
"""Score paired end-to-end outputs; both variants must be correct."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()

    pairs: dict[str, dict[str, dict]] = defaultdict(dict)
    for line in args.results.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        sample_id, separator, variant = record["sample_id"].rpartition("::")
        if separator and variant in {"clean", "mutated"}:
            pairs[sample_id][variant] = record

    complete = [pair for pair in pairs.values() if set(pair) == {"clean", "mutated"}]
    pair_success = sum(
        pair["clean"]["status"] == "CLEAN"
        and pair["mutated"]["status"] == "DETECTED"
        and pair["mutated"].get("target_type_hit", True)
        for pair in complete
    )
    unresolved = sum(
        "UNRESOLVED" in {pair["clean"]["status"], pair["mutated"]["status"]}
        for pair in complete
    )
    report = {
        "complete_pairs": len(complete),
        "pair_successes": pair_success,
        "pair_accuracy": round(pair_success / len(complete), 6) if complete else 0.0,
        "pairs_with_unresolved": unresolved,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
