#!/usr/bin/env python3
"""Calibrate the same-book similarity threshold (UPGRADE-PLAN D5).

Extracts each PDF once and prints a pairwise Jaccard matrix so the edition
threshold is chosen from data instead of a guess.
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

from kb_registry import extract_pdf_text, jaccard, normalize_text, shingles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", action="append", required=True)
    parser.add_argument("--label", action="append", default=[])
    args = parser.parse_args()

    pdfs = [Path(item) for item in args.pdf]
    labels = args.label or [path.stem[:28] for path in pdfs]
    texts: dict[str, set[int]] = {}
    for path, label in zip(pdfs, labels, strict=True):
        raw = extract_pdf_text(path)
        texts[label] = shingles(raw)
        print(
            f"extracted {label}: chars={len(normalize_text(raw))} shingles={len(texts[label])}",
            flush=True,
        )

    print("\npairwise Jaccard:")
    matrix = {}
    for (label_a, set_a), (label_b, set_b) in combinations(texts.items(), 2):
        score = round(jaccard(set_a, set_b), 4)
        matrix[f"{label_a} vs {label_b}"] = score
        print(f"  {score:.4f}  {label_a}  <->  {label_b}")

    print("\n" + json.dumps(matrix, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
