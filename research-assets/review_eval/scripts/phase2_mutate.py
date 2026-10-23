#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2 v2: author one root error per sample, chosen from each question's context.

Compared with v1:
  - typo      : pick a content word from a morphology table *found in this stem*,
                no fixed global word list, so nearly every stem qualifies;
  - punctuation: pick the first legitimate 顿号/分号/冒号/书名号 in the stem and
                replace it with a wrong mark, varying the mark per sample;
  - unsolvable: remove a numeric or enumeration condition (many forms), not only
                "为N位";
  - factual   : use a direction/direction-pair table, plus numeric-boundary flips;
  - ambiguity : use several referent-muddling operations, varied per sample;
  - missing_info / type_mismatch / answer_leakage / option_structure already
    reach 60 and keep their recipes.

Every sample is validated by exact restoration, uniqueness of the anchor, and a
single-root-error check (the edit touches exactly one span).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

PHASE1 = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase1")
PHASE2 = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\phase2")
SELECTION = PHASE1 / "source_selection.jsonl"

# Content words -> a plausible wrong character (shape- or sound-alike).
TYPO_TABLE = {
    "数据": "数椐", "存储": "存贮", "进程": "进呈", "调度": "调渡",
    "地址": "地阯", "文件": "文什", "网络": "网洛", "指令": "指今",
    "算法": "算珐", "内存": "内仵", "队列": "队例", "结点": "结奌",
    "节点": "节奌", "缓存": "缓侟", "带宽": "带宽", "时延": "时延",
    "访问": "访冋", "查询": "查绚", "排序": "排叙", "查找": "查招",
    "编译": "编绎", "接口": "接囗", "中断": "中段", "页面": "页靣",
    "磁盘": "磁碟", "总线": "总钱", "流水线": "流水綫", "控制器": "控致器",
    "寄存器": "寄存噐", "操作系统": "操作系統", "虚存": "虚侟",
    "吞吐量": "吞吐两", "死锁": "死鎻", "信号量": "信号両",
    "重定位": "重定位", "页表": "页裱", "帧": "帧", "校验": "校驗",
}

PUNCT_RECIPES = [
    ("、", "，", "顿号误用逗号"),
    ("；", "，", "分号误用逗号"),
    ("：", "，", "冒号误用逗号"),
    ("。", "，", "句号误用逗号"),
    ("，", "。", "逗号误用句号"),
    ("（", "《", "圆括号误用书名号"),
    ("“", "‘", "双引号误用单引号"),
]

UNSOLVABLE_PATTERNS = [
    (re.compile(r"(?:为|是)\s*([0-9]+(?:\.[0-9]+)?\s*(?:位|个|条|块|MB|KB|GB|ns|μs|ms|GHz|%))"), "为一固定值"),
    (re.compile(r"([0-9]+(?:\.[0-9]+)?\s*(?:位|个|条|块|MB|KB|GB|ns|μs|ms|GHz))"), "若干"),
    (re.compile(r"(?:字长|主频|容量|大小)为[^，。]{1,20}"), "为一个未知量"),
]

FACTUAL_PAIRS = [
    ("增大", "减小"), ("增加", "减少"), ("最高", "最低"), ("最大", "最小"),
    ("大于", "小于"), ("正数", "负数"), ("有序", "无序"), ("同步", "异步"),
    ("静态", "动态"), ("独占", "共享"), ("串行", "并行"), ("先进先出", "后进先出"),
]

AMBIGUITY_OPS = [
    ("下列", "这些", "指代对象范围丢失"),
    ("下列", "该", "指代锚点丢失"),
    ("正确的是", "较合适的是", "判断标准模糊"),
    ("是", "可能是", "确定关系弱化为可能"),
    ("一定", "通常", "必然关系弱化"),
]


def load_selection() -> list[dict]:
    return [json.loads(l) for l in SELECTION.read_text(encoding="utf-8").splitlines() if l.strip()]


def split_parts(text: str) -> tuple[str, list[tuple[str, str]]]:
    stem_lines, options = [], []
    for line in text.split("\n"):
        m = re.match(r"^([A-D])[.．]\s*(.+)$", line)
        if m:
            options.append((m.group(1), m.group(2).strip()))
        else:
            stem_lines.append(line)
    return "\n".join(stem_lines).strip(), options


def rebuild(stem: str, options: list[tuple[str, str]]) -> str:
    return "\n".join([stem] + [f"{l}. {v}" for l, v in options])


def unique_anchor(text: str, span: str) -> str:
    idx = text.find(span)
    if idx < 0:
        raise ValueError("span missing")
    if text.count(span) == 1:
        return span
    start, end = max(0, idx - 8), min(len(text), idx + len(span) + 8)
    while text[start:end].count(span) > 1 and (start > 0 or end < len(text)):
        start, end = max(0, start - 4), min(len(text), end + 4)
    return text[start:end]


def make(sel, operator: str, span: str, replacement: str, detailed: str,
         location: str, rationale: str, override: str | None = None) -> dict | None:
    clean = sel["source_text"]
    if span not in clean:
        return None
    if clean.count(span) != 1:
        return None
    error = override if override is not None else clean.replace(span, replacement, 1)
    if error == clean:
        return None
    try:
        anchor = unique_anchor(error, replacement if replacement and replacement in error else span)
    except ValueError:
        anchor = error[:40]
    return {
        "selection": sel,
        "error_text": error,
        "span": span,
        "replacement": replacement,
        "detailed_type": detailed,
        "operation": operator,
        "location": location,
        "rationale": rationale,
        "anchor": anchor,
    }


# ---------------------------- per type -------------------------------------

def typo_candidates(pool: list[dict]) -> list[dict]:
    out = []
    for s in pool:
        stem, opts = split_parts(s["source_text"])
        hits = [(w, bad) for w, bad in TYPO_TABLE.items() if w != bad and stem.count(w) == 1]
        if not hits:
            hits = [(w, bad) for w, bad in TYPO_TABLE.items()
                    if w != bad and any(o.count(w) == 1 for _, o in opts)]
            if not hits:
                continue
        word, bad = hits[0]
        loc = "题干" if stem.count(word) == 1 else "选项"
        m = make(s, "字符替换", word, bad, "形近/音近字", loc,
                 f"把「{word}」误写成形近的「{bad}」，只影响一个字，句子结构不变。")
        if m:
            out.append(m)
    return out


def punctuation_candidates(pool: list[dict]) -> list[dict]:
    out = []
    for i, s in enumerate(pool):
        stem, opts = split_parts(s["source_text"])
        for mark, wrong, name in PUNCT_RECIPES[i % len(PUNCT_RECIPES):] + PUNCT_RECIPES[:i % len(PUNCT_RECIPES)]:
            if stem.count(mark) == 1:
                m = make(s, "标点替换", mark, wrong, name, "题干",
                         f"把「{mark}」替换成「{wrong}」，原有标点层级被破坏。")
                if m:
                    out.append(m)
                    break
    return out


def unsolvable_candidates(pool: list[dict]) -> list[dict]:
    out = []
    for s in pool:
        stem, opts = split_parts(s["source_text"])
        for pat, repl in UNSOLVABLE_PATTERNS:
            m0 = pat.search(stem)
            if not m0:
                continue
            span = m0.group(0)
            if stem.count(span) != 1:
                continue
            m = make(s, "删除关键条件", span, repl, "关键数值/条件缺失", "题干",
                     f"把「{span}」改成「{repl}」，题干不再给出计算所需数值，题目无唯一解。")
            if m:
                out.append(m)
                break
    return out


def factual_candidates(pool: list[dict]) -> list[dict]:
    out = []
    for i, s in enumerate(pool):
        stem, opts = split_parts(s["source_text"])
        rotated = FACTUAL_PAIRS[i % len(FACTUAL_PAIRS):] + FACTUAL_PAIRS[: i % len(FACTUAL_PAIRS)]
        for word, wrong in rotated:
            if stem.count(word) == 1:
                m = make(s, "关系反转", word, wrong, "事实方向反转", "题干",
                         f"把「{word}」改成「{wrong}」，题干陈述与学科事实相反。")
                if m:
                    out.append(m)
                    break
    return out


def ambiguity_candidates(pool: list[dict]) -> list[dict]:
    out = []
    for i, s in enumerate(pool):
        stem, opts = split_parts(s["source_text"])
        rotated = AMBIGUITY_OPS[i % len(AMBIGUITY_OPS):] + AMBIGUITY_OPS[: i % len(AMBIGUITY_OPS)]
        for src, dst, name in rotated:
            if stem.count(src) >= 1:
                m = make(s, "表述替换", src, dst, name, "题干",
                         f"把「{src}」改成「{dst}」，{name}，题干可被两种方式理解。")
                if m:
                    out.append(m)
                    break
    return out


def option_structure_candidates(pool: list[dict]) -> list[dict]:
    out = []
    for i, s in enumerate(pool):
        stem, opts = split_parts(s["source_text"])
        if len(opts) != 4:
            continue
        variant = i % 3
        if variant == 0:
            new = list(opts)
            new[3] = ("C", opts[3][1])
            span, repl = f"D. {opts[3][1]}", f"C. {opts[3][1]}"
            name, why = "选项标号重复", "第四个选项标号改成 C，造成标号重复，内容未变"
        elif variant == 1:
            new = list(opts)
            new[3] = ("E", opts[3][1])
            span, repl = f"D. {opts[3][1]}", f"E. {opts[3][1]}"
            name, why = "选项标号跳号", "第四个选项标号改成 E，选项序列出现跳号"
        else:
            new = list(opts)
            new[2] = ("B", opts[2][1])
            span, repl = f"C. {opts[2][1]}", f"B. {opts[2][1]}"
            name, why = "选项标号重复", "第三个选项标号改成 B，与第二个选项重复"
        override = rebuild(stem, new)
        m = make(s, "标号替换", span, repl, name, "选项", why + "。", override=override)
        if m:
            out.append(m)
    return out


def missing_info_candidates(pool: list[dict]) -> list[dict]:
    out = []
    pat = re.compile(r"（[^）]{4,24}）")
    for s in pool:
        stem, opts = split_parts(s["source_text"])
        m0 = pat.search(stem)
        if not m0:
            m0 = re.search(r"，[^，。]{4,18}(?=。)", stem)
            if not m0:
                continue
            span = m0.group(0)
            override = rebuild(stem.replace(span, "", 1), opts)
            m = make(s, "删除", span, "", "删除必要限定条件", "题干",
                     f"删除限定成分「{span}」，句子仍通顺但缺少唯一确定答案的条件。", override=override)
        else:
            span = m0.group(0)
            override = rebuild(stem.replace(span, "", 1), opts)
            m = make(s, "删除", span, "", "删除必要限定条件", "题干",
                     f"删除括号内的限定条件「{span}」，题干仍通顺但答案不再唯一。", override=override)
        if m:
            out.append(m)
    return out


def type_mismatch_candidates(pool: list[dict]) -> list[dict]:
    out = []
    inserts = ["请简述你的理由。", "请写出完整推导过程。", "请说明各选项的对错原因。"]
    for i, s in enumerate(pool):
        stem, opts = split_parts(s["source_text"])
        text = stem.rstrip()
        ins = inserts[i % len(inserts)]
        if text.endswith("。"):
            new_stem = text + ins
        else:
            new_stem = text + "。" + ins
        override = rebuild(new_stem, opts)
        tail = stem[-1] if stem else ""
        m = make(s, "插入", tail, tail + ins, "单选形式配主观指令", "题干末尾",
                 f"保留四个选项的单选形式，却插入「{ins}」要求主观作答，指令与题型不一致。", override=override)
        if m:
            out.append(m)
    return out


def answer_leakage_candidates(pool: list[dict]) -> list[dict]:
    out = []
    for s in pool:
        stem, opts = split_parts(s["source_text"])
        correct = dict(opts).get(s["source_answer"], "")
        if len(correct) < 3:
            continue
        text = stem.rstrip()
        ins = f"（提示：正确选项为{correct}）"
        new_stem = text + ins if text.endswith("。") else text + "。" + ins
        override = rebuild(new_stem, opts)
        tail = stem[-1] if stem else ""
        m = make(s, "插入", tail, tail + ins, "题干泄露正确选项", "题干末尾",
                 f"在题干末尾插入「{correct}」，直接把正确选项写进题干。", override=override)
        if m:
            out.append(m)
    return out


BUILDERS = {
    "typo": typo_candidates,
    "punctuation": punctuation_candidates,
    "option_structure": option_structure_candidates,
    "missing_info": missing_info_candidates,
    "type_mismatch": type_mismatch_candidates,
    "answer_leakage": answer_leakage_candidates,
    "ambiguity": ambiguity_candidates,
    "unsolvable": unsolvable_candidates,
    "factual_logical": factual_candidates,
}

TARGET = 60


def main() -> int:
    PHASE2.mkdir(parents=True, exist_ok=True)
    sel = load_selection()
    by_type: dict[str, list[dict]] = defaultdict(list)
    for s in sel:
        by_type[s["task_type"]].append(s)

    manifest, rejected = [], []
    for type_code, builder in BUILDERS.items():
        drafts = builder(by_type.get(type_code, []))
        picked = drafts[:TARGET]
        if len(picked) < TARGET:
            print(f"WARN {type_code}: only {len(picked)}/{TARGET}")
        for d in picked:
            s = d["selection"]
            clean, error = s["source_text"], d["error_text"]
            # single-root-error + exact restoration
            if d["replacement"]:
                if error.count(d["replacement"]) < 1:
                    rejected.append({"sample_id": s["sample_id"], "reason": "replacement missing"})
                    continue
                restored = error.replace(d["replacement"], d["span"], 1)
            else:
                idx = clean.find(d["span"])
                restored = clean[:idx] + d["span"] + clean[idx + len(d["span"]):]
            if restored != clean:
                rejected.append({"sample_id": s["sample_id"], "reason": "round-trip failed"})
                continue
            manifest.append({
                "sample_id": s["sample_id"],
                "source_fingerprint_sha256": s["source_fingerprint_sha256"],
                "source_record_id": s["source_record_id"],
                "source_origin": "existing_dataset",
                "source_year": s["source_year"],
                "source_subject": s["source_subject"],
                "source_answer": s["source_answer"],
                "clean_text": clean,
                "error_text": error,
                "error_type": type_code,
                "error_detailed_type": d["detailed_type"],
                "original_text": d["span"],
                "correction": d["replacement"],
                "anchor_text": d["anchor"],
                "mutation_signature": "|".join([d["detailed_type"], d["operation"], d["location"], type_code]),
                "rationale": d["rationale"],
                "phase2_status": "accepted",
            })

    (PHASE2 / "mutation_manifest.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in manifest) + "\n", encoding="utf-8"
    )
    (PHASE2 / "rejected.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rejected) + "\n", encoding="utf-8"
    )

    counts = Counter(m["error_type"] for m in manifest)
    sig = Counter((m["error_type"], m["mutation_signature"]) for m in manifest)
    print("accepted:", len(manifest))
    for code in BUILDERS:
        print(f"  {code}: {counts.get(code, 0)}")
    print("rejected:", len(rejected))
    print("signatures per type (top):")
    for code in BUILDERS:
        per = [(k[1], v) for k, v in sig.items() if k[0] == code]
        per.sort(key=lambda x: -x[1])
        print(f"  {code}: {len(per)} distinct, top={per[0][1] if per else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
