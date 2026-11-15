"""408 scope navigation, deliberately independent of generators and solvers.

Chapter-level navigation is not a claim of leaf-level syllabus or quality coverage.
Source: HEP outline commentary, ISBN 9787040657791 (2025-10).
The complete 2027 official outline has not been verified.
"""
from __future__ import annotations

from .generation import RequestError

SOURCE = "https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=68b8764ae119ac9729e8a8bc"
AREAS = {
    "data_structures": {
        "ds.foundations": "基本概念与算法分析", "ds.linear": "线性表",
        "ds.stack_queue_array": "栈、队列与数组", "ds.trees": "树与二叉树",
        "ds.graphs": "图", "ds.search": "查找与字符串匹配", "ds.sort": "排序",
    },
    "computer_organization": {
        "co.system": "计算机系统与性能", "co.representation": "数据表示与运算",
        "co.memory": "存储系统", "co.instructions": "指令系统",
        "co.cpu": "CPU、流水线与多处理器", "co.io": "总线与输入输出",
    },
    "operating_systems": {
        "os.foundations": "操作系统基础", "os.process": "进程、调度、同步与死锁",
        "os.memory": "内存与虚拟内存", "os.files": "文件系统", "os.io": "输入输出管理",
    },
    "computer_networks": {
        "cn.architecture": "网络体系结构", "cn.physical": "物理层",
        "cn.link": "数据链路层", "cn.network": "网络层",
        "cn.transport": "传输层", "cn.application": "应用层",
    },
}


def read_scope(subject, areas):
    if not isinstance(subject, str) or subject not in AREAS:
        raise RequestError("通用创作限于408四门科目。", "UNSUPPORTED_REQUEST")
    all_areas = {key: label for group in AREAS.values() for key, label in group.items()}
    if (not isinstance(areas, list) or not 1 <= len(areas) <= 4
            or any(not isinstance(a, str) or a not in all_areas for a in areas)
            or len(set(areas)) != len(areas) or not any(a in AREAS[subject] for a in areas)):
        raise RequestError("syllabus_areas 须为1至4个不重复的章节ID，至少一个属于主科目。")
    return [{"id": a, "label": all_areas[a]} for a in areas]


def coverage_report(material_topics=(), evaluated_topics=()):
    """Report supplied evidence, never turn a chapter listing into tested coverage.

Inputs are explicit (subject, topic, area) triples from a verified inventory or
evaluation, not guessed from labels. A tested topic does not certify its chapter.
"""
    rows = []
    for subject, group in AREAS.items():
        for area, label in group.items():
            rows.append({"subject": subject, "area": area, "label": label,
                         "material_topics": sorted({t for s, t, a in material_topics if s == subject and a == area}),
                         "evaluated_topics": sorted({t for s, t, a in evaluated_topics if s == subject and a == area}),
                         "authoring_contract": ["single_choice", "comprehensive"],
                         "chapter_quality_verified": False})
    return {"source": SOURCE, "granularity": "chapter_navigation",
            "latest_official_outline_verified": False, "areas": rows}
