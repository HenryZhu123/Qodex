#!/usr/bin/env python3
"""Export clean/mutated counterfactual pairs from a mutation manifest."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "sample_id", "pair_id", "variant", "label", "error_type",
            "subject", "source_record_id", "full_text", "reference",
        ])
        for record in records:
            if record.get("error_type") == "none":
                continue
            pair_id = record["sample_id"]
            common = [
                pair_id,
                record.get("error_type", ""),
                record.get("source_subject", ""),
                record.get("source_record_id", ""),
            ]
            writer.writerow([
                f"{pair_id}::clean", pair_id, "clean", "clean", common[1],
                common[2], common[3], record["clean_text"], record.get("reference", ""),
            ])
            writer.writerow([
                f"{pair_id}::mutated", pair_id, "mutated", "error", common[1],
                common[2], common[3], record["error_text"], record.get("reference", ""),
            ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
