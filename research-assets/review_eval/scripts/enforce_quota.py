#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enforce subtype quotas for one manual error-type file.

Given <type>.json with entries [rid, original, wrong, subtype, rationale] and a
per-subtype quota, keep at most `quota` entries per subtype so that no single
subtype exceeds the diversity cap. Reports the resulting distribution.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
PHASE2M = ROOT / "phase2_manual"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True)
    ap.add_argument("--quota", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = PHASE2M / f"{args.type}.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    entries = spec[args.type]

    by_subtype = defaultdict(list)
    for e in entries:
        by_subtype[e[3]].append(e)

    kept = []
    for subtype, items in by_subtype.items():
        kept.extend(items[: args.quota])

    kept.sort(key=lambda e: e[0])
    dist = Counter(e[3] for e in kept)
    total = len(kept)
    print(f"{args.type}: kept {total}/{len(entries)}")
    for subtype, n in dist.most_common():
        print(f"  {subtype}: {n} ({n/total:.0%})")
    print(f"  max share: {max(dist.values())/total:.0%}")

    if not args.dry_run:
        spec[args.type] = kept
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("  written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
