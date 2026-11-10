#!/usr/bin/env python3
"""Shared metrics for three-state review evaluation.

Records are question-level. ``status`` must be one of DETECTED, CLEAN, or
UNRESOLVED.  UNRESOLVED is never silently converted to CLEAN: conservative
recall counts it as a miss, while conditional recall excludes it explicitly.
"""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from typing import Any, Iterable

VALID_STATUSES = frozenset({"DETECTED", "CLEAN", "UNRESOLVED"})


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    rate = successes / total
    scale = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / scale
    half = z * sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / scale
    return max(0.0, center - half), min(1.0, center + half)


def calibrated_precision(recall: float, false_positive_rate: float, prevalence: float) -> float:
    if not 0 <= prevalence <= 1:
        raise ValueError("prevalence must be in [0, 1]")
    numerator = recall * prevalence
    denominator = numerator + false_positive_rate * (1 - prevalence)
    return numerator / denominator if denominator else 0.0


def _rate_block(successes: int, total: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, total)
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 6) if total else 0.0,
        "wilson_95": [round(low, 6), round(high, 6)],
    }


def summarize(records: Iterable[dict[str, Any]], prevalences: Iterable[float] = (0.05, 0.10)) -> dict[str, Any]:
    rows = list(records)
    for row in rows:
        if row.get("status") not in VALID_STATUSES:
            raise ValueError(f"Invalid status for {row.get('sample_id')}: {row.get('status')!r}")

    errors = [row for row in rows if not row.get("is_clean", False)]
    clean = [row for row in rows if row.get("is_clean", False)]
    detected = sum(row["status"] == "DETECTED" for row in errors)
    exact_type_available = all("target_type_hit" in row for row in errors)
    exact_type_detected = sum(
        row["status"] == "DETECTED" and row.get("target_type_hit", False)
        for row in errors
    )
    false_positives = sum(row["status"] == "DETECTED" for row in clean)
    unresolved_errors = sum(row["status"] == "UNRESOLVED" for row in errors)
    unresolved_clean = sum(row["status"] == "UNRESOLVED" for row in clean)
    resolved_errors = len(errors) - unresolved_errors
    resolved_clean = len(clean) - unresolved_clean

    conservative_recall = detected / len(errors) if errors else 0.0
    conditional_recall = detected / resolved_errors if resolved_errors else 0.0
    conservative_fpr = false_positives / len(clean) if clean else 0.0
    conditional_fpr = false_positives / resolved_clean if resolved_clean else 0.0

    by_category: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("category") or "unknown")].append(row)
    for category, category_rows in sorted(grouped.items()):
        hits = sum(row["status"] == "DETECTED" for row in category_rows)
        unresolved = sum(row["status"] == "UNRESOLVED" for row in category_rows)
        resolved = len(category_rows) - unresolved
        by_category[category] = {
            "detected": hits,
            "total": len(category_rows),
            "unresolved": unresolved,
            "conservative": _rate_block(hits, len(category_rows)),
            "conditional": _rate_block(hits, resolved),
        }
        if category != "clean" and all("target_type_hit" in row for row in category_rows):
            exact_hits = sum(
                row["status"] == "DETECTED" and row.get("target_type_hit", False)
                for row in category_rows
            )
            by_category[category]["exact_type_recall"] = _rate_block(
                exact_hits, len(category_rows)
            )

    error_category_rates = [
        value["conservative"]["rate"]
        for category, value in by_category.items()
        if category != "clean"
    ]
    calibrated = {
        f"{prevalence:.0%}": round(
            calibrated_precision(conservative_recall, conservative_fpr, prevalence), 6
        )
        for prevalence in prevalences
    }
    return {
        "counts": {
            "samples": len(rows),
            "errors": len(errors),
            "clean": len(clean),
            "detected_errors": detected,
            "exact_type_detected_errors": exact_type_detected if exact_type_available else None,
            "false_positives": false_positives,
            "unresolved_errors": unresolved_errors,
            "unresolved_clean": unresolved_clean,
        },
        "conservative_recall": _rate_block(detected, len(errors)),
        "conditional_recall": _rate_block(detected, resolved_errors),
        "exact_type_recall": (
            _rate_block(exact_type_detected, len(errors)) if exact_type_available else None
        ),
        "conservative_fpr": _rate_block(false_positives, len(clean)),
        "conditional_fpr": _rate_block(false_positives, resolved_clean),
        "macro_conservative_recall": round(
            sum(error_category_rates) / len(error_category_rates), 6
        ) if error_category_rates else 0.0,
        "calibrated_precision": calibrated,
        "by_category": by_category,
    }
