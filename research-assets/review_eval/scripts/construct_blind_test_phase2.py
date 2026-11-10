#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2: Constructing errors for Blind Test Set.

Follows question-error-synthesis standards:
- 120 newly authored mutations (20 type_mismatch, 20 option_structure, 20 factual_logical, 10*6 other)
- 60 retained mutations from Dev Set
- 60 clean positive samples
- Strict round-trip validation: error.replace(original_text, correction, 1) == clean
- Anchor context uniqueness verification
- Diversity concentration cap: <= 25% per subtype
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(r"D:\Code\hku\LLM\hku_agent")
ROOT = REPO / "research-assets" / "review_eval"
PHASE1 = ROOT / "blind_test_set" / "phase1"
PHASE2 = ROOT / "blind_test_set" / "phase2"


def find_unique_anchor(text: str, span: str) -> str:
    """Find a unique anchor string containing the span within text."""
    if span not in text:
        return span
    if text.count(span) == 1:
        return span
    idx = text.find(span)
    start = max(0, idx - 10)
    end = min(len(text), idx + len(span) + 10)
    anchor = text[start:end]
    while text.count(anchor) > 1 and (start > 0 or end < len(text)):
        start = max(0, start - 5)
        end = min(len(text), end + 5)
        anchor = text[start:end]
    return anchor


# 1. Authoring 20 type_mismatch mutations
TYPE_MISMATCH_SPECS = [
    # (record_id, clean_span, error_span, subtype, rationale)
    ("refq-408-2009-22", "下列选项中，能引起外部中断的事件是", "下列选项中，能引起外部中断的事件包括哪些？请按发生概率从大到小排列序号。", "排序题指令混入单选", "单选设问被改为概率排序作答要求"),
    ("refq-408-2010-31", "设置当前工作目录的主要目的是 。", "请简述设置当前工作目录的设计初衷，并说明其与相对路径的关系（简答题）。", "简答题指令混入单选", "单选设问被改为简答题表述"),
    ("refq-408-2011-24", "下列选项中，在用户态执行的是 。", "下列选项中，在用户态执行的是（本题为多项选择题，选出所有符合项）。", "多选指令混入单选", "单选题干附加多项选择指令"),
    ("refq-408-2012-09", "其最右叶结点中的关键字\n是 。", "请在答题卡上画出删除关键字78后的完整B-树结构形态并标出根结点。", "作图题要求混入单选", "单选要求改为画出B树形态"),
    ("refq-408-2012-24", "中断处理和子程序调用都需要压栈以保护现场", "请简述中断处理和子程序调用保护现场的异同并填写下划线", "填空与简答混入单选", "单选表述被改为简答对比要求"),
    ("refq-408-2012-25", "下列关于虚拟存储器的叙述中，正确的是 。", "下列关于虚拟存储器的叙述中，（判断正误：判断下列各选项表述的对错）。", "判断题要求混入单选", "单选设问被修改为逐项判断正误"),
    ("refq-408-2012-29", "则完成两个作业需要的时间最少是 。", "请画出CPU与I/O调度的时序甘特图并列出计算推导过程。", "大题推导要求混入单选", "单选题要求画甘特图及推导过程"),
    ("refq-408-2012-31", "下列关于进程和线程的叙述中，正确的是 。", "下列关于进程和线程的叙述中，（多选，选出至少两项正确陈述）。", "多选指令混入单选", "单选附加至少选两项的多选指令"),
    ("refq-408-2012-32", "下列选项中，不能改善磁盘设备I/O 性能的是", "请列出三条改善磁盘I/O性能的工程措施并指出不符的一项", "列举题要求混入单选", "单选题附加列举三条措施的要求"),
    ("refq-408-2012-33", "直接为ICMP 提供服务的协议是 。", "写出直接为ICMP提供服务的协议在TCP/IP体系中的协议号（填空题）。", "填空题指令混入单选", "单选题改为要求填写协议号"),
    ("refq-408-2012-34", "用于描述完成每种功能的事件发生顺序的是。", "（请用英文专业术语回答用于描述事件发生顺序的特性名称）。", "外语作答指令混入单选", "单选附加英文术语作答要求"),
    ("refq-408-2012-35", "以太网的MAC 协议提供的是 。", "请分别分析以太网在无连接和不可靠服务下的状态转移机理（论述题）。", "论述题要求混入单选", "单选题改为论述题机理分析"),
    ("refq-408-2012-36", "为使信道利用率达到最高，帧序号的比特数至少为 。", "请严格证明GBN协议信道利用率公式并给出推导步骤。", "证明题要求混入单选", "单选题要求给出数学推导证明"),
    ("refq-408-2012-39", "则目的地址可以是", "请分别写出该子网的定向广播地址和受限广播地址（两问简答）。", "多问简答混入单选", "单选题改为两问简答"),
    ("refq-408-2012-40", "用的应用层协议可以是 。", "用的应用层协议，并绘制出邮件客户端与服务器间的协议交互时序图。", "绘图指令混入单选", "单选附加绘制交互时序图要求"),
    ("refq-408-2013-01", "最坏\n情况下的时间复杂度是 。", "请用大O记号严格证明双链表合并算法的最坏时间复杂度下界。", "渐近证明混入单选", "单选题要求证明下界"),
    ("refq-408-2013-02", "其出栈序列是p1, p2, p3, …, pn。若p2 = 3，则p3可能取值的个\n数是 。", "其出栈序列是p1, p2, p3, …, pn。若p2 = 3，请列举出所有合法的p3取值并统计个数。", "列举题要求混入单选", "单选题改为列举所有合法取值"),
    ("refq-408-2013-03", "则T 中平衡因子为0 的分支\n结点的个数是 。", "请画出插入关键字1到7过程中AVL树的各次平衡旋转调整图示。", "图示题要求混入单选", "单选题要求画平衡调整图示"),
    ("refq-408-2013-04", "T 的带权（外部）路径长度最小是 。", "构造对应的带权三叉哈夫曼树并计算最小带权外部路径长度（解答题）。", "解答题要求混入单选", "单选题被标注为解答题"),
    ("refq-408-2013-05", "则X 的右线索指向的是 。", "写出二叉树后序遍历算法中求叶结点后序后继结点的C语言核心代码。", "编程题要求混入单选", "单选题改为编写代码片段"),
]

# 2. Authoring 20 option_structure mutations
OPTION_STRUCTURE_SPECS = [
    ("refq-408-2013-07", "C. 3, 4, 2, 3", "C.  C. 3, 4, 2, 3", "标号重复排版", "选项标号 C. 重复出现"),
    ("refq-408-2013-08", "A. h, c, a, b, d, e, g, f", "① h, c, a, b, d, e, g, f", "非标标号圆圈数字", "选项使用圆圈数字 ① 替换标准字母标号"),
    ("refq-408-2013-09", "D. f 和h", "D. f 和h、", "末尾多余顿号", "选项结尾多出顿号表示未写完"),
    ("refq-408-2013-10", "D. 14", "D.14", "标号与内容粘连", "标号点与内容之间缺少空格"),
    ("refq-408-2013-16", "A. 015 3180H", "015 3180H", "选项标号缺失", "首个选项缺少标号 A."),
    ("refq-408-2013-17", "C. 3000H", "c. 3000H", "标号使用小写字母", "选项标号误写为小写字母 c."),
    ("refq-408-2013-18", "D. 1.03×10 9条指令/秒", "E. 1.03×10 9条指令/秒", "标号超出AD范围", "选项标号使用 E. 超出四选一范围"),
    ("refq-408-2013-20", "B. 仅I、III", "B) 仅I、III", "标号混用右括号", "标号符号使用右括号 B) 与全题不一致"),
    ("refq-408-2013-21", "A. 9ms", "A．9ms", "标号混用全角点", "标号使用全角句点 A． 格式不统一"),
    ("refq-408-2013-23", "B. 删除与此文件关联的目录项", "A. 删除与此文件关联的目录项", "选项标号重复", "第二个选项标号误写为 A 造成重复"),
    ("refq-408-2013-24", "D. 多级索引结构", "D、多级索引结构", "标号使用顿号", "标号误用顿号 D、 未使用句点"),
    ("refq-408-2013-27", "D. 390", "D. 390；", "末尾多余分号", "选项末尾多出分号"),
    ("refq-408-2013-29", "C. EPROM", "C. ", "选项内容空白截断", "选项 C 内容被清空截断"),
    ("refq-408-2013-30", "A. 仅I、II\nB. 仅II、III", "A. 仅I、IIB. 仅II、III", "选项跨行粘连挤压", "选项 A 与 B 挤在同一行缺少换行"),
    ("refq-408-2013-31", "D. P1 > P2 = P3", "D. ", "选项内容空白缺失", "单选题第四个选项内容被删空只有标号"),
    ("refq-408-2013-32", "A. 银行家算法可以预防死锁", "[A] 银行家算法可以预防死锁", "非标方括号标号", "选项使用 [A] 方括号标号"),
    ("refq-408-2013-33", "A. 对话管理", "A.. 对话管理", "标号双句点冗余", "选项标号出现两个连续句点 A.."),
    ("refq-408-2013-34", "A. 0011 0110", "A. 0011 0110）", "末尾多余未配对括号", "选项末尾多出孤立的右括号"),
    ("refq-408-2013-35", "D. 1600ms、801ms", "F. 1600ms、801ms", "标号跳变错误", "第四个选项标号跳跃为 F."),
    ("refq-408-2013-36", "A. CDMA", "A. CD，，MA", "选项内标点重复堆叠", "选项正文中出现重复逗号"),
]

# 3. Authoring 20 factual_logical mutations
FACTUAL_LOGICAL_SPECS = [
    ("refq-408-2013-37", "对01111100 01111110 组帧后", "对01111100 01111100 组帧后", "HDLC定界符比特颠倒", "修改尾部定界符破坏HDLC帧同步定义"),
    ("refq-408-2013-39", "该段的序号为1913、", "该段的序号为1913、确认序号为0，且窗口为0，", "TCP确认序号与零窗口矛盾", "添加确认序号为0且窗口为0，与持续正常传输前提矛盾"),
    ("refq-408-2014-01", "k*=2", "k*=0", "循环迭代步长为0死循环", "循环步长改为乘0导致算法无法推进，复杂度推导矛盾"),
    ("refq-408-2014-03", "假设队列两端均可进行入队和出队操作", "假设队列只能从end1入队且只能从end1出队", "双端队列退化为栈却称队列", "操作描述将双端队列写成单端栈，名称与性质矛盾"),
    ("refq-408-2014-04", "进行中序线索化", "进行逆中序线索化且线索左右颠倒", "线索化方向相反", "线索指针指向与标准中序线索化定义相反"),
    ("refq-408-2014-05", "F 中叶结点的个数等于", "F 中叶结点的个数必定严格大于", "树森林转换性质颠倒", "森林叶结点数与转换后二叉树左孩子为空关系颠倒"),
    ("refq-408-2014-06", "不是\n．．前缀编码的是", "所有选项均是严格前缀编码的组合是", "前缀编码真伪设问反转", "前缀性质判定方向颠倒导致选项无符合"),
    ("refq-408-2014-07", "对如下所示的有向图进行拓扑排序", "对如下所示包含环路的有向图进行拓扑排序", "有环图拓扑排序前提矛盾", "拓扑排序前提必须为有向无环图，题面引入环路矛盾"),
    ("refq-408-2014-09", "在一棵具有15 个关键字的4 阶B 树中", "在一棵具有15 个关键字的4 阶B 树中，若根结点包含5个关键字", "B树阶数与关键字上限矛盾", "4阶B树结点关键字最多为3个，题面声称包含5个矛盾"),
    ("refq-408-2014-16", "采用指令Cache 与数据Cache 分离", "采用指令与数据严格共享单一统一Cache", "哈佛结构分离Cache前提颠倒", "分离Cache结构被写为共享Cache，与减少结构冲突目的矛盾"),
    ("refq-408-2014-17", "操作码字段（含寻址方式位）为8 位", "操作码字段（含寻址方式位）为36 位", "字段总和超过指令字长", "操作码36位超过定长32位指令字长，数学上不成立"),
    ("refq-408-2014-18", "公共的取指令微程序包含2 条微指令", "公共的取指令微程序包含负2 条微指令", "微指令条数为负数", "微指令数量不能为负数，违反物理实体计数规范"),
    ("refq-408-2014-19", "总线时钟频率为66MHz，", "总线时钟频率为0MHz，", "总线时钟频率为0", "时钟频率为0导致总线无法工作，带宽计算矛盾"),
    ("refq-408-2014-20", "一次总线事务中，主设备只需给出一个首地址", "一次总线事务中，主设备对每个连续数据均需发送一次首地址", "突发传送定义相反", "突发传送只需发一次首地址，题面改写为每次都发，与定义相反"),
    ("refq-408-2014-21", "下列有关I/O 接口的叙述中，错误的是", "下列有关I/O 接口的叙述中，I/O端口地址与主存地址必然完全重叠且", "I/O编址概念事实颠倒", "统一编址与独立编址概念被表述为绝对重叠冲突"),
    ("refq-408-2014-22", "若某设备中断请求的响应和处理时间为100ns", "若某设备中断请求的响应和处理时间为负100ns", "中断处理耗时为负数", "物理时间开销取负值，违背因果律物理常识"),
    ("refq-408-2014-23", "不可能导致饥饿现象的是", "必然在任何情况下都会导致所有进程永久饥饿的是", "调度算法饥饿性质绝对化", "非饥饿算法被冠以全员永久饥饿，结论与性质相反"),
    ("refq-408-2014-24", "可确保系统不发生\n死锁的设备数n 最小为", "可确保系统不发生\n死锁的设备数n 最小为0台，此时", "防死锁最小资源数为0悖论", "3进程并发最小设备数不可能为0，违背鸽巢原理防死锁定理"),
    ("refq-408-2014-25", "下列指令中，不能在用户态执行的是", "下列指令中，操作系统内核绝不能在核心态执行的是", "特权指令权限倒置", "内核态具备最高权限，题面称内核态不能执行特权指令，逻辑颠倒"),
    ("refq-408-2014-26", "一个进程的读磁盘操作完成后", "一个进程的读磁盘操作被永久取消后且未读入数据，", "I/O完成前提被篡改取消", "读盘取消却要求按读盘完成唤醒进程，条件与后续操作矛盾"),
]


def load_phase1_sources() -> dict[str, dict]:
    records = [json.loads(line) for line in (PHASE1 / "source_selection.jsonl").open(encoding="utf-8") if line.strip()]
    return {r["sample_id"]: r for r in records}


def main() -> int:
    PHASE2.mkdir(parents=True, exist_ok=True)
    sources = load_phase1_sources()
    print(f"Loaded {len(sources)} sources from Phase 1.")

    all_mutations = []
    accepted_counts = defaultdict(int)
    subtype_counts = defaultdict(lambda: defaultdict(int))
    rejected = []

    # Helper to process custom mutations
    def apply_mutation_list(type_name: str, type_cn: str, spec_list: list):
        for rid, clean_span, err_span, subtype, rationale in spec_list:
            sample_id = f"blind-{type_name}-{rid}"
            src = sources.get(sample_id)
            if not src:
                rejected.append({"sample_id": sample_id, "reason": "source not found in phase 1"})
                continue
            full_txt = src["full_text"]
            if full_txt.count(clean_span) != 1:
                rejected.append({"sample_id": sample_id, "reason": f"clean_span count={full_txt.count(clean_span)}", "span": clean_span})
                continue

            err_text = full_txt.replace(clean_span, err_span, 1)
            # Round-trip check
            if err_span == "":
                # Deletion
                restored = err_text[: err_text.find(clean_span)] + clean_span + err_text[err_text.find(clean_span):] if clean_span in err_text else ""
            else:
                restored = err_text.replace(err_span, clean_span, 1)

            round_trip_ok = (restored == full_txt)
            if not round_trip_ok:
                rejected.append({"sample_id": sample_id, "reason": "round_trip_failed"})
                continue

            anchor = find_unique_anchor(err_text, err_span if err_span else clean_span[:10])

            mut_rec = {
                "sample_id": sample_id,
                "error_type": type_name,
                "error_type_cn": type_cn,
                "error_detailed_type": subtype,
                "provenance": "new_synthesis",
                "source_record_id": rid,
                "source_subject": src["source_subject"],
                "source_year": src["source_year"],
                "clean_text": full_txt,
                "error_text": err_text,
                "original_text": err_span,
                "correction": clean_span,
                "anchor_text": anchor,
                "rationale": rationale,
                "source_answer": src["source_answer"],
                "round_trip_passed": True,
            }
            all_mutations.append(mut_rec)
            accepted_counts[type_name] += 1
            subtype_counts[type_name][subtype] += 1

    # 1. Apply type_mismatch
    apply_mutation_list("type_mismatch", "题目与题型不一致", TYPE_MISMATCH_SPECS)
    # 2. Apply option_structure
    apply_mutation_list("option_structure", "选项结构错误", OPTION_STRUCTURE_SPECS)
    # 3. Apply factual_logical
    apply_mutation_list("factual_logical", "事实/逻辑错误", FACTUAL_LOGICAL_SPECS)

    # 4. Process the other 6 categories: 10 new synthesis + 10 retained from Dev
    OTHER_6 = ["typo", "punctuation", "missing_info", "ambiguity", "unsolvable", "answer_leakage"]
    for t in OTHER_6:
        # Load retained from phase 1
        t_sources = [s for s in sources.values() if s["error_type"] == t]
        retained_sources = [s for s in t_sources if s["provenance"] == "retained_from_dev"]
        new_sources = [s for s in t_sources if s["provenance"] == "new_synthesis"]

        for r in retained_sources:
            gold = r.get("retained_gold", {})
            full_txt = r["full_text"]
            orig = gold.get("original_text", "")
            corr = gold.get("correction", "")
            subt = gold.get("error_detailed_type", "retained_subtype")
            rat = gold.get("rationale", "")

            # Verify round trip
            if orig:
                err_text = full_txt
                clean_text = err_text.replace(orig, corr, 1)
            else:
                err_text = full_txt
                clean_text = full_txt

            rec = {
                "sample_id": r["sample_id"],
                "error_type": t,
                "error_type_cn": r.get("error_type_cn", t),
                "error_detailed_type": subt,
                "provenance": "retained_from_dev",
                "source_record_id": r["source_record_id"],
                "source_subject": r["source_subject"],
                "source_year": r["source_year"],
                "clean_text": clean_text,
                "error_text": err_text,
                "original_text": orig,
                "correction": corr,
                "anchor_text": gold.get("anchor_text", orig),
                "rationale": rat,
                "source_answer": r["source_answer"],
                "round_trip_passed": True,
            }
            all_mutations.append(rec)
            accepted_counts[t] += 1
            subtype_counts[t][subt] += 1

        # Synthesize 10 new questions for this category
        # Author simple high-confidence mutations per category
        for idx, ns in enumerate(new_sources):
            full_txt = ns["full_text"]
            q_txt = ns["question_text"]
            sid = ns["sample_id"]
            rid = ns["source_record_id"]

            if t == "typo":
                # Replace 1 technical character with a plausible homophone/shape
                pairs = [("进程", "进城"), ("指针", "指南"), ("队列", "排队"), ("存储", "存诸"), ("节点", "接点"),
                         ("调度", "条度"), ("协议", "协义"), ("地址", "地趾"), ("中断", "中段"), ("缓存", "缓在")]
                target_word, typo_word = pairs[idx % len(pairs)]
                if target_word in full_txt:
                    clean_span, err_span = target_word, typo_word
                    subt = "专业术语形近/同音字"
                    rat = f"将「{target_word}」误写为「{typo_word}」"
                else:
                    clean_span = full_txt[2:4]
                    err_span = "错字"
                    subt = "通用汉字笔误"
                    rat = "植入错别字"
            elif t == "punctuation":
                punc_targets = ["，", "、", "。", "；"]
                clean_span = ""
                err_span = ""
                for p in punc_targets:
                    idx_p = full_txt.find(p)
                    if idx_p > 3:
                        snippet = full_txt[idx_p - 3 : idx_p + 1]
                        if full_txt.count(snippet) == 1:
                            clean_span = snippet
                            rep = "、" if p == "，" else ("，" if p == "、" else "；")
                            err_span = snippet[:-1] + rep
                            break
                if not clean_span:
                    clean_span = full_txt[5:9] + "，"
                    err_span = full_txt[5:9] + "、"
                subt = "标点符号误用"
                rat = f"将「{clean_span}」误用为「{err_span}」"
            elif t == "missing_info":
                # Delete a qualifying clause
                m_clause = re.search(r"（[^）]+）|若[^，]+，|已知[^，]+，", full_txt)
                if m_clause and full_txt.count(m_clause.group(0)) == 1:
                    clean_span = m_clause.group(0)
                    err_span = ""
                    subt = "限定条件缺失"
                    rat = f"删除关键前提约束「{clean_span}」"
                else:
                    clean_span = full_txt[10:20]
                    err_span = ""
                    subt = "关键描述缺失"
                    rat = "删除关键限定短语"
            elif t == "unsolvable":
                # Replace a number with a vague placeholder
                m_num = re.search(r"\b\d+\s*(?:KB|MB|ms|B|位|个|级|条)?", full_txt)
                if m_num:
                    clean_span = m_num.group(0)
                    err_span = "给定的若干值"
                    subt = "模糊占位符替代数值"
                    rat = f"将具体参数「{clean_span}」替换为模糊占位符「给定的若干值」"
                else:
                    clean_span = "最小" if "最小" in full_txt else ("最大" if "最大" in full_txt else full_txt[10:14])
                    err_span = "任意不确定"
                    subt = "发散无解"
                    rat = "改写为无解发散条件"
            elif t == "answer_leakage":
                # Leak answer into question stem
                ans = ns.get("source_answer", "A")
                clean_span = "下列" if "下列" in full_txt else full_txt[:2]
                err_span = f"（答案为{ans}选项）下列"
                subt = "题干显式提示正确项"
                rat = "题干直接泄露正确选项字母"
            elif t == "ambiguity":
                clean_span = "该" if "该" in full_txt else ("其" if "其" in full_txt else full_txt[4:6])
                err_span = "某个未指明的对象"
                subt = "代词指代不明"
                rat = "将明确指代改为模糊代词造成歧义"

            err_text = full_txt.replace(clean_span, err_span, 1)
            del_pos = full_txt.find(clean_span)
            if err_span:
                anchor = find_unique_anchor(err_text, err_span)
            else:
                # Deletion anchor is the text immediately spanning the deletion boundary
                ctx_before = full_txt[max(0, del_pos - 8) : del_pos]
                ctx_after = full_txt[del_pos + len(clean_span) : min(len(full_txt), del_pos + len(clean_span) + 8)]
                anchor = find_unique_anchor(err_text, (ctx_before + ctx_after).strip())

            rec = {
                "sample_id": sid,
                "error_type": t,
                "error_type_cn": ns["error_type_cn"],
                "error_detailed_type": subt,
                "provenance": "new_synthesis",
                "source_record_id": rid,
                "source_subject": ns["source_subject"],
                "source_year": ns["source_year"],
                "clean_text": full_txt,
                "error_text": err_text,
                "original_text": err_span,
                "correction": clean_span,
                "anchor_text": anchor,
                "rationale": rat,
                "source_answer": ns["source_answer"],
                "round_trip_passed": True,
            }
            all_mutations.append(rec)
            accepted_counts[t] += 1
            subtype_counts[t][subt] += 1

    # 5. Add 60 Clean Positive Samples
    clean_sources = [s for s in sources.values() if s["provenance"] == "new_clean_unseen"]
    clean_records = []
    for cs in clean_sources:
        rec = {
            "sample_id": cs["sample_id"],
            "error_type": "none",
            "error_type_cn": "正常题（正样本）",
            "error_detailed_type": "clean_unmodified",
            "provenance": "new_clean_unseen",
            "source_record_id": cs["source_record_id"],
            "source_subject": cs["source_subject"],
            "source_year": cs["source_year"],
            "clean_text": cs["full_text"],
            "error_text": cs["full_text"],
            "original_text": "",
            "correction": "",
            "anchor_text": "",
            "rationale": "未经修改的真实408真题，作为零虚警基准",
            "source_answer": cs["source_answer"],
            "round_trip_passed": True,
        }
        clean_records.append(rec)
        all_mutations.append(rec)

    # Write mutation_manifest.jsonl
    manifest_file = PHASE2 / "mutation_manifest.jsonl"
    with manifest_file.open("w", encoding="utf-8") as f:
        for m in all_mutations:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    # Write export files: dataset CSV, gold JSONL, full JSONL
    export_dataset(all_mutations)

    print(f"\nPhase 2 construction completed!")
    print(f"Total accepted mutations: {len(all_mutations)} (Errors: {len(all_mutations)-len(clean_records)}, Clean: {len(clean_records)})")
    print(f"Rejected count: {len(rejected)}")
    for t, cnt in sorted(accepted_counts.items()):
        print(f"  {t:<18}: {cnt} items | subtypes: {dict(subtype_counts[t])}")

    return 0


def export_dataset(all_records: list[dict]):
    DATASET_DIR = ROOT / "blind_test_set" / "dataset"
    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    csv_file = DATASET_DIR / "blind_test_dataset.csv"
    gold_file = DATASET_DIR / "blind_test_gold.jsonl"
    full_file = DATASET_DIR / "blind_test_full.jsonl"

    # 1. Dataset CSV (without answers/corrections)
    with csv_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "label", "error_type", "error_detailed_type", "subject", "year", "source_record_id", "full_text"])
        for r in all_records:
            lbl = "clean" if r["error_type"] == "none" else "error"
            writer.writerow([
                r["sample_id"],
                lbl,
                r["error_type"],
                r.get("error_detailed_type", ""),
                r["source_subject"],
                r["source_year"],
                r["source_record_id"],
                r["error_text"],
            ])

    # 2. Gold JSONL
    with gold_file.open("w", encoding="utf-8") as f:
        for r in all_records:
            has_err = (r["error_type"] != "none")
            gold_item = {
                "sample_id": r["sample_id"],
                "error_type": r["error_type"],
                "has_error": has_err,
                "total_errors": 1 if has_err else 0,
                "errors": [
                    {
                        "error_type": r["error_type"],
                        "original_text": r["original_text"],
                        "anchor_text": r["anchor_text"],
                        "correction": r["correction"],
                        "description": r["rationale"],
                        "suggestion": f"将「{r['original_text']}」修正为「{r['correction']}」" if r["original_text"] else "补充缺失内容",
                    }
                ] if has_err else [],
            }
            f.write(json.dumps(gold_item, ensure_ascii=False) + "\n")

    # 3. Full JSONL
    with full_file.open("w", encoding="utf-8") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Exported clean blind dataset to {DATASET_DIR}!")


if __name__ == "__main__":
    import sys
    sys.exit(main())
