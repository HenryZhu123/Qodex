#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build and validate manual mutations for one error type.

Reads phase2_manual/<type>.json entries of the form
    [source_record_id, clean_span, error_span, subtype, rationale]

Applies each entry to its source question and writes accepted mutations to
phase2_manual/<type>_manifest.jsonl.

Field semantics in the manifest follow the skill schema:
  original_text = the erroneous span as it appears in error_text
  correction    = the minimal repair that restores clean_text

Operations supported:
  - replace:  error_span is non-empty and differs from clean_span
  - delete :  error_span is empty, clean_span is removed
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
PHASE1 = ROOT / "phase1"
PHASE2M = ROOT / "phase2_manual"


def load_sources() -> dict[str, dict]:
    rows = [
        json.loads(line)
        for line in (PHASE1 / "source_selection.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {r["source_record_id"]: r for r in rows}


def anchor(text: str, span: str) -> str:
    idx = text.find(span)
    if idx < 0:
        raise ValueError("span missing")
    if text.count(span) == 1:
        return span
    start, end = max(0, idx - 8), min(len(text), idx + len(span) + 8)
    while text[start:end].count(span) > 1 and (start > 0 or end < len(text)):
        start, end = max(0, start - 4), min(len(text), end + 4)
    return text[start:end]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True)
    args = ap.parse_args()
    type_code = args.type

    spec = json.loads((PHASE2M / f"{type_code}.json").read_text(encoding="utf-8"))
    entries = spec[type_code]
    sources = load_sources()

    accepted, rejected = [], []
    for entry in entries:
        rid, clean_span, error_span, subtype, rationale = entry
        src = sources.get(rid)
        if src is None:
            rejected.append({"source_record_id": rid, "reason": "source not in selection"})
            continue
        clean = src["source_text"]
        if clean.count(clean_span) != 1:
            rejected.append({
                "source_record_id": rid,
                "reason": f"span count={clean.count(clean_span)}",
                "span": clean_span,
            })
            continue

        if error_span == "":
            operation = "删除"
            error = clean.replace(clean_span, "", 1)
            original_text = ""  # nothing visible left at that place
            correction = clean_span
            anchor_src = clean_span[:12]
            try:
                anchor_text = anchor(clean, anchor_src)
            except ValueError:
                anchor_text = clean_span
            restored = clean  # deletion restores by reinserting; checked below
            ok = error == clean[: clean.find(clean_span)] + clean[clean.find(clean_span) + len(clean_span):]
        else:
            operation = "替换"
            error = clean.replace(clean_span, error_span, 1)
            original_text = error_span
            correction = clean_span
            restored = error.replace(error_span, clean_span, 1)
            try:
                anchor_text = anchor(error, error_span)
            except ValueError:
                anchor_text = error_span[:20]
            ok = restored == clean

        if not ok:
            rejected.append({"source_record_id": rid, "reason": "round-trip failed"})
            continue
        if error == clean:
            rejected.append({"source_record_id": rid, "reason": "no change"})
            continue

        accepted.append({
            "sample_id": f"rev-{type_code}-{rid}",
            "source_fingerprint_sha256": src["source_fingerprint_sha256"],
            "source_record_id": rid,
            "source_origin": "existing_dataset",
            "source_year": src["source_year"],
            "source_subject": src["source_subject"],
            "source_answer": src["source_answer"],
            "clean_text": clean,
            "error_text": error,
            "error_type": type_code,
            "error_detailed_type": subtype,
            "operation": operation,
            "original_text": original_text,
            "correction": correction,
            "anchor_text": anchor_text,
            "mutation_signature": f"{subtype}|{operation}|{type_code}",
            "rationale": rationale,
            "phase2_status": "accepted",
            "authored_by": "manual",
        })

    out = PHASE2M / f"{type_code}_manifest.jsonl"
    out.write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for a in accepted) + "\n",
        encoding="utf-8",
    )
    rej = PHASE2M / f"{type_code}_rejected.jsonl"
    rej.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rejected) + "\n",
        encoding="utf-8",
    )

    print(f"{type_code}: accepted {len(accepted)}/{len(entries)}, rejected {len(rejected)}")
    for r in rejected:
        print("  REJECT", r)
    subs: dict[str, int] = {}
    for a in accepted:
        subs[a["error_detailed_type"]] = subs.get(a["error_detailed_type"], 0) + 1
    if accepted:
        top = max(subs.values())
        print(f"  subtypes: {subs}")
        print(f"  max share: {top / len(accepted):.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
