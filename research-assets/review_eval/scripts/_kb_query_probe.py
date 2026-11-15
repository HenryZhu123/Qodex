"""Ad-hoc retrieval quality probe against the local knowledge base."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src")
sys.path.insert(0, str(SRC))

from exam_checker.integrations.knowledge_base import KnowledgeBaseRetriever  # noqa: E402

QUERIES = [
    ("computer_network", "TCP 三次握手 为什么需要"),
    ("computer_network", "子网掩码 路由聚合"),
    ("operating_system", "缺页中断 页面置换算法"),
    ("operating_system", "进程同步 信号量 P操作 V操作"),
    ("computer_organization", "IEEE754 单精度 浮点数 表示范围"),
    ("computer_organization", "Cache 映射方式 直接映射"),
    ("data_structure", "平衡二叉树 插入 旋转"),
    ("data_structure", "快速排序 时间复杂度 最坏"),
]


def main() -> None:
    kb = KnowledgeBaseRetriever()
    print(f"kb_available={kb.is_available()}")
    for subject, query in QUERIES:
        items, latency = kb.search(subject, query, top_k=2)
        print(f"\n=== [{subject}] {query}  ({latency:.0f} ms, hits={len(items)})")
        for item in items:
            snippet = item.content.replace("\n", " ")[:110]
            print(f"  score={item.score:.2f} p.{item.page_start} head={item.heading_path or '(无)'}")
            print(f"    {snippet}")


if __name__ == "__main__":
    main()
