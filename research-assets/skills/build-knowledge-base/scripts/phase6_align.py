#!/usr/bin/env python3
"""Phase 6: multi-source alignment between the 8th and 7th edition (计网).

Steps:
  1. chunk the freshly parsed 8th edition (markdown blocks merged to ~700 chars)
  2. generate candidates against the ingested 7th edition by character-trigram
     containment (cast wide, this stage may over-produce)
  3. judge every candidate pair into equivalent / exclusive / conflict /
     complementary with an LLM, conflicts first
  4. write delta/<doc_id>.jsonl and a relation report

The existing kb.sqlite is never modified: the delta file keeps the merge
reversible.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import httpx

SCRIPTS = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\skills\build-knowledge-base\scripts")
sys.path.insert(0, str(SCRIPTS))

from kb_registry import normalize_text, trigrams  # noqa: E402

EIGHTH_PARSED = Path(r"D:\Code\hku\LLM\kb_review\books\computer_network_8th\parsed\bf0b7038334a1485.json")
SEVENTH_DB = Path(r"D:\Code\hku\LLM\kb_review\books\computer_network\kb.sqlite")
OUT_DIR = Path(r"D:\Code\hku\LLM\kb_review\books\computer_network_8th\delta")
ENV_FILE = Path(r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\.env.local")

SYSTEM = "你是考研计算机(408)教材知识对齐专家。只输出 JSON。"

PROMPT = """判断【来源B】的一段内容与【来源A】的一段内容之间是哪种关系。

【来源A：教材第7版】
{a}

【来源B：教材第8版】
{b}

关系只能选以下之一，判定顺序必须是先冲突、再等价、最后独有/互补：
- "conflict"：指向同一问题或同一对象，但给出互不相容的结论（数值、公式、判定规则相反）。详略不同不算冲突。
- "equivalent"：表述相同或语义等价，讲的是同一个事实/结论。
- "complementary"：不重复但相关（一个讲一般情形、一个讲例外；一个讲流程、一个讲证明）。
- "exclusive"：两者讲的是不同知识点，没有实质对应关系。

只输出 JSON：
{{"relation":"conflict|equivalent|complementary|exclusive","reason":"不超过50字","stance_a":"若为冲突，A的主张","stance_b":"若为冲突，B的主张"}}"""


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name, value = stripped.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def chunk_eighth(target: int = 700, hard_max: int = 1200) -> list[dict]:
    data = json.loads(EIGHTH_PARSED.read_text(encoding="utf-8"))
    units = [u for u in data["units"] if u.get("text", "").strip()]
    chunks: list[dict] = []
    buffer: list[str] = []
    size = 0
    first = None
    for unit in units:
        text = unit["text"].strip()
        if first is None:
            first = unit
        if size + len(text) > hard_max and buffer:
            chunks.append({"text": "\n".join(buffer), "page": first.get("page", 0)})
            buffer, size, first = [], 0, unit
        buffer.append(text)
        size += len(text)
        if size >= target and text.endswith(("。", "！", "？", "：", ")", "）")):
            chunks.append({"text": "\n".join(buffer), "page": first.get("page", 0)})
            buffer, size, first = [], 0, None
    if buffer:
        chunks.append({"text": "\n".join(buffer), "page": first.get("page", 0) if first else 0})
    for index, chunk in enumerate(chunks, start=1):
        chunk["chunk_id"] = f"cn8th:{index:04d}"
        chunk["trigrams"] = trigrams(chunk["text"])
    return chunks


def load_seventh() -> list[dict]:
    conn = sqlite3.connect(f"file:{SEVENTH_DB.as_posix()}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT chunk_id, content, heading_path, page_start FROM chunks"
    ).fetchall()
    conn.close()
    return [
        {
            "chunk_id": chunk_id,
            "text": content,
            "heading": heading or "",
            "page": page_start,
            "trigrams": trigrams(content),
        }
        for chunk_id, content, heading, page_start in rows
    ]


def candidates_for(chunk: dict, seventh: list[dict], index: dict[str, list[int]], top_k: int, floor: float) -> list[dict]:
    votes: Counter[int] = Counter()
    grams = chunk["trigrams"]
    if not grams:
        return []
    for gram in grams:
        for position in index.get(gram, ()):
            votes[position] += 1
    scored = []
    for position, hits in votes.most_common(30):
        other = seventh[position]
        smaller = min(len(grams), len(other["trigrams"]))
        if smaller and hits / smaller >= floor:
            scored.append((hits / smaller, other))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [{"score": round(score, 3), **other} for score, other in scored[:top_k]]


def parse_json(text: str) -> dict | None:
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


async def judge(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    base: str,
    key: str,
    model: str,
    left: str,
    right: str,
) -> dict | None:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": PROMPT.format(a=left[:1500], b=right[:1500])},
        ],
        "temperature": 0,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }
    async with semaphore:
        for attempt in range(1, 4):
            try:
                response = await client.post(
                    f"{base.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                )
                if response.status_code == 400 and "response_format" in body:
                    body.pop("response_format")
                    continue
                if response.status_code != 200:
                    await asyncio.sleep(attempt * 2)
                    continue
                parsed = parse_json(response.json()["choices"][0]["message"].get("content") or "")
                if parsed and parsed.get("relation") in {
                    "conflict",
                    "equivalent",
                    "complementary",
                    "exclusive",
                }:
                    return parsed
                await asyncio.sleep(attempt * 2)
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                await asyncio.sleep(attempt * 2)
    return None


async def run(args: argparse.Namespace) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = load_env()
    base = env["EXAM_CHECKER_REVIEW_LLM_BASE_URL"]
    key = env["EXAM_CHECKER_REVIEW_LLM_API_KEY"]

    eighth = chunk_eighth()
    seventh = load_seventh()
    index: dict[str, list[int]] = {}
    for position, other in enumerate(seventh):
        for gram in other["trigrams"]:
            postings = index.setdefault(gram, [])
            if len(postings) < 80:
                postings.append(position)

    planned = []
    for chunk in eighth:
        found = candidates_for(chunk, seventh, index, args.top_k, args.floor)
        planned.append((chunk, found))
    with_candidates = sum(1 for _, found in planned if found)
    print(
        json.dumps(
            {
                "eighth_chunks": len(eighth),
                "seventh_chunks": len(seventh),
                "chunks_with_candidates": with_candidates,
                "candidate_pairs": sum(len(f) for _, f in planned),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    delta_path = OUT_DIR / f"{args.doc_id}.jsonl"
    done: dict[str, dict] = {}
    if args.resume and delta_path.exists():
        for line in delta_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                # failed judgements are retried, not treated as final
                if row.get("relation") != "unjudged":
                    done[row["chunk_id"]] = row
    pending = [(chunk, found) for chunk, found in planned if chunk["chunk_id"] not in done]
    print(f"already={len(done)} pending={len(pending)}", flush=True)

    semaphore = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    mode = "a" if done else "w"
    client = httpx.AsyncClient(timeout=180)
    handle = delta_path.open(mode, encoding="utf-8")
    try:
        async def worker(item: tuple[dict, list[dict]]) -> None:
            chunk, found = item
            row = {
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "page": chunk["page"],
                "source": "kurose-8th",
                "candidates": [
                    {"chunk_id": c["chunk_id"], "score": c["score"], "page": c["page"]} for c in found
                ],
            }
            if not found:
                row.update(
                    relation="exclusive",
                    canonical_id=f"cn8th:{hashlib.sha256(chunk['text'].encode()).hexdigest()[:12]}",
                    source_versions=["kurose-8th"],
                    reason="无相似候选，属独有内容",
                )
            else:
                best = found[0]
                verdict = await judge(
                    client, semaphore, base, key, args.model, best["text"], chunk["text"]
                )
                if verdict is None:
                    row.update(relation="unjudged", reason="judge 失败")
                else:
                    relation = verdict["relation"]
                    row.update(relation=relation, reason=verdict.get("reason", "")[:200])
                    if relation == "equivalent":
                        row.update(
                            canonical_id=best["chunk_id"],
                            aliases=[chunk["text"][:120]],
                            source_versions=["kurose-7th", "kurose-8th"],
                        )
                    elif relation == "conflict":
                        group = "conflict:" + hashlib.sha256(best["chunk_id"].encode()).hexdigest()[:12]
                        row.update(
                            canonical_id=best["chunk_id"],
                            conflict_group_id=group,
                            conflict_stance=verdict.get("stance_b", ""),
                            counterpart_stance=verdict.get("stance_a", ""),
                            source_versions=["kurose-7th", "kurose-8th"],
                        )
                    elif relation == "complementary":
                        row.update(
                            canonical_id=f"cn8th:{hashlib.sha256(chunk['text'].encode()).hexdigest()[:12]}",
                            related_to=[best["chunk_id"]],
                            source_versions=["kurose-8th"],
                        )
                    else:
                        row.update(
                            canonical_id=f"cn8th:{hashlib.sha256(chunk['text'].encode()).hexdigest()[:12]}",
                            source_versions=["kurose-8th"],
                        )
            async with lock:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                done[row["chunk_id"]] = row
                if len(done) % 25 == 0:
                    print(f"progress {len(done)}/{len(planned)}", flush=True)

        await asyncio.gather(*(worker(item) for item in pending))
    finally:
        handle.close()
        await client.aclose()

    rows = list(done.values())
    counts = Counter(row.get("relation", "?") for row in rows)
    report = {
        "doc_id": args.doc_id,
        "source_a": "kurose-7th",
        "source_b": "kurose-8th",
        "chunks": len(rows),
        "relation_counts": dict(counts),
        "conflicts": [
            {"chunk_id": row["chunk_id"], "group": row.get("conflict_group_id"), "reason": row.get("reason")}
            for row in rows
            if row.get("relation") == "conflict"
        ],
        "delta_file": str(delta_path),
    }
    (OUT_DIR / f"{args.doc_id}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["relation_counts"], ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id", default="kurose8th")
    parser.add_argument("--model", default="glm-5.3")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--floor", type=float, default=0.2)
    parser.add_argument("--resume", action="store_true")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
