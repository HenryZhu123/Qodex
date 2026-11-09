#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalize phase 2 manifests into the skill's answer schema.

For every sample we recompute the canonical fields from clean_text/error_text so
that:

  original_text = the erroneous span exactly as it appears in error_text
  correction    = the minimal repair that restores clean_text
  anchor_text   = a unique continuous excerpt of error_text containing it

Deletions (empty original_text) are handled by locating the gap: the anchor is
the context around the point where the removed span used to be.
"""

from __future__ import annotations

import json
from pathlib import Path

PHASE2M = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase2_manual")


def diff_span(clean: str, error: str) -> tuple[int, int, str, str]:
    """Longest-common-prefix/suffix diff of two strings.

    Returns (start, end, original_span_in_error, correction_span_in_clean).
    """
    n, m = len(clean), len(error)
    p = 0
    while p < n and p < m and clean[p] == error[p]:
        p += 1
    s = 0
    while s < n - p and s < m - p and clean[n - 1 - s] == error[m - 1 - s]:
        s += 1
    clean_span = clean[p:n - s]
    error_span = error[p:m - s]
    return p, m - s, error_span, clean_span


def anchor(text: str, span: str, pos: int) -> str:
    if span and text.count(span) == 1:
        return span
    start, end = max(0, pos - 10), min(len(text), pos + max(len(span), 1) + 10)
    cand = text[start:end]
    while span and cand.count(span) > 1 and (start > 0 or end < len(text)):
        start, end = max(0, start - 5), min(len(text), end + 5)
        cand = text[start:end]
    if not span:
        return cand or text[:40]
    return cand


def main() -> int:
    rows = []
    for f in sorted(PHASE2M.glob("*_manifest.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))

    out = []
    fixed = 0
    broken = 0
    for r in rows:
        clean, error = r["clean_text"], r["error_text"]
        if clean == error:
            broken += 1
            continue
        pos, end, error_span, clean_span = diff_span(clean, error)
        # verify: removing error_span and inserting clean_span restores clean
        restored = error[:pos] + clean_span + error[end:]
        if restored != clean:
            broken += 1
            continue
        anc = anchor(error, error_span, pos)
        if r.get("original_text") != error_span or r.get("correction") != clean_span:
            fixed += 1
        r["original_text"] = error_span
        r["correction"] = clean_span
        r["anchor_text"] = anc
        r["diff_start"] = pos
        r["has_error"] = True
        r["total_errors"] = 1
        out.append(r)

    merged = PHASE2M / "phase2_normalized.jsonl"
    merged.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n",
        encoding="utf-8",
    )
    print(f"total samples      : {len(rows)}")
    print(f"normalized         : {len(out)}")
    print(f"fields corrected   : {fixed}")
    print(f"broken (skipped)   : {broken}")
    print("written            :", merged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
