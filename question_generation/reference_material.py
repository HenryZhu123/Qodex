"""Original explanatory notes for documented gaps in the textbook indexes."""
from __future__ import annotations

from hashlib import sha256
import re
from unicodedata import normalize

# Text is project-authored. URLs identify the underlying course or textbook,
# and are deliberately distinct from the citation of a verbatim book excerpt.
NOTES = (
    ("cn.physical", ("奈奎斯特", "奈氏准则", "nyquist", "香农", "shannon", "信道容量", "信噪比"),
     "https://www.cs.unm.edu/~maccabe/classes/585/FALL02/chap02.pdf",
     "University of New Mexico, The Physical Layer, Maximum Data Rate of a Channel, slide 13",
     "理想无噪声低通信道的带宽为 B Hz 时，奈奎斯特上限是每秒 2B 个码元。"
     "若有 M 种可区分码元，每码元携带 log2(M) 比特，码元数和电平数给出的比特率上界为 2B log2(M) bit/s。"
     "这一上界不能保证在有噪声时仍可区分全部电平。"),
    ("cn.physical", ("香农", "shannon", "信道容量", "信噪比", "奈奎斯特", "nyquist"),
     "https://ocw.mit.edu/courses/res-6-004-principles-of-computer-system-design-an-introduction-spring-2009/46bd7ae60f3adfbdcfaca03df7892c24_networks_open_5_0.pdf",
     "MIT OpenCourseWare, Principles of Computer System Design, Ch. 7, Sidebar 7.4",
     "带宽 B Hz、加性白高斯噪声下的容量为 B log2(1 + S/N) bit/s，其中 S/N 是信号与噪声的功率比。"
     "若给的是 dB 值 D，先换算 S/N = 10^(D/10)。容量是可可靠传输速率的理论上界，增加电平数不能抬高固定带宽和信噪比下的容量。"
     "若题目同时明确给定理想码元速率与码元集约束，任何可行速率都须服从这两类上界；取较小者仍只是上界。"),
    ("cn.link", ("csma/cd", "csma-cd", "争用期", "碰撞检测", "最短帧"),
     "https://intronetworks.cs.luc.edu/current2/ComputerNetworks/ethernet1.html",
     "Peter L. Dordal, An Introduction to Computer Networks 2.0.11, 2.1.5, Fig. 10",
     "在共享半双工 CSMA/CD 链路上，最晚情形是远端在本端信号到达前一瞬开始发送，"
     "该远端信号再走一次单程传播路径才到本端。因此若最大单程传播时延为 τ，最晚检测时刻的上界为 2τ。"
     "在忽略中继处理、检测等额外延时的题设下，为保证发送期间能察觉最迟冲突，"
     "最短帧的发送时间 L/R 须覆盖 2τ，其中 L 是比特数，R 是 bit/s。"
     "若要求帧长为整字节，须向上取整。实际标准的时隙预算还涉及设备，不能把简化式当成完整合规判定。"),
    ("ds.linear", ("尾指针", "删除尾结点", "删除尾节点"),
     "https://opendsa-server.cs.vt.edu/ODSA/Books/eu/cs330/spring-2025/Excelsior2/html/ListAnalysis.html",
     "OpenDSA, 3.6.2 Time Comparison",
     "在普通单链表中，每个结点只保存后继链接。尾指针能直接定位当前尾结点，但删除它还需要找到前驱，"
     "将前驱的后继置空并让尾指针指向前驱。仅有头指针与尾指针时，两个以上结点通常要从头找前驱，"
     "最坏为线性时间。若已持有有效前驱指针，重连和更新尾指针只需常数时间。无哨兵的单元素表删空后头、尾均为空。"),
    ("ds.stack_queue_array", ("稀疏矩阵", "三元组"),
     "https://math.nist.gov/MatrixMarket/formats.html",
     "NIST Matrix Market File Formats, Coordinate Format",
     "一般稀疏矩阵可用行数、列数和非零项数记录规模，再以（行号，列号，值）三元组记录每个非零元素。"
     "若每个坐标至多有一条记录，未出现的坐标表示零。转置会交换矩阵行列数，并将每个三元组的行号和列号交换，值不变。"
     "若接口要求输出按行号、列号排序，还要按交换后的坐标重排，原三元组顺序未必仍然有效。"),
    ("co.system", ("阿姆达尔", "阿姆达尔定律", "amdahl"),
     "https://pages.cs.wisc.edu/~markhill/cs354/Fall2008/notes/performance.html",
     "University of Wisconsin–Madison, CS 354, Performance features, Amdahl's Law",
     "Amdahl 定律适用于固定工作量和明确的原始时间分解。若占原执行时间比例 f 的部分加速到原来的 s 倍，"
     "其余耗时与额外开销不变，新总耗时与旧总耗时的比为 1−f+f/s，总加速比是该比值的倒数。"
     "若 0≤f<1，即使 s 趋于无穷，总加速比也至多为 1/(1−f)。f 必须按改造前的执行时间计算。"),
    ("os.io", ("磁盘调度", "look", "扫描算法"),
     "https://codex.cs.yale.edu/avi/os-book/OS8/os8e/slide-dir/PDF-dir/ch11.pdf",
     "Silberschatz, Galvin & Gagne, Operating System Concepts Essentials, Ch. 11, SCAN and C-LOOK",
     "在给定初始磁头位置、移动方向和静态请求集合时，扫描调度（SCAN）沿当前方向服务请求，并在物理端点掉头。"
     "LOOK 只走到当前方向最后一个待处理请求，在需要掉头服务另一侧时不再额外走到物理端点。"
     "因此访问顺序相同也可能有不同的总移动量。比较前应说明磁道上下界、统计是否在服务完最后一条请求时结束，以及有无新到请求。"),
    ("cn.physical", ("曼彻斯特", "manchester", "自同步编码"),
     "https://cseweb.ucsd.edu/classes/sp16/cse123-a/lectures/123-sp16-l4.pdf",
     "UC San Diego CSE 123, Lecture 4 Layers & Framing, Manchester Encoding",
     "曼彻斯特编码把每个数据位分为两个等长半位，两半电平相反。位中点必有跳变，可供接收端恢复位时钟并维持同步。"
     "跳变方向对应 0 或 1，题面要声明约定。相邻位的边界也可能跳变，不能把每个跳变都当作新数据位。"
     "若线路预算按每秒可承载的等长半位数给出，一个数据位需要两个半位。帧起点或位相位的识别仍需明确条件。"),
)


def reference_evidence(areas, query, *, related=False):
    query = normalize("NFKC", query).casefold()
    direct, nearby = [], []
    pairs = {m[1] for m in re.finditer(r"(?=([\u4e00-\u9fff]{2}))", query)} if related else set()
    for area, terms, source, anchor, summary in NOTES:
        if area not in areas:
            continue
        overlap = sum(pair in summary for pair in pairs)
        if any(term in query for term in terms):
            direct.append((overlap, source, anchor, summary))
        elif overlap >= 3:
            # Search the note itself, so exact tag vocabulary is not required.
            # Keep at most one extra note in the initial brief shortlist.
            nearby.append((overlap, source, anchor, summary))
    for _, source, anchor, summary in sorted(direct, key=lambda item: -item[0]):
        yield _evidence(source, anchor, summary)
    if nearby:
        _, source, anchor, summary = max(nearby)
        yield _evidence(source, anchor, summary)


def _evidence(source, anchor, summary):
    digest = sha256(summary.encode()).hexdigest()
    return {"id": "reference:" + digest, "source": source, "anchor": anchor,
            "summary": summary, "version": "Qodex explanatory note · sha256:" + digest,
            "rules": []}


def restore_reference(areas, reference):
    for area, _, source, anchor, summary in NOTES:
        if area in areas and source == reference["source"] and anchor == reference["anchor"]:
            item = _evidence(source, anchor, summary)
            if item["id"] == reference["id"]:
                return item
    return None
