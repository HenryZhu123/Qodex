#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean the candidate clean-question set.

Two problems found in the raw candidates:

1. Formatting noise from the PDF text layer:
   - `．` is a PDF emphasis dot ("不．符合"), not a punctuation error;
   - `＿` and full-width spaces are blank placeholders.
   A reviewer would flag these as punctuation problems, inflating the
   false-positive rate for reasons unrelated to subject knowledge.

2. Subject labels follow a mechanical 408 question-number range, but some
   papers (mock sets, atypical years) number questions differently, so a
   sorting question can be labelled "computer organization". Retrieval and
   per-subject reporting depend on the label, so it is re-derived from content.

Output: dataset/clean_set.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
SRC = ROOT / "dataset" / "clean_candidates.jsonl"
OUT = ROOT / "dataset" / "clean_set.jsonl"

KEYWORDS = {
    "data_structure": [
        "排序", "查找", "二叉树", "平衡树", "哈夫曼", "图的", "有向图", "无向图", "栈", "队列",
        "链表", "邻接", "拓扑", "关键路径", "最小生成树", "哈希", "散列", "B 树", "堆",
    ],
    "computer_organization": [
        "Cache", "cache", "指令", "流水线", "总线", "寄存器", "存储器", "CPU", "中断", "补码",
        "浮点", "IEEE", "编址", "寻址", "主存", "DRAM", "SRAM", "TLB", "DMA",
    ],
    "operating_system": [
        "进程", "线程", "页表", "死锁", "调度", "文件系统", "虚拟存储", "信号量", "临界区",
        "内存管理", "分页", "分段", "磁盘", "生产者", "同步", "互斥", "系统调用",
    ],
    "computer_network": [
        "TCP", "UDP", "IP 地址", "路由", "以太网", "带宽", "报文", "交换机", "子网", "HTTP",
        "DNS", "CSMA", "拥塞", "CSMA/CD", "MAC", "链路", "域名", "传输层", "应用层",
    ],
}


def clean_noise(text: str) -> str:
    text = text.replace("．", "")      # PDF emphasis dot
    text = text.replace("＿", "___")   # blank placeholder
    text = text.replace("\u3000", " ")  # full-width space
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def infer_subject(text: str) -> str | None:
    scores = {s: sum(text.count(k) for k in kws) for s, kws in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return None
    ordered = sorted(scores.values(), reverse=True)
    if len(ordered) > 1 and ordered[0] == ordered[1]:
        return None  # ambiguous, keep the original label
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=100)
    args = ap.parse_args()

    rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]

    out = []
    relabelled = 0
    for r in rows:
        text = clean_noise(r["full_text"])
        subject = infer_subject(text) or r["subject"]
        if subject != r["subject"]:
            relabelled += 1
        out.append({**r, "full_text": text, "subject": subject,
                    "subject_original": r["subject"]})

    # Rebalance across subjects after relabelling.
    by_subject: dict[str, list[dict]] = {}
    for r in out:
        by_subject.setdefault(r["subject"], []).append(r)
    for v in by_subject.values():
        v.sort(key=lambda x: x["sample_id"])

    order = ["data_structure", "computer_organization", "operating_system", "computer_network"]
    picked, idx = [], {s: 0 for s in order}
    while len(picked) < args.target and any(idx.get(s, 0) < len(by_subject.get(s, [])) for s in order):
        for s in order:
            if len(picked) >= args.target:
                break
            lst = by_subject.get(s, [])
            if idx.get(s, 0) < len(lst):
                picked.append(lst[idx[s]])
                idx[s] += 1

    for i, r in enumerate(picked, 1):
        r["sample_id"] = f"clean-{i:03d}"

    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in picked) + "\n",
                   encoding="utf-8")

    print(f"input      : {len(rows)}")
    print(f"cleaned out: {len(picked)}")
    print(f"relabelled : {relabelled}")
    print("by subject :", dict(Counter(r["subject"] for r in picked)))
    print("noise left :", sum(1 for r in picked if "．" in r["full_text"]))
    print("written    :", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
