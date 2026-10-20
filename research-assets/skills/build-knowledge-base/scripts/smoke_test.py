#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained smoke test for the build-knowledge-base skill."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunker import choose_chunk_plan, chunk_document  # noqa: E402
from integrity import check_integrity, sample_contiguous  # noqa: E402
from parsers import parse_document  # noqa: E402
from store import get_stats, init_db, insert_chunks, insert_document, query_fts  # noqa: E402

SAMPLE = """第1章 操作系统引论

1.1 操作系统的目标和作用

操作系统（operating system，OS）是配置在计算机硬件上的第一层软件，是对硬件系统的首次扩充。其主要作用是管理硬件设备，提高它们的利用率和系统吞吐量，并为用户和应用程序提供一个简单的接口。

1.1.1 操作系统的目标

在计算机系统上配置OS，其主要目标是实现：方便性、有效性、可扩充性、开放性。

第2章 进程管理

2.1 进程的基本概念

进程是程序在一个数据集合上运行的过程，它是系统进行资源分配和调度的一个独立单位。

例题：下列关于进程的说法正确的是（ ）。
A. 进程是程序的一次执行
B. 进程是静态的
C. 进程不需要资源
D. 进程与程序完全相同

答案：A
解析：进程是程序的一次执行过程，具有动态性。
"""


def main() -> int:
    tmp_path = Path.cwd() / ".kb_smoke_tmp"
    shutil.rmtree(tmp_path, ignore_errors=True)
    tmp_path.mkdir(parents=True, exist_ok=True)
    try:
        source = tmp_path / "sample.txt"
        source.write_text(SAMPLE, encoding="utf-8")

        parsed = parse_document(source)
        assert len(parsed.text) > 100, "parse produced too little text"
        assert len(parsed.units) > 10, "expected line units"

        sample = sample_contiguous(parsed.units, parsed.unit_type, ratio=0.1, min_units=5)
        assert sample["sample_units"] >= 5, "minimum sample not honored"

        report = check_integrity(sample, parsed.to_dict())
        assert report["verdict"] in {"pass", "warn"}, f"unexpected verdict: {report['verdict']}"

        plan = choose_chunk_plan(report, parsed.to_dict())
        assert plan["mode"] in {"hierarchical", "paragraph", "question", "code"}, plan["mode"]
        assert not plan["blocked"], "unexpected blocked plan"

        chunks = chunk_document(parsed.to_dict(), plan)
        assert chunks, "no chunks produced"
        assert all(c["chunk_id"] for c in chunks), "missing chunk id"
        assert all(c["char_count"] > 0 for c in chunks), "empty chunk"

        db_path = tmp_path / "kb.sqlite"
        conn = init_db(db_path)
        insert_document(conn, parsed.to_dict())
        insert_chunks(conn, chunks)
        stats = get_stats(conn)
        assert stats["documents"] == 1, stats
        assert stats["chunks"] == len(chunks), stats

        hits = query_fts(conn, "操作系统的目标", top_k=3)
        conn.close()
        assert hits, "expected at least one search hit"

        print("SMOKE TEST PASSED")
        print(f"  parsed chars: {len(parsed.text)}")
        print(f"  chunks: {len(chunks)}")
        print(f"  verdict: {report['verdict']}")
        print(f"  mode: {plan['mode']}")
        print(f"  top hit: {hits[0]['chunk_id']} score={hits[0]['score']:.4f}")
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
