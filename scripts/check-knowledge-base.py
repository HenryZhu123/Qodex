"""Read-only verification of a supplied KB release and real retrieval, no model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from exam_checker.integrations.knowledge_base import KnowledgeBaseRetriever


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    total = 0
    for entry in manifest["files"]:
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Manifest path leaves knowledge base directory")
        data = path.read_bytes()
        assert len(data) == entry["bytes"], f"Size mismatch: {entry['path']}"
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], f"Hash mismatch: {entry['path']}"
        if "chunks" in entry:
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
                assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
                assert count == entry["chunks"]
                total += count
    assert total == manifest["total_chunks"]
    retriever = KnowledgeBaseRetriever(root / "books")
    assert retriever.is_available()
    results = []
    for subject, query in [
        ("data_structure", "线性表 顺序存储 插入 删除"),
        ("computer_organization", "高速缓存 主存 地址 映射"),
        ("operating_system", "进程 调度 时间片"),
        ("computer_network", "TCP 拥塞窗口 ssthresh"),
    ]:
        items, latency = retriever.search(subject, query, top_k=2)
        assert items, f"No retrieval result: {subject}"
        results.append({"subject": subject, "hits": len(items), "chunk_ids": [item.chunk_id for item in items], "latency_ms": round(latency, 1)})
    print(json.dumps({"verified_files": len(manifest["files"]), "total_chunks": total, "retrieval": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
