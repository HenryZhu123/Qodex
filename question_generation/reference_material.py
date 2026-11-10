"""Original explanatory notes for documented gaps in the textbook indexes."""
from __future__ import annotations

from hashlib import sha256
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
)


def reference_evidence(areas, query):
    query = normalize("NFKC", query).casefold()
    for area, terms, source, anchor, summary in NOTES:
        if area in areas and any(term in query for term in terms):
            digest = sha256(summary.encode()).hexdigest()
            yield {"id": "reference:" + digest, "source": source, "anchor": anchor,
                   "summary": summary, "version": "Qodex explanatory note · sha256:" + digest,
                   "rules": []}
