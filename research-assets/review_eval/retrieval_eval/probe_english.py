import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Code\hku\LLM\hku_agent\research-assets\skills\build-knowledge-base\scripts")
from store import init_db, query_fts  # noqa: E402

DB = Path(r"D:\Code\hku\LLM\kb_review\books\computer_network\kb.sqlite")
PROBES = [
    ("James F. Kurose", "作者英文名（OCR 里写作 JamesF.Kurose）"),
    ("Keith W. Ross", "第二作者"),
    ("TCP/IP 协议", "原文写作 TCP/IP，查询写作 TCP / IP 也应命中"),
]

conn = init_db(DB)
results = []
for query, note in PROBES:
    hits = query_fts(conn, query, top_k=2)
    top = hits[0] if hits else None
    results.append({
        "query": query,
        "note": note,
        "hits": len(hits),
        "top_chunk": top["chunk_id"] if top else None,
        "top_heading": top["heading_path"] if top else None,
        "snippet": (top["content"][:80] if top else ""),
    })
conn.close()

out = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\retrieval_eval\english_probes.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
for row in results:
    print(f"{row['query']:20s} hits={row['hits']} top={row['top_chunk']} {row['snippet'][:50]}")
