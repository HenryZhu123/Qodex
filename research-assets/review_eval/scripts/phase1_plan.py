#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1 v2: re-plan source allocation by question features.

Problem with v1: sources were assigned to error types by a fixed rotation, so
many assignments could not host the intended error (e.g. a pure calculation
question cannot carry a "factual relation reversal").

Fix: score every usable question against each error type's requirements, then
assign greedily by best fit, one question per sample, no reuse.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"D:\Code\hku\LLM\hku_agent")
SRC_CANDIDATES = [
    REPO / "research-assets" / "reference_questions_408.jsonl",
    Path(r"D:\Code\hku\LLM\kb_refq_out\reference_questions.jsonl"),
]
PHASE1 = REPO / "research-assets" / "review_eval" / "phase1"

ERROR_TYPES = [
    ("typo", "错别字"),
    ("punctuation", "标点符号错误"),
    ("option_structure", "选项结构错误"),
    ("missing_info", "信息缺失"),
    ("type_mismatch", "题目与题型不一致"),
    ("answer_leakage", "答案泄露"),
    ("ambiguity", "语义不清"),
    ("unsolvable", "题目无解"),
    ("factual_logical", "事实/逻辑错误"),
]
PER_TYPE = 60

# Words whose wrong form is plausible for a typo mutation.
TYPO_WORDS = [
    "数据", "存储", "进程", "调度", "地址", "文件", "网络", "指令", "算法",
    "内存", "队列", "结点", "节点", "缓存", "带宽", "时延", "访问", "查询",
    "排序", "查找", "编译", "接口", "中断", "页面", "磁盘", "总线", "流水线",
    "控制器", "寄存器", "操作系统", "吞吐量", "死锁", "信号量", "页表", "校验",
    "编码", "译码", "总线", "复用", "同步", "虚拟", "物理", "逻辑", "容量",
]

PUNCT_MARKS = ["、", "；", "：", "。", "，", "（", "“"]

RELATION_WORDS = [
    "增大", "增加", "最高", "最大", "大于", "正数", "有序", "同步",
    "静态", "独占", "串行", "先进先出", "稳定", "唯一", "连续", "共享",
]

NUMERIC_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def fingerprint(text: str) -> str:
    norm = unicodedata.normalize("NFKC", text)
    norm = norm.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", ln.strip()) for ln in norm.split("\n")]
    return hashlib.sha256("\n".join(lines).strip().encode("utf-8")).hexdigest()


def question_text(rec: dict) -> str:
    opts = rec.get("options") or {}
    parts = [rec["stem"].strip()]
    for letter in "ABCD":
        if opts.get(letter):
            parts.append(f"{letter}. {opts[letter]}")
    return "\n".join(parts)


def stem_only(text: str) -> str:
    return "\n".join(l for l in text.split("\n") if not re.match(r"^[A-D][.．]", l))


def features(text: str) -> dict:
    stem = stem_only(text)
    num_with_unit = re.search(
        r"[0-9]+(?:\.[0-9]+)?\s*(?:位|个|条|块|MB|KB|GB|ns|μs|ms|GHz|%|度|层|级|字|字节|比特|页|段|项)",
        stem,
    )
    return {
        "has_typo_word": any(w in stem for w in TYPO_WORDS),
        "has_punct": any(stem.count(m) >= 1 for m in PUNCT_MARKS),
        "has_4_options": text.count("\nA. ") == 1 and text.count("\nD. ") == 1,
        "has_bracket": "（" in stem or "(" in stem,
        "has_clause": "，" in stem,
        "has_relation": any(w in stem for w in RELATION_WORDS),
        "has_number": bool(num_with_unit),
        "has_any_digit": bool(NUMERIC_RE.search(stem)),
        "has_list": bool(re.search(r"^I[.．]", text, re.M)),
        "stem_len": len(stem),
        "option_len": len(text) - len(stem),
    }


# Each error type: list of (feature, weight). Features are scored additively;
# boolean features contribute their weight only when true, so a missing feature
# lowers the score instead of disqualifying the candidate.
REQUIREMENTS = {
    "typo": [("has_typo_word", 8), ("stem_len", 0.02)],
    "punctuation": [("has_punct", 8), ("has_clause", 3)],
    "option_structure": [("has_4_options", 8), ("option_len", 0.01)],
    "missing_info": [("has_bracket", 5), ("has_clause", 5)],
    "type_mismatch": [("has_4_options", 5), ("stem_len", 0.03)],
    "answer_leakage": [("has_4_options", 5), ("option_len", 0.02)],
    "ambiguity": [("stem_len", 0.04), ("has_clause", 3)],
    "unsolvable": [("has_number", 8), ("has_any_digit", 4), ("has_list", 3), ("has_clause", 2)],
    "factual_logical": [("has_relation", 8), ("has_any_digit", 1), ("stem_len", 0.02)],
}


def score(feat: dict, reqs: list[tuple[str, float]]) -> float:
    """Additive score; boolean features add their weight when true."""
    total = 0.0
    for key, weight in reqs:
        value = feat[key]
        if isinstance(value, bool):
            if value:
                total += weight
        else:
            total += value * weight
    return total


def main() -> int:
    PHASE1.mkdir(parents=True, exist_ok=True)
    src = next((p for p in SRC_CANDIDATES if p.exists()), None)
    if src is None:
        raise SystemExit("reference questions not found")

    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    usable = [
        r for r in rows
        if r.get("options_complete") and r.get("answer_available") and len(r.get("stem", "")) >= 20
    ]

    scored = []
    for rec in usable:
        text = question_text(rec)
        feat = features(text)
        scored.append((rec, text, feat))

    used: set[str] = set()
    selections: list[dict] = []
    coverage: dict[str, int] = {}

    # Scarce types are filled first: a type whose pool is small (unsolvable needs
    # a numeric condition) must claim its sources before flexible types consume
    # them. Then round-robin the rest.
    scarce = ["unsolvable", "factual_logical", "punctuation"]
    order = scarce + [c for c, _ in ERROR_TYPES if c not in scarce]
    pending = {code: PER_TYPE for code, _ in ERROR_TYPES}

    for code in order:
        while pending[code] > 0:
            best = None
            best_score = -2.0
            for rec, text, feat in scored:
                if rec["record_id"] in used:
                    continue
                s = score(feat, REQUIREMENTS[code])
                if s > best_score:
                    best, best_score = (rec, text), s
            if best is None or best_score <= 0:
                coverage[code] = pending[code]
                pending[code] = 0
                break
            rec, text = best
            used.add(rec["record_id"])
            pending[code] -= 1
            selections.append({
                "sample_id": f"rev-{code}-{rec['record_id']}",
                "source_fingerprint_sha256": fingerprint(text),
                "source_text": text,
                "source_record_id": rec["record_id"],
                "source_file": str(src),
                "source_question_number": rec["question_no"],
                "source_year": rec["year"],
                "source_subject": rec["subject"],
                "source_answer": rec["standard_answer"],
                "status": "reserved",
                "reserved_for_run": "review-eval-p2",
                "task_type": code,
                "reserved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "used_at": None,
                "fit_score": round(best_score, 2),
            })

    counts = Counter(s["task_type"] for s in selections)
    subject_dist = Counter(s["source_subject"] for s in selections)
    year_dist = Counter(s["source_year"] for s in selections)

    (PHASE1 / "source_selection.jsonl").write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in selections) + "\n",
        encoding="utf-8",
    )

    print("selected:", len(selections))
    for code, _ in ERROR_TYPES:
        print(f"  {code}: {counts.get(code, 0)}")
    if coverage:
        print("shortfall:", coverage)
    print("subjects:", dict(subject_dist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
