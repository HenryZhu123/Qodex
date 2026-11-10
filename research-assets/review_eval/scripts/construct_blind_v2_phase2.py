#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2 for Blind Test Set v2 (occurrence-aware authoring).

Every generator works on a *specific occurrence* of a span and records a
context window as original_text/correction, so a span that appears several
times in the stem can still yield a single, exactly reversible mutation.

Authoring policy (fixed before any measurement):
- one root cause per item;
- subtype rotation, no subtype above 25% of its error type;
- machine-verified exact round trip and unique anchor; failures are rejected.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval")
PHASE1 = ROOT / "blind_test_v2" / "phase1"
PHASE2 = ROOT / "blind_test_v2" / "phase2"
DATASET = ROOT / "blind_test_v2" / "dataset"

TYPE_CN = {
    "typo": "错别字",
    "punctuation": "标点符号错误",
    "option_structure": "选项错误",
    "type_mismatch": "题目与题型不一致",
    "missing_info": "信息缺失",
    "ambiguity": "语义不清",
    "unsolvable": "题目无解",
    "answer_leakage": "答案泄露",
    "factual_logical": "事实/逻辑错误",
}


def split_stem(text: str) -> tuple[str, list[str]]:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^[A-D][\.．]", line.strip()):
            return "\n".join(lines[:i]), lines[i:]
    return text, []


def mutate_at(
    text: str, span: str, repl: str, occurrence: int = 0, ctx: int = 8
) -> tuple[str, str, str] | None:
    """Replace one specific occurrence; return (error_text, err_window, clean_window)."""
    idx = -1
    for _ in range(occurrence + 1):
        idx = text.find(span, idx + 1)
        if idx < 0:
            return None
    err = text[:idx] + repl + text[idx + len(span) :]
    for width in (ctx, ctx * 2, ctx * 4, len(text)):
        s = max(0, idx - width)
        e = min(len(text), idx + len(span) + width)
        clean_win = text[s:e]
        shift = e + (len(repl) - len(span))
        err_win = err[s : max(e, shift)]
        if err_win.count(err_win) == 1 and err.replace(err_win, clean_win, 1) == text:
            return err, err_win, clean_win
    return None


# --------------------------------------------------------------------- specs
FACTUAL_SPECS = [
    ("refq-408-2021-16", "主存地址为32 位", "主存地址为4 位", "位宽与容量矛盾",
     "4 位主存地址只能覆盖 16B，与 Cache 数据区 32KB、主存块 32B 的编址前提矛盾"),
    ("refq-408-2023-12", "P 的平均CPI 为1.2",
     "P 的平均CPI 为0.5，且每条指令平均需要2 个时钟周期", "定义自相矛盾",
     "CPI 即每条指令平均时钟周期数，0.5 与「每条指令需 2 个时钟周期」不能同时成立"),
    ("refq-408-2022-34", "4 个幅值的ASK 调制", "4 个幅值的ASK 调制（每个符号携带3 个比特）",
     "调制阶数与比特数矛盾",
     "M 个幅值 ASK 每符号携带 log2(M) 比特，4 个幅值即 2 比特，不可能携带 3 比特"),
    ("refq-408-2022-38", "计时器发生了超时",
     "计时器发生了超时，且超时后拥塞窗口与慢开始门限均保持不变", "协议行为定义矛盾",
     "TCP 超时后必须令 ssthresh=cwnd/2 且 cwnd 重置为 1 个 MSS，不存在「均保持不变」"),
    ("refq-408-2019-39", "初始序列号分别为2018 和2046",
     "初始序列号分别为2018 和2046，且SYN 段不占用序列号", "协议规则矛盾",
     "SYN 段消耗一个序列号，确认号应为 ISN+1，与「不占用序列号」的附加前提冲突"),
    ("refq-408-2024-09", "是大根堆（最大堆）", "是小根堆（最小堆）", "性质与数据矛盾",
     "序列首元素 28 为全体最大值，只能是大根堆，冠以「小根堆」与数据矛盾"),
]

TM_FORMS = [
    ("简答题作答", "请结合各选项分别说明理由（简答题）。"),
    ("排序题作答", "请按重要性从高到低排列各选项序号。"),
    ("作图题作答", "请在答题卡上画出对应结构并标注关键结点。"),
    ("证明题作答", "请证明你的结论并写出完整推导过程。"),
    ("判断题作答", "请逐项判断各选项的正误（正确画√，错误画×）。"),
    ("多选指令", "本题为多项选择题，请选出所有符合题意的选项。"),
    ("计算过程要求", "请写出完整的计算过程与中间结果。"),
    ("英文作答要求", "请用英文专业术语作答。"),
    ("列举要求", "请列举出全部符合条件的对象并逐一说明。"),
    ("程序设计要求", "请给出实现该功能的完整代码片段。"),
    ("填空改造", "请将答案填写在横线上并说明依据。"),
    ("流程描述要求", "请描述该过程的完整执行流程并给出时序图。"),
]

OPT_VARIANTS = [
    ("标号重复", "dup"), ("圆圈数字标号", "circle"), ("末尾多余顿号", "tail_dun"),
    ("标号与内容粘连", "glue"), ("缺少首个标号", "no_prefix"), ("小写字母标号", "lower"),
    ("越界标号", "out_of_range"), ("混用右括号", "paren"), ("全角句点标号", "fullwidth"),
    ("标号错位重复", "wrong_dup"), ("顿号替代句点", "dot_to_dun"), ("末尾多余分号", "tail_semi"),
    ("方括号标号", "bracket"), ("双句点冗余", "double_dot"), ("末尾多余右括号", "tail_paren"),
    ("标号跳变", "jump"), ("标点重复堆叠", "dup_punc"), ("内容空白", "blank"),
]

TYPO_SHAPE = {"进": "珵", "缓": "緩", "总": "總", "线": "綫", "数": "數", "网": "網",
              "结": "結", "页": "頁", "调": "調", "储": "儲", "址": "阯", "址": "址"}

MI_PATTERNS = [
    ("删除括号限定", r"（[^）]{2,20}）"),
    ("删除条件从句", r"若[^，。]{2,18}，"),
    ("删除已知条件", r"已知[^，。]{2,18}，"),
    ("删除并列限定", r"，且[^，。]{2,16}"),
    ("删除方式限定", r"采用[^，。]{2,16}，"),
    ("删除范围限定", r"在[^，。]{2,12}中，"),
    ("删除插入分句", r"，[^，。]{4,18}，"),
    ("删除冒号说明", r"：[^，。]{2,20}，"),
    ("删除任意分句", r"，[^，。]{4,16}"),
]

AMB_OPS = [
    ("代词指代不明", "该", "某个未指明的对象"),
    ("范围泛化", "所有", "部分"),
    ("确定性弱化", "必须", "可能需要"),
    ("主体省略", "其", "上述对象之一"),
    ("边界缺失", "最多", "若干"),
    ("并列数量模糊", "分别", "各自或共同"),
    ("任意性扩大", "某个", "任意"),
    ("限定词缺失", "上述的", ""),
    ("限定词缺失", "相应的", ""),
    ("限定词缺失", "指定的", ""),
    ("限定词缺失", "特定的", ""),
]

PUNC_OPS = [
    ("逗号误用为顿号", "，", "、"), ("顿号误用为逗号", "、", "，"),
    ("句号误用为分号", "。", "；"), ("分号误用为逗号", "；", "，"),
    ("逗号误用为句号", "，", "。"), ("逗号误用为分号", "，", "；"),
]

LEAK_FORMS = [
    ("题干提示正确项", "（本题正确选项为{ans}）"),
    ("题干复述正确结论", "（正确选项的内容与教材结论一致）"),
    ("题干给出解题步骤", "（提示：按公式逐项代入即可得到答案）"),
    ("题干排除干扰项", "（选项A与B均可直接排除）"),
    ("题干给出中间结果", "（提示：中间计算结果已经确定）"),
]


def main() -> int:
    PHASE2.mkdir(parents=True, exist_ok=True)
    DATASET.mkdir(parents=True, exist_ok=True)

    sources = [json.loads(l) for l in (PHASE1 / "source_selection.jsonl").open(encoding="utf-8") if l.strip()]
    by_type: dict[str, list[dict]] = defaultdict(list)
    for s in sources:
        by_type[s["error_type"]].append(s)

    out: list[dict] = []
    rejected: list[dict] = []
    sub_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def emit(src, etype, subtype, clean, err, orig, corr, why):
        if orig:
            if err.replace(orig, corr, 1) != clean:
                rejected.append({"sample_id": src["sample_id"], "reason": "round_trip"})
                return
        if orig and err.count(orig) != 1:
            rejected.append({"sample_id": src["sample_id"], "reason": "anchor_not_unique"})
            return
        if not orig:
            rejected.append({"sample_id": src["sample_id"], "reason": "empty_original"})
            return
        out.append({
            "sample_id": src["sample_id"], "error_type": etype,
            "error_type_cn": TYPE_CN[etype], "error_detailed_type": subtype,
            "provenance": "new_synthesis", "source_record_id": src["source_record_id"],
            "source_subject": src["source_subject"], "source_year": src["source_year"],
            "reference": src["reference"], "clean_text": clean, "error_text": err,
            "original_text": orig, "correction": corr, "anchor_text": orig,
            "rationale": why, "source_answer": src["source_answer"],
        })
        sub_count[etype][subtype] += 1

    # ---------------- factual_logical (hand-authored)
    for rid, span, repl, subtype, why in FACTUAL_SPECS:
        src = next((s for s in by_type["factual_logical"] if s["source_record_id"] == rid), None)
        if src is None:
            rejected.append({"sample_id": rid, "reason": "factual_source_missing"})
            continue
        r = mutate_at(src["full_text"], span, repl)
        if not r:
            rejected.append({"sample_id": src["sample_id"], "reason": "factual_mutate_failed"})
            continue
        err, ew, cw = r
        emit(src, "factual_logical", subtype, src["full_text"], err, ew, cw, why)

    # ---------------- type_mismatch
    for i, src in enumerate(by_type["type_mismatch"]):
        subtype, instr = TM_FORMS[i % len(TM_FORMS)]
        clean = src["full_text"]
        stem, opts = split_stem(clean)
        if not opts or not stem.strip():
            rejected.append({"sample_id": src["sample_id"], "reason": "tm_no_options"})
            continue
        m = list(re.finditer(r"[。\.]", stem))
        pos = m[-1].start() if m else len(stem.rstrip()) - 1
        err = stem[: pos + 1] + instr + stem[pos + 1 :] + "\n" + "\n".join(opts)
        emit(src, "type_mismatch", subtype, clean, err, instr, "",
             f"单选题干被追加「{subtype}」指令，与四选一单项选择题型冲突")

    # ---------------- option_structure
    for i, src in enumerate(by_type["option_structure"]):
        subtype, kind = OPT_VARIANTS[i % len(OPT_VARIANTS)]
        clean = src["full_text"]
        stem, opts = split_stem(clean)
        if len(opts) < 4:
            rejected.append({"sample_id": src["sample_id"], "reason": "opts_lt_4"})
            continue
        tgt = 1 if kind in {"dup", "wrong_dup"} else 0
        line = opts[tgt].strip()
        mt = re.match(r"^([A-D])([\.．])", line)
        if not mt:
            rejected.append({"sample_id": src["sample_id"], "reason": "prefix_unparsed"})
            continue
        prefix, rest = mt.group(0), line[len(mt.group(0)) :]
        if kind == "dup":
            new = prefix + " " + prefix + " " + rest
        elif kind == "circle":
            new = "①" + " " + rest
        elif kind == "tail_dun":
            new = line + "、"
        elif kind == "glue":
            new = prefix + rest.lstrip()
        elif kind == "no_prefix":
            new = rest.lstrip()
        elif kind == "lower":
            new = prefix.lower() + rest
        elif kind == "out_of_range":
            new = "E" + prefix[1:] + rest
        elif kind == "paren":
            new = prefix[0] + ")" + rest
        elif kind == "fullwidth":
            new = prefix[0] + "．" + rest
        elif kind == "wrong_dup":
            prev = re.match(r"^([A-D])[\.．]", opts[0].strip()).group(0)
            new = prev + " " + rest
        elif kind == "dot_to_dun":
            new = prefix[0] + "、" + rest
        elif kind == "tail_semi":
            new = line + "；"
        elif kind == "bracket":
            new = "[" + prefix[0] + "]" + rest
        elif kind == "double_dot":
            new = prefix + "." + rest
        elif kind == "tail_paren":
            new = line + "）"
        elif kind == "jump":
            new = "F" + prefix[1:] + rest
        elif kind == "dup_punc":
            new = line.replace("，", "，，", 1) if "，" in rest else line + "，，"
        else:  # blank
            new = prefix + " "
        new_opts = list(opts)
        new_opts[tgt] = new
        err = (stem + "\n" if stem else "") + "\n".join(new_opts)
        emit(src, "option_structure", subtype, clean, err, new, line,
             f"选项排版被破坏：{subtype}")

    # ---------------- typo (shape / trad / extra / missing / order)
    typo_kinds = ["形近或繁体替换", "衍字", "脱字", "语序颠倒"]
    for i, src in enumerate(by_type["typo"]):
        subtype = typo_kinds[i % len(typo_kinds)]
        clean = src["full_text"]
        stem, opts = split_stem(clean)
        ok = None
        if subtype == "形近或繁体替换":
            for k, v in TYPO_SHAPE.items():
                if k in stem:
                    ok = mutate_at(clean, k, v)
                    if ok:
                        break
        elif subtype == "衍字":
            for m in re.finditer(r"[\u4e00-\u9fff]", stem):
                ch = m.group(0)
                ok = mutate_at(clean, ch, ch + ch, occurrence=0)
                if ok:
                    break
        elif subtype == "脱字":
            for m in re.finditer(r"[\u4e00-\u9fff]{2}", stem):
                ch = m.group(0)[1]
                ok = mutate_at(clean, ch, "")
                if ok:
                    break
        else:
            for m in re.finditer(r"([\u4e00-\u9fff])([\u4e00-\u9fff])", stem):
                pair = m.group(0)
                ok = mutate_at(clean, pair, pair[::-1])
                if ok:
                    break
        if not ok:
            rejected.append({"sample_id": src["sample_id"], "reason": f"typo_{subtype}"})
            continue
        err, ew, cw = ok
        emit(src, "typo", subtype, clean, err, ew, cw, f"文字错误：{subtype}")

    def pick(candidates, etype):
        """Choose the candidate whose subtype is currently least used."""
        return min(candidates, key=lambda c: sub_count[etype][c[0]])

    # ---------------- punctuation (rotate over actually-applicable ops)
    for i, src in enumerate(by_type["punctuation"]):
        candidates = []
        for subtype_try, old, new in PUNC_OPS:
            for occ in range(8):
                ok = mutate_at(src["full_text"], old, new, occurrence=occ)
                if ok:
                    candidates.append((subtype_try, ok))
                    break
        if not candidates:
            rejected.append({"sample_id": src["sample_id"], "reason": "punc_no_op"})
            continue
        subtype, (err, ew, cw) = pick(candidates, "punctuation")
        emit(src, "punctuation", subtype, src["full_text"], err, ew, cw, f"标点误用：{subtype}")

    # ---------------- missing_info
    for i, src in enumerate(by_type["missing_info"]):
        candidates = []
        for subtype_try, pat in MI_PATTERNS:
            for m in re.finditer(pat, src["full_text"]):
                ok = mutate_at(src["full_text"], m.group(0), "")
                if ok:
                    candidates.append((subtype_try, ok))
                    break
        if not candidates:
            rejected.append({"sample_id": src["sample_id"], "reason": "mi_no_op"})
            continue
        subtype, (err, ew, cw) = pick(candidates, "missing_info")
        emit(src, "missing_info", subtype, src["full_text"], err, ew, cw,
             f"删除题面前提，使作答所需条件不再完整（{subtype}）")

    # ---------------- ambiguity
    for i, src in enumerate(by_type["ambiguity"]):
        candidates = []
        for subtype_try, good, bad in AMB_OPS:
            for occ in range(8):
                ok = mutate_at(src["full_text"], good, bad, occurrence=occ)
                if ok:
                    candidates.append((subtype_try, ok))
                    break
        for kw, label, repl in (
            ("任意", "任意性扩大", "某个"),
            ("均", "全称量化弱化", "部分"),
            ("都", "全称量化弱化", "部分"),
            ("和", "逻辑连接词歧义", "或"),
            ("与", "逻辑连接词歧义", "或"),
            ("仅", "范围限定弱化", "包含但不限于"),
        ):
            ok = mutate_at(src["full_text"], kw, repl, occurrence=0)
            if ok:
                candidates.append((label, ok))
        if not candidates:
            rejected.append({"sample_id": src["sample_id"], "reason": "amb_no_op"})
            continue
        subtype, (err, ew, cw) = pick(candidates, "ambiguity")
        emit(src, "ambiguity", subtype, src["full_text"], err, ew, cw,
             f"{subtype}：明确表述被改为模糊表述")

    # ---------------- unsolvable
    num_re = r"\d+(?:\.\d+)?\s*(?:KB|MB|kB|GB|ms|us|μs|ns|B|bit|Hz|MHz|GHz|个|条|位|级|台)"
    for i, src in enumerate(by_type["unsolvable"]):
        clean = src["full_text"]
        candidates = []
        for m in re.finditer(num_re, clean):
            ok = mutate_at(clean, m.group(0), "给定的某个值")
            if ok:
                candidates.append(("数值改为模糊占位符", ok))
                break
        for m in re.finditer(r"\d+\s*(?:个|条|台|位|级)", clean):
            ok = mutate_at(clean, m.group(0), "")
            if ok:
                candidates.append(("删除计数条件", ok))
                break
        for m in re.finditer(r"（[^）]{2,20}）", clean):
            ok = mutate_at(clean, m.group(0), "")
            if ok:
                candidates.append(("删除关键参数", ok))
                break
        for kw in ("最大", "最小", "唯一", "确定"):
            ok = mutate_at(clean, kw, "某个")
            if ok:
                candidates.append(("删除极值或确定性目标", ok))
                break
        for m in re.finditer(
            r"直接映射|全相联|组相联|请求分页|虚拟存储|同步总线|异步总线"
            r"|写直达|大根堆|小根堆|单缓冲|双缓冲",
            clean,
        ):
            ok = mutate_at(clean, m.group(0), "某种未指明的机制")
            if ok:
                candidates.append(("关键机制未指明", ok))
                break
        if not candidates:
            rejected.append({"sample_id": src["sample_id"], "reason": "uns_no_op"})
            continue
        subtype, (err, ew, cw) = pick(candidates, "unsolvable")
        emit(src, "unsolvable", subtype, clean, err, ew, cw, f"{subtype}：题干无法唯一确定答案")

    # ---------------- answer_leakage
    for i, src in enumerate(by_type["answer_leakage"]):
        subtype, tmpl = LEAK_FORMS[i % len(LEAK_FORMS)]
        clean = src["full_text"]
        stem, opts = split_stem(clean)
        if not opts or not stem.strip():
            rejected.append({"sample_id": src["sample_id"], "reason": "leak_no_options"})
            continue
        ans = (src.get("source_answer") or "").strip()[:1] or "A"
        injected = tmpl.replace("{ans}", ans)
        m = re.search(r"下列", stem)
        idx = m.start() if m else len(stem.rstrip())
        stem2 = stem[:idx] + injected + stem[idx:]
        err = stem2 + "\n" + "\n".join(opts)
        emit(src, "answer_leakage", subtype, clean, err, injected, "",
             f"题干注入「{subtype}」信息，直接或间接透露答案")

    # ---------------- clean
    for src in by_type["none"]:
        out.append({
            "sample_id": src["sample_id"], "error_type": "none",
            "error_type_cn": "正常题（正样本）", "error_detailed_type": "clean_unmodified",
            "provenance": "new_clean_unseen", "source_record_id": src["source_record_id"],
            "source_subject": src["source_subject"], "source_year": src["source_year"],
            "reference": src["reference"], "clean_text": src["full_text"],
            "error_text": src["full_text"], "original_text": "", "correction": "",
            "anchor_text": "", "rationale": "未经修改的真实 408 真题，作为零虚警基准",
            "source_answer": src["source_answer"],
        })

    # ---------------- write
    with (PHASE2 / "mutation_manifest.jsonl").open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (PHASE2 / "rejected.jsonl").open("w", encoding="utf-8") as f:
        for r in rejected:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    errors = [r for r in out if r["error_type"] != "none"]
    with (DATASET / "blind_v2_dataset.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "label", "error_type", "error_detailed_type", "subject",
                    "year", "source_record_id", "full_text", "reference"])
        for r in out:
            w.writerow([r["sample_id"], "clean" if r["error_type"] == "none" else "error",
                        r["error_type"], r["error_detailed_type"], r["source_subject"],
                        r["source_year"], r["source_record_id"], r["error_text"], r["reference"]])

    with (DATASET / "blind_v2_gold.jsonl").open("w", encoding="utf-8") as f:
        for r in out:
            has = r["error_type"] != "none"
            f.write(json.dumps({
                "sample_id": r["sample_id"], "error_type": r["error_type"],
                "has_error": has, "total_errors": 1 if has else 0,
                "errors": [{"error_type": r["error_type"], "original_text": r["original_text"],
                            "anchor_text": r["anchor_text"], "correction": r["correction"],
                            "description": r["rationale"]}] if has else [],
            }, ensure_ascii=False) + "\n")

    with (DATASET / "blind_v2_full.jsonl").open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"accepted: {len(out)} (errors {len(errors)}, clean {len(out) - len(errors)})")
    print(f"rejected: {len(rejected)}")
    for et in ["typo", "punctuation", "option_structure", "missing_info", "ambiguity",
               "unsolvable", "answer_leakage", "type_mismatch", "factual_logical"]:
        c = sub_count.get(et, {})
        t = sum(c.values())
        if not t:
            print(f"  {et:<18} MISSING")
            continue
        print(f"  {et:<18} {t:>3} items, {len(c)} subtypes, max {max(c.values()) / t * 100:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
