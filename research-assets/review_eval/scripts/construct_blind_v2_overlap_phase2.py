"""Build the hand-authored Phase-2 mutations for the Blind-v2 expansion.

Every semantic edit in ``MUTATIONS`` is authored individually.  Code below the
mapping only applies edits and validates bookkeeping invariants.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "blind_v2_expansion" / "runs" / "blind_v2_overlap_expansion_20261031"


def edit(
    clean_span: str,
    error_span: str,
    operation: str,
    location: str,
    token_class: str,
    rationale: str,
    *,
    original_text: str | None = None,
    correction: str | None = None,
    anchor_text: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "clean_span": clean_span,
        "error_span": error_span,
        "operation": operation,
        "location": location,
        "token_class": token_class,
        "rationale": rationale,
        "original_text": error_span if original_text is None else original_text,
        "correction": clean_span if correction is None else correction,
        "anchor_text": error_span if anchor_text is None else anchor_text,
        "evidence": evidence or {},
    }


MUTATIONS: dict[str, dict[str, Any]] = {
    # punctuation
    "v2x-punctuation-001": edit(
        "机器处于“开中断” 状态。",
        "机器处于“开中断。” 状态",
        "move_sentence_mark_inside_quote",
        "stem-condition",
        "quote-boundary-punctuation",
        "把属于外层句子的句号移入术语引号，破坏引号与句末标点的边界。",
        original_text="“开中断。” 状态",
        correction="“开中断” 状态。",
        anchor_text="机器处于“开中断。” 状态",
    ),
    "v2x-punctuation-002": edit(
        "3, …, n",
        "3, …，, n",
        "duplicate_list_separator_after_ellipsis",
        "stem-sequence",
        "ellipsis-plus-double-comma",
        "省略号后同时出现中文逗号和英文逗号，形成重复分隔标点。",
        original_text="…，,",
        correction="… ,".replace(" ", ""),
        anchor_text="3, …，, n",
    ),

    # option structure
    "v2x-option_structure-042": edit(
        "A. O(log n)",
        "1. O(log n)",
        "replace_option_letter_with_numeric_level",
        "option-A-label",
        "numeric-label-among-letter-options",
        "首个选项误用层级数字1作标号，后续仍为B、C、D，选项标号体系断裂。",
        original_text="1.",
        correction="A.",
        anchor_text="1. O(log n)",
    ),
    "v2x-option_structure-043": edit(
        "B. 仅II\nC. 仅I、II",
        "B. 仅II\n仅I、II",
        "remove_option_label_from_body_line",
        "option-B-C-boundary",
        "label-body-line-misalignment",
        "C项正文仍在原行，但其标号缺失，B与D之间的标号序列断裂。",
        original_text="B. 仅II\n仅I、II",
        correction="B. 仅II\nC. 仅I、II",
    ),

    # answer leakage: each carrier is authored separately and exposes the verified answer directly.
    "v2x-answer_leakage-027": edit(
        "操作系统不可能执行的操作是",
        "操作系统不可能执行的操作是（A）",
        "prefill_answer_parentheses",
        "stem-answer-slot",
        "prefilled-parentheses-A",
        "题干作答位置已直接填入正确选项A。",
        original_text="（A）",
        correction="",
        anchor_text="不可能执行的操作是（A）",
    ),
    "v2x-answer_leakage-028": edit(
        "直接为会话层提供服务的是 。",
        "直接为会话层提供服务的是［C］。",
        "prefill_answer_brackets",
        "stem-answer-slot",
        "prefilled-square-brackets-C",
        "题干空位已预填正确选项C。",
        original_text="［C］",
        correction=" ",
        anchor_text="提供服务的是［C］。",
    ),
    "v2x-answer_leakage-029": edit(
        "计算机硬件能够直接执行的是 。",
        "计算机硬件能够直接执行的是【A】。",
        "prefill_answer_box",
        "stem-answer-slot",
        "prefilled-box-A",
        "题干答案框直接给出了正确选项A。",
        original_text="【A】",
        correction=" ",
    ),
    "v2x-answer_leakage-030": edit(
        "C. 10",
        "C. ★10",
        "mark_correct_option_with_star",
        "option-C",
        "star-on-correct-option",
        "星标直接标出了正确选项C。",
        original_text="★",
        correction="",
        anchor_text="C. ★10",
    ),
    "v2x-answer_leakage-031": edit(
        "C. ③→②→④→①",
        "C. ✓③→②→④→①",
        "mark_correct_option_with_check",
        "option-C",
        "check-on-correct-option",
        "对勾直接标出了正确选项C。",
        original_text="✓",
        correction="",
        anchor_text="C. ✓③→②→④→①",
    ),
    "v2x-answer_leakage-032": edit(
        "C. 物理地址",
        "C. 【正确】物理地址",
        "label_correct_option_explicitly",
        "option-C",
        "correct-label-on-option",
        "“正确”标签直接暴露了选项C。",
        original_text="【正确】",
        correction="",
        anchor_text="C. 【正确】物理地址",
    ),
    "v2x-answer_leakage-033": edit(
        "列相同的是 。",
        "列相同的是 。（参考答案：B）",
        "append_answer_letter_note",
        "stem-ending",
        "tail-answer-letter-B",
        "题干末尾直接注明参考答案B。",
        original_text="（参考答案：B）",
        correction="",
    ),
    "v2x-answer_leakage-034": edit(
        "则采用的排序方法可能是 。",
        "则采用的排序方法可能是 。（正确选项为A）",
        "append_correct_choice_note",
        "stem-ending",
        "tail-correct-choice-A",
        "题干尾注明示正确选项A。",
        original_text="（正确选项为A）",
        correction="",
    ),
    "v2x-answer_leakage-035": edit(
        "主要保护措施是 。",
        "主要保护措施是 。（答案字母：A）",
        "append_answer_field",
        "stem-ending",
        "tail-answer-field-A",
        "答案字段直接给出A。",
        original_text="（答案字母：A）",
        correction="",
    ),
    "v2x-answer_leakage-036": edit(
        "网络层提供的是 。",
        "网络层提供的是无连接不可靠的数据报服务，即选择相应选项。",
        "embed_answer_text_in_stem",
        "stem-answer-clause",
        "embedded-answer-service",
        "题干直接写出了选项A的完整答案内容。",
        original_text="无连接不可靠的数据报服务，即选择相应选项",
        correction=" ",
    ),
    "v2x-answer_leakage-037": edit(
        "则根结点的孩子结\n点 。",
        "则根结点的孩子结\n点只有e，即选择对应选项。",
        "embed_answer_text_in_question",
        "stem-answer-clause",
        "embedded-answer-only-e",
        "题干直接给出根结点只有e这一正确结论。",
        original_text="只有e，即选择对应选项",
        correction=" ",
    ),
    "v2x-answer_leakage-038": edit(
        "则该数的值是 。",
        "则该数的值是1.5×2 13，即选择对应选项。",
        "embed_numeric_answer_in_stem",
        "stem-answer-clause",
        "embedded-numeric-answer",
        "题干直接写出选项A的数值答案。",
        original_text="1.5×2 13，即选择对应选项",
        correction=" ",
    ),
    "v2x-answer_leakage-039": edit(
        "下列调度算法中，不可能导致饥饿现象的是 。",
        "已知时间片轮转不可能导致饥饿现象。下列调度算法中，不可能导致饥饿现象的是 。",
        "place_solution_conclusion_before_question",
        "stem-opening",
        "solution-conclusion-round-robin",
        "题干先给出“时间片轮转”这一正确结论，再要求选择。",
        original_text="已知时间片轮转不可能导致饥饿现象。",
        correction="",
        anchor_text="已知时间片轮转不可能导致饥饿现象。下列调度算法中",
    ),
    "v2x-answer_leakage-040": edit(
        "通过POP3 协议接收邮件时，使用的传输层服务类型是 。",
        "通过POP3 协议接收邮件时，已知其使用有连接可靠的数据传输服务，使用的传输层服务类型是 。",
        "place_protocol_conclusion_before_question",
        "stem-middle",
        "solution-conclusion-pop3",
        "题干直接给出选项D的服务类型。",
        original_text="已知其使用有连接可靠的数据传输服务，",
        correction="",
    ),
    "v2x-answer_leakage-041": edit(
        "对10TB 的数据文件进行排序，应使用的方法是 。",
        "对10TB 的数据文件进行排序，已知应采用归并排序，应使用的方法是 。",
        "place_method_conclusion_before_question",
        "stem-middle",
        "solution-conclusion-external-sort",
        "题干在设问前直接给出归并排序这一正确答案。",
        original_text="已知应采用归并排序，",
        correction="",
    ),

    # type mismatch
    "v2x-type_mismatch-047": edit(
        "在支持多线程的系统中， 进程P 创建的若干线程不能共享的是 。",
        "请补全一个用于判断进程P中线程私有资源的函数声明，并写出函数体。",
        "replace_mcq_stem_with_code_completion",
        "stem-task",
        "code-completion-instruction",
        "reference为单项选择题，但题干要求补全函数并编写代码。",
    ),
    "v2x-type_mismatch-048": edit(
        "在OSI 参考模型中，下列功能需由应用层的相邻层实现的是",
        "请补全一个判断OSI应用层相邻层功能的程序接口，并写出返回值类型。",
        "replace_mcq_stem_with_program_interface",
        "stem-task",
        "program-interface-instruction",
        "单选选项仍在，但题干改为程序接口补全任务。",
    ),
    "v2x-type_mismatch-049": edit(
        "对n 个互不相同的符号进行哈夫曼编码。若生成的哈夫曼树共有115 个结点，则n 的值\n是 。",
        "请分步推导含115个结点的哈夫曼树对应的符号数n，并按每个推导步骤给分。",
        "replace_mcq_stem_with_scored_derivation",
        "stem-task",
        "multi-step-scoring-instruction",
        "reference为单项选择题，题干却要求展示分步推导并按步骤评分。",
    ),
    "v2x-type_mismatch-050": edit(
        "若CPU 速度提高50%, I/O 速度不变，则运行基准程序A 所耗费的时间是 。",
        "请证明CPU速度提高50%后的运行时间结论，并给出一个反例说明该结论不成立的情形。",
        "replace_mcq_question_with_proof_and_counterexample",
        "stem-task",
        "proof-counterexample-instruction",
        "单项选择题被改成证明并构造反例的开放任务。",
    ),
    "v2x-type_mismatch-051": edit(
        "处理外部中断时，应该由操作系统保存的是 。",
        "请画出外部中断处理流程图，并在图中标注由操作系统保存的现场信息。",
        "replace_mcq_stem_with_diagram_labeling",
        "stem-task",
        "diagram-labeling-instruction",
        "reference为单选题，题干要求作图并标注。",
    ),
    "v2x-type_mismatch-052": edit(
        "则除H4 外，\n从物理层上能够收到该确认帧的主机还有 。",
        "请对A至D四种接收主机组合逐项判断真伪，并填写四格真假矩阵。",
        "replace_mcq_question_with_truth_matrix",
        "stem-task",
        "truth-matrix-instruction",
        "单选题被改为需要逐项判断的真假矩阵任务。",
    ),
    "v2x-type_mismatch-053": edit(
        "下列关于栈的叙述中，错误的是 。",
        "请把I至IV四条栈的叙述与A至D四组结论一一配伍，并填写配伍表。",
        "replace_mcq_stem_with_matching_table",
        "stem-task",
        "matching-table-statements",
        "题干要求一一配伍并填写表格，与单选作答接口不一致。",
    ),
    "v2x-type_mismatch-054": edit(
        "IEEE 754 单精度浮点格式表示的数中，最小的规格化正数是 。",
        "请将A至D四个浮点数分别与规格化数、非规格化数、零和特殊值配伍，并填写配伍表。",
        "replace_mcq_stem_with_category_matching",
        "stem-task",
        "matching-table-float-categories",
        "原单选题被改成四项分类配伍任务。",
    ),

    # factual / logical errors
    "v2x-factual_logical-003": edit(
        "当前值为1。",
        "当前值为1，且同一时刻该信号量的当前值为-1。",
        "assert_two_simultaneous_signal_values",
        "stem-given-values",
        "contradictory-signal-values",
        "同一信号量在同一时刻被赋予1和-1两个当前值，条件内部直接矛盾。",
        evidence={"constraint_check": "signal.current_value cannot be both 1 and -1 at one instant"},
    ),
    "v2x-factual_logical-004": edit(
        "其中访问Cache\n缺失（未命中）50 次",
        "其中访问Cache\n缺失（未命中）50 次、命中900 次",
        "add_inconsistent_hit_count",
        "stem-access-counts",
        "count-sum-mismatch",
        "1000次访问被写成50次未命中和900次命中，两部分合计仅950次。",
        evidence={"constraint_check": "50 misses + 900 hits = 950, not 1000 accesses"},
    ),
    "v2x-factual_logical-005": edit(
        "这些资源总数分别为18、6、22。",
        "这些资源总数分别为18、6、22，且R2已分配总数为7。",
        "add_allocation_exceeding_total",
        "stem-resource-totals",
        "allocated-exceeds-total",
        "R2总数为6却声明已分配7个，资源总量约束被破坏。",
        evidence={"constraint_check": "allocated R2=7 exceeds total R2=6"},
    ),
    "v2x-factual_logical-006": edit(
        "CPI 增加到原来的1.2 倍",
        "CPI 增加到原来的1.2 倍且保持不变",
        "assert_cpi_changes_and_stays_constant",
        "stem-optimization-condition",
        "change-versus-constant-conflict",
        "CPI被同时规定为增加到1.2倍和保持不变，两项条件不能同时成立。",
        evidence={"constraint_check": "CPI cannot be 1.2x and 1.0x simultaneously"},
    ),
    "v2x-factual_logical-007": edit(
        "帧长为1000 字节",
        "帧长为1000 字节（即1000比特）",
        "add_false_byte_bit_equivalence",
        "stem-frame-length",
        "byte-bit-equivalence-conflict",
        "1字节等于8比特，1000字节应为8000比特，题干把两种容量错误地等同。",
        evidence={"constraint_check": "1000 bytes = 8000 bits, not 1000 bits"},
    ),
    "v2x-factual_logical-008": edit(
        "信噪比为30dB",
        "信噪比为30bps",
        "replace_snr_unit_with_data_rate_unit",
        "stem-channel-condition",
        "snr-data-rate-unit-conflict",
        "信噪比是无量纲比值，通常以dB表示，不能使用数据传输速率单位bps。",
        evidence={"constraint_check": "SNR cannot be measured in bits per second"},
    ),
    "v2x-factual_logical-009": edit(
        "在OSI 参考模型中，RI、Switch、Hub 实现的最高功能层分别是 。",
        "在OSI 参考模型中，已知Switch只实现物理层功能，RI、Switch、Hub 实现的最高功能层分别是 。",
        "assign_switch_to_physical_layer",
        "stem-device-layer-definition",
        "switch-layer-definition-conflict",
        "以太网交换机至少实现数据链路层功能，把它限定为只实现物理层违反设备层级定义。",
        evidence={"constraint_check": "Switch operates at data-link layer, not physical layer only"},
    ),
    "v2x-factual_logical-010": edit(
        "下列TCP/IP 应用层协议中，可以使用传输层无连接服务的是 。",
        "已知DNS只能使用TCP。下列TCP/IP 应用层协议中，可以使用传输层无连接服务的是 。",
        "claim_dns_tcp_only",
        "stem-protocol-behavior",
        "dns-transport-definition-conflict",
        "DNS可使用UDP提供的无连接服务，“只能使用TCP”与协议行为冲突。",
        evidence={"constraint_check": "DNS commonly uses UDP and may also use TCP"},
    ),
    "v2x-factual_logical-011": edit(
        "以太网交换机进行转发决策时使用的PDU 地址是 。",
        "已知以太网交换机按网络层IP地址转发。以太网交换机进行转发决策时使用的PDU 地址是 。",
        "claim_ethernet_switch_uses_ip",
        "stem-forwarding-rule",
        "ethernet-address-layer-conflict",
        "二层以太网交换机依据目的MAC地址转发，题干却断言按网络层IP地址转发。",
        evidence={"constraint_check": "Ethernet switch forwarding table is keyed by MAC address"},
    ),
    "v2x-factual_logical-012": edit(
        "x=x+1;",
        "x=x+0;",
        "set_loop_progress_to_zero",
        "program-loop-update",
        "zero-progress-loop",
        "循环变量x不再增长；当循环条件初次成立时程序无法终止，原复杂度问题的算法不变量被破坏。",
        evidence={"constraint_check": "x remains 0 while condition can remain true"},
    ),
    "v2x-factual_logical-013": edit(
        "若元素a, b, c, d, e, f 依次进栈",
        "若元素a, b, c, d, e, f 依次进入按先进先出规则工作的栈",
        "define_stack_as_fifo",
        "stem-data-structure-definition",
        "stack-fifo-definition-conflict",
        "栈的基本规则是后进先出，题干将同一对象定义为按先进先出工作。",
        evidence={"constraint_check": "stack is LIFO, not FIFO"},
    ),
    "v2x-factual_logical-014": edit(
        "满足短任务优先且不会发生饥饿现象",
        "满足短任务优先且规定等待时间越长响应比越低，并且不会发生饥饿现象",
        "reverse_response_ratio_waiting_property",
        "stem-scheduling-property",
        "response-ratio-monotonicity-conflict",
        "高响应比优先算法中等待时间越长响应比越高，题干把这一关键性质反向表述。",
        evidence={"constraint_check": "response ratio (W+S)/S increases with waiting time W"},
    ),
    "v2x-factual_logical-015": edit(
        "用栈来存放暂时还不能确定运算次序的操作符，若栈初始时为\n空",
        "用容量为0的栈来存放暂时还不能确定运算次序的操作符，若栈初始时为\n空",
        "set_required_stack_capacity_to_zero",
        "stem-stack-capacity",
        "zero-capacity-working-stack",
        "转换过程需要把操作符压栈，但题干把用于该操作的栈容量设为0，数据结构前提不成立。",
        evidence={"constraint_check": "a zero-capacity stack cannot store any pending operator"},
    ),
    "v2x-factual_logical-016": edit(
        "D\n20%\n5",
        "D\n30%\n5",
        "make_instruction_mix_exceed_100_percent",
        "stem-cpi-table",
        "percentage-sum-over-100",
        "四类指令比例变为50%+20%+10%+30%=110%，不可能构成完整指令混合。",
        evidence={"constraint_check": "instruction proportions sum to 110%"},
    ),

    # unified solvability failures
    "v2x-solvability_failure-017": edit(
        "某系统有n 台互斥使用的同类设备",
        "某系统有n 台互斥使用的同类设备，且同一时刻n=8、n=10",
        "assign_two_values_to_device_count",
        "stem-device-count",
        "contradictory-count-values",
        "同一时刻设备总数n被同时指定为8和10，已知条件无法同时成立。",
        evidence={"contradictory_conditions": ["n=8", "n=10"]},
    ),
    "v2x-solvability_failure-018": edit(
        "由3 个“1”和5 个“0”组成的8 位二进制补码",
        "由3 个“1”和5 个“0”组成且总位数为7的8 位二进制补码",
        "contradict_bit_count_and_declared_width",
        "stem-bit-count",
        "seven-versus-eight-bit-conflict",
        "3个1加5个0已是8位，却又声明总位数为7，编码对象不存在。",
        evidence={"contradictory_conditions": ["3+5=8 bits", "total width=7 bits"]},
    ),
    "v2x-solvability_failure-019": edit(
        "有一个100 阶的三对角矩阵M",
        "有一个同时为100 阶和99 阶的三对角矩阵M",
        "assign_two_orders_to_same_matrix",
        "stem-matrix-order",
        "matrix-order-conflict",
        "同一个方阵M被同时定义为100阶和99阶，矩阵规模条件矛盾。",
        evidence={"contradictory_conditions": ["order(M)=100", "order(M)=99"]},
    ),
    "v2x-solvability_failure-044": edit(
        "A. 仅I",
        "A. I和II",
        "make_second_semantically_correct_option",
        "option-A",
        "equivalent-correct-combination-wording",
        "I和II均正确，修改后的A与原正确选项B表达同一正确组合，单选题出现两个有效答案。",
        evidence={"correct_options_after_mutation": ["A", "B"]},
    ),
    "v2x-solvability_failure-045": edit(
        "B. 仅II 和III",
        "B. I、II均正确",
        "make_alternate_correct_option",
        "option-B",
        "equivalent-correct-ram-rom-combination",
        "I和II是正确叙述，修改后的B与原正确选项A均成为有效答案。",
        evidence={"correct_options_after_mutation": ["A", "B"]},
    ),
    "v2x-solvability_failure-046": edit(
        "B. 只有II",
        "B. I正确，II和III错误",
        "state_same_truth_assignment_in_second_option",
        "option-B",
        "equivalent-graph-truth-assignment",
        "无向连通图三条叙述中只有I恒真，修改后的B与A均准确描述同一真假组合。",
        evidence={"correct_options_after_mutation": ["A", "B"]},
    ),

    # language ambiguity
    "v2x-ambiguity-020": edit(
        "簇和磁盘扇区大小分别为1KB 和512B",
        "簇和磁盘扇区之一大小为1KB，另一个为512B",
        "remove_value_to_object_correspondence",
        "stem-storage-units",
        "unlabeled-pair-correspondence",
        "两个数值都给出，但未说明哪个属于簇、哪个属于扇区；两种对应关系会得到不同分配空间。",
        evidence={"interpretations": ["cluster=1KB, sector=512B", "cluster=512B, sector=1KB"]},
    ),
    "v2x-ambiguity-021": edit(
        "从S1中依次弹出两个操作数a 和b",
        "从S1中并非只依次弹出两个操作数a 和b",
        "introduce_negation_scope_ambiguity",
        "step-1",
        "negation-only-order-scope",
        "“并非只依次”既可否定只弹出两个，也可否定依次弹出，操作规则有两种解释。",
        evidence={"interpretations": ["more than two operands are popped", "two operands are popped but not in stated order"]},
    ),
    "v2x-ambiguity-022": edit(
        "外存上有120 个初始归并段，进行12 路归并时",
        "外存上此前有120 个归并段，进行12 路归并时",
        "replace_initial_state_with_unresolved_prior_state",
        "stem-merge-time",
        "unresolved-before-this-reference",
        "“此前有120个”未说明此后是否已完成归并，当前归并段数可能仍为120，也可能已经减少。",
        evidence={"interpretations": ["current run count remains 120", "one or more merges occurred after the count of 120"]},
    ),
    "v2x-ambiguity-023": edit(
        "FTP 客户和服务器间传递FTP 命令时",
        "FTP 客户和服务器分别建立控制连接和数据连接后，在其上传递FTP 命令时",
        "introduce_ambiguous_pronoun_antecedent",
        "stem-ftp-actor",
        "pronoun-client-or-server",
        "“其上”既可回指控制连接，也可回指数据连接，恰好对应不同选项。",
        evidence={"interpretations": ["commands travel on the control connection", "commands travel on the data connection"]},
    ),
    "v2x-ambiguity-024": edit(
        "降低进程优先级的合理时机",
        "进程优先级较低的合理时机",
        "remove_priority_comparison_baseline",
        "stem-comparison",
        "missing-comparison-reference",
        "“较低”没有说明相对于原优先级、其他进程还是某阈值，比较基准不明确。",
        evidence={"interpretations": ["lower than its previous priority", "lower than other ready processes"]},
    ),
    "v2x-ambiguity-025": edit(
        "下面程序片段的时间复杂度",
        "下面程序片段中该量的时间复杂度",
        "insert_cross_object_pronoun",
        "stem-complexity-object",
        "pronoun-n-x-or-program",
        "“该量”既可回指问题规模n，也可指程序中的变量x，所求对象指代不唯一。",
        evidence={"interpretations": ["growth measured against n", "growth attributed to variable x"]},
    ),
    "v2x-ambiguity-026": edit(
        "两者之间可能的不同之处是",
        "两者之间可能都不相同的是",
        "introduce_quantifier_negation_scope",
        "stem-quantifier",
        "possible-all-not-scope",
        "“可能都不相同”既可理解为所有方面均可能不同，也可理解为并非所有方面相同，量词与否定辖域不清。",
        evidence={"interpretations": ["all listed properties may differ", "at least one listed property may differ"]},
    ),
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(re.sub(r"[ \t]+", " ", line.strip()) for line in text.split("\n")).strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def historical_rows() -> list[dict[str, Any]]:
    paths = [
        ROOT / "taxonomy_v2" / "dev_a" / "review_eval_full.jsonl",
        ROOT / "taxonomy_v2" / "dev_b" / "blind_test_full.jsonl",
        ROOT / "taxonomy_v2" / "blind_v2" / "blind_v2_full.jsonl",
    ]
    return [row for path in paths for row in read_jsonl(path)]


def char_grams(text: str, size: int = 5) -> set[str]:
    compact = re.sub(r"\s+", "", normalize(text))
    return {compact[index : index + size] for index in range(max(0, len(compact) - size + 1))}


def main() -> None:
    sources = read_jsonl(RUN_DIR / "source_selection.jsonl")
    if set(MUTATIONS) != {row["sample_id"] for row in sources}:
        missing = sorted({row["sample_id"] for row in sources} - set(MUTATIONS))
        extra = sorted(set(MUTATIONS) - {row["sample_id"] for row in sources})
        raise ValueError(f"Mutation mapping mismatch; missing={missing}, extra={extra}")

    history = historical_rows()
    historical_types: dict[str, set[str]] = {}
    historical_error_texts: set[str] = set()
    history_grams: list[tuple[str, set[str]]] = []
    for row in history:
        source_id = str(row.get("source_record_id") or "")
        if source_id and row.get("error_type") != "none":
            historical_types.setdefault(source_id, set()).add(str(row.get("error_type")))
        if row.get("error_type") != "none":
            text = str(row.get("error_text") or row.get("full_text") or "")
            if text:
                historical_error_texts.add(normalize(text))
                history_grams.append((str(row.get("sample_id")), char_grams(text)))

    manifest: list[dict[str, Any]] = []
    for source in sources:
        sample_id = source["sample_id"]
        mutation = MUTATIONS[sample_id]
        clean = str(source["clean_text"])
        clean_span = mutation["clean_span"]
        if clean.count(clean_span) != 1:
            raise ValueError(f"{sample_id}: clean_span count={clean.count(clean_span)}: {clean_span!r}")
        error = clean.replace(clean_span, mutation["error_span"], 1)
        original = mutation["original_text"]
        correction = mutation["correction"]
        anchor = mutation["anchor_text"]
        if not original or error.count(original) != 1:
            raise ValueError(f"{sample_id}: original_text must occur exactly once")
        if error.count(anchor) != 1:
            raise ValueError(f"{sample_id}: anchor_text count={error.count(anchor)}")
        if error.replace(original, correction, 1) != clean:
            raise ValueError(f"{sample_id}: round trip failed")
        target = str(source["planned_error_type"])
        if target in historical_types.get(str(source["source_record_id"]), set()):
            raise ValueError(f"{sample_id}: same source and historical error type")
        if normalize(error) in historical_error_texts:
            raise ValueError(f"{sample_id}: normalized error text duplicates history")
        manifest.append(
            {
                "sample_id": sample_id,
                "source_fingerprint_sha256": source["source_fingerprint_sha256"],
                "source_origin": "existing_dataset",
                "source_dataset": source["source_origin"],
                "source_record_id": source["source_record_id"],
                "source_subject": source["source_subject"],
                "source_year": source["source_year"],
                "source_answer": source["source_answer"],
                "source_answer_original": source.get("source_answer_original", ""),
                "clean_text": clean,
                "error_text": error,
                "error_type": target,
                "error_detailed_type": source["planned_subtype"],
                "solvability_subtype": source["planned_subtype"] if target == "solvability_failure" else "",
                "original_text": original,
                "correction": correction,
                "anchor_text": anchor,
                "mutation_operation": mutation["operation"],
                "mutation_location": mutation["location"],
                "mutation_token_class": mutation["token_class"],
                "mutation_signature": "|".join(
                    [source["planned_subtype"], mutation["operation"], mutation["location"], mutation["token_class"]]
                ),
                "rationale": mutation["rationale"],
                "validation": {
                    "root_error_count": 1,
                    "round_trip_passed": True,
                    "anchor_unique": True,
                    "same_source_same_type_passed": True,
                    "historical_full_text_duplicate": False,
                    **mutation["evidence"],
                },
                "phase2_status": "accepted",
            }
        )

    normalized = [normalize(row["error_text"]) for row in manifest]
    if len(normalized) != len(set(normalized)):
        raise ValueError("Batch contains duplicate normalized error texts")

    near_history: list[dict[str, Any]] = []
    near_batch: list[dict[str, Any]] = []
    for row in manifest:
        grams = char_grams(row["error_text"])
        best_id, best_score = "", 0.0
        for historical_id, other in history_grams:
            union = grams | other
            score = len(grams & other) / len(union) if union else 1.0
            if score > best_score:
                best_id, best_score = historical_id, score
        if best_score >= 0.85:
            near_history.append(
                {"sample_id": row["sample_id"], "historical_sample_id": best_id, "jaccard_5gram": round(best_score, 6)}
            )
    for index, row in enumerate(manifest):
        left = char_grams(row["error_text"])
        for other_row in manifest[index + 1 :]:
            right = char_grams(other_row["error_text"])
            union = left | right
            score = len(left & right) / len(union) if union else 1.0
            if score >= 0.85:
                near_batch.append(
                    {"left": row["sample_id"], "right": other_row["sample_id"], "jaccard_5gram": round(score, 6)}
                )

    write_jsonl(RUN_DIR / "mutation_manifest.jsonl", manifest)
    write_jsonl(
        RUN_DIR / "phase2_questions.jsonl",
        [
            {
                "sample_id": row["sample_id"],
                "error_type": row["error_type"],
                "error_detailed_type": row["error_detailed_type"],
                "reference": f"【学科】{row['source_subject']}\n【题型或其它信息】单项选择题",
                "detection_content": row["error_text"],
            }
            for row in manifest
        ],
    )
    signature_counts = Counter(row["mutation_signature"] for row in manifest)
    location_counts = Counter(row["mutation_location"] for row in manifest)
    max_signature_count = max(signature_counts.values(), default=0)
    max_location_count = max(location_counts.values(), default=0)
    summary = {
        "requested": len(sources),
        "constructed": len(manifest),
        "skipped": 0,
        "replaced_sources": 1,
        "by_error_type": dict(Counter(row["error_type"] for row in manifest)),
        "by_subtype": dict(Counter(row["error_detailed_type"] for row in manifest)),
        "by_source_dataset": dict(Counter(row["source_dataset"] for row in manifest)),
        "mutation_signatures": {
            "unique": len(signature_counts),
            "max_count": max_signature_count,
            "max_rate": round(max_signature_count / len(manifest), 6) if manifest else 0.0,
        },
        "mutation_locations": {
            "counts": dict(location_counts),
            "max_count": max_location_count,
            "max_rate": round(max_location_count / len(manifest), 6) if manifest else 0.0,
        },
        "round_trip_passed": sum(bool(row["validation"]["round_trip_passed"]) for row in manifest),
        "anchor_unique": sum(bool(row["validation"]["anchor_unique"]) for row in manifest),
        "single_root_error": sum(row["validation"]["root_error_count"] == 1 for row in manifest),
        "historical_exact_duplicates": 0,
        "batch_exact_duplicates": 0,
        "near_history_at_0_85": near_history,
        "near_batch_at_0_85": near_batch,
        "source_answer_corrections": sum(
            str(row["source_answer"]) != str(row.get("source_answer_original") or row["source_answer"])
            for row in manifest
        ),
    }
    (RUN_DIR / "phase2_validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
