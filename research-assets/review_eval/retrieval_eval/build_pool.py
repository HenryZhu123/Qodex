#!/usr/bin/env python3
"""Build the retrieval evaluation set: queries, negatives and a pooled candidate list.

Pool = BM25 top-10 per query. If a dense retriever is added later, its top-10 must
be merged into the same pool before labelling, otherwise its true hits never get
labelled and it is scored unfairly.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r"D:\Code\hku\LLM\hku_agent")
sys.path.insert(0, str(ROOT / "pi-coding-agent/services/exam-checker/src"))

from exam_checker.integrations.knowledge_base import KnowledgeBaseRetriever  # noqa: E402

KB_ROOT = Path(r"D:\Code\hku\LLM\kb_review\books")
OUT = ROOT / "research-assets/review_eval/retrieval_eval"
DEV_A_RESULTS = ROOT / "research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031/full_v2/rescored/results.jsonl"

SUBJECTS = ("operating_system", "computer_organization", "data_structure", "computer_network")
PREFIX = {"operating_system": "os", "computer_organization": "co",
          "data_structure": "ds", "computer_network": "cn"}

# Topics a reviewer plausibly asks about but the four 408 textbooks do not cover.
NEGATIVES = [
    ("operating_system", "iOS jetsam 内存压缩与进程终止顺序"),
    ("operating_system", "Kubernetes cgroup v2 的 cpu.max 配额换算"),
    ("operating_system", "Linux io_uring 提交队列与完成队列的环形结构"),
    ("operating_system", "macOS XNU 混合内核的 Mach 端口权限"),
    ("operating_system", "Windows 内核 APC 注入的调度时机"),
    ("computer_organization", "RISC-V 向量扩展 vsetvl 指令编码"),
    ("computer_organization", "Apple M 系列统一内存的缓存一致性协议"),
    ("computer_organization", "PCIe 5.0 FLIT 编码与 CRC 重传"),
    ("computer_organization", "ARM SVE 可伸缩向量长度寄存器"),
    ("computer_organization", "HBM3 伪通道 bank group 时序参数"),
    ("data_structure", "跳表的无锁并发插入与 ABA 问题"),
    ("data_structure", "Rust BTreeMap 的节点分裂阈值"),
    ("data_structure", "持久化线段树的可持久化版本号回收"),
    ("data_structure", "Merkle Patricia Trie 的路径压缩规则"),
    ("data_structure", "布谷鸟过滤器的踢出循环上限"),
    ("computer_network", "HTTP/3 QUIC 连接迁移的路径验证"),
    ("computer_network", "eBPF XDP 在网卡驱动的挂载点"),
    ("computer_network", "WireGuard 的 Noise 握手密钥轮换"),
    ("computer_network", "SRv6 段路由的 End.DX2 行为"),
    ("computer_network", "TCP BBRv3 的带宽探测周期"),
]


def load_queries(limit_per_subject: int, seed: int) -> list[dict]:
    by_subject: dict[str, list[str]] = collections.defaultdict(list)
    for line in DEV_A_RESULTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        for check in record.get("checks", []):
            for raw in check.get("kb_queries") or []:
                raw = raw.strip()
                if not raw.startswith("["):
                    continue
                subject, _, text = raw[1:].partition("]")
                subject = subject.strip()
                text = text.strip()
                if subject in SUBJECTS and len(text) >= 8:
                    by_subject[subject].append(text)

    rng = random.Random(seed)
    rows: list[dict] = []
    for subject in SUBJECTS:
        pool = sorted(set(by_subject[subject]))
        picked = rng.sample(pool, min(limit_per_subject, len(pool)))
        for i, text in enumerate(sorted(picked), start=1):
            rows.append({"qid": f"{PREFIX[subject]}-{i:02d}", "query": text,
                         "subject": subject, "source": "dev_a_logic_check",
                         "negative": False})
    for i, (subject, text) in enumerate(NEGATIVES, start=1):
        rows.append({"qid": f"neg-{i:02d}", "query": text, "subject": subject,
                     "source": "synthetic_out_of_scope", "negative": True})
    return rows


def build_pool(rows: list[dict], top_k: int) -> tuple[list[dict], dict]:
    pool: list[dict] = []
    stats = {}
    for row in rows:
        db = KB_ROOT / row["subject"] / "kb.sqlite"
        match = KnowledgeBaseRetriever._build_fts_query(row["query"])
        hits: list[tuple] = []
        if db.is_file() and match:
            conn = sqlite3.connect(db)
            try:
                hits = conn.execute(
                    """
                    SELECT c.chunk_id, c.heading_path, c.page_start, c.content,
                           bm25(chunks_fts) AS score
                    FROM chunks_fts f JOIN chunks c ON c.chunk_id = f.chunk_id
                    WHERE chunks_fts MATCH ?
                    ORDER BY score ASC
                    LIMIT ?
                    """,
                    (match, top_k),
                ).fetchall()
            except sqlite3.Error:
                hits = []
            finally:
                conn.close()
        stats[row["qid"]] = len(hits)
        for rank, (chunk_id, heading, page, content, score) in enumerate(hits, start=1):
            pool.append({
                "qid": row["qid"], "chunk_id": chunk_id, "book": row["subject"],
                "rank_bm25": rank, "bm25": round(float(score), 4),
                "heading_path": heading or "", "page_start": page,
                "snippet": (content or "")[:160].replace("\n", " "),
            })
    return pool, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-subject", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    rows = load_queries(args.per_subject, args.seed)
    pool, stats = build_pool(rows, args.top_k)

    with (OUT / "queries.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (OUT / "pool.jsonl").open("w", encoding="utf-8") as handle:
        for item in pool:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    zero = [qid for qid, n in stats.items() if n == 0]
    print(json.dumps({
        "queries": len(rows),
        "positive": sum(1 for r in rows if not r["negative"]),
        "negative": sum(1 for r in rows if r["negative"]),
        "pool_items": len(pool),
        "unique_chunks": len({p["chunk_id"] for p in pool}),
        "queries_with_zero_hits": len(zero),
        "zero_hit_qids": zero,
        "avg_hits_per_query": round(sum(stats.values()) / len(stats), 1),
        "hits_on_negatives": sum(stats[r["qid"]] for r in rows if r["negative"]),
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
