#!/usr/bin/env python3
"""Knowledge-base dedup registry (P3/P4/P5).

Three layers:

  L1 file hash     sha256 of the raw file            -> block re-import
  L2 content hash  sha256 of normalised full text    -> block same content,
                                                        different packaging/source
  L3 chunk hash    sha256 of each normalised chunk   -> delta import: only new
                                                        chunks are added

Edition handling: when L1/L2 both miss but the text overlaps an existing book of
the same subject above a threshold, the incoming file is treated as another
edition. It may be imported, and a delta report lists added/removed chunks.

Registry is a separate SQLite file so the per-subject kb.sqlite stays untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

DEFAULT_REGISTRY = Path(r"D:\Code\hku\LLM\kb_review\registry.sqlite")
KB_ROOT = Path(r"D:\Code\hku\LLM\kb_review\books")
PAGE_MARKER = re.compile(r"\[\[PAGE:\d+\]\]")
NON_CONTENT = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]+")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,
    subject         TEXT NOT NULL,
    title           TEXT,
    source_path     TEXT,
    file_sha256     TEXT UNIQUE,
    content_sha256  TEXT,
    edition         TEXT,
    chunk_count     INTEGER,
    term_fingerprint TEXT,
    added_at        TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chunk_registry (
    chunk_hash   TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL,
    first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunk_registry(doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_subject ON documents(subject);
"""


def connect(path: Path = DEFAULT_REGISTRY) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("pragma table_info(documents)")}
    if "term_fingerprint" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN term_fingerprint TEXT")
    return conn


def _existing_units(subject: str, limit: int = 3000) -> list[str]:
    """Unit texts of already-ingested books of this subject (from parsed JSON)."""
    units: list[str] = []
    for parsed in sorted((KB_ROOT / subject / "parsed").glob("*.json")):
        try:
            data = json.loads(parsed.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        units.extend(
            unit["text"] for unit in data.get("units", []) if unit.get("text", "").strip()
        )
        if len(units) >= limit:
            break
    return units[:limit]


def trigrams(text: str) -> set[str]:
    norm = normalize_text(text)
    return {norm[i : i + 3] for i in range(len(norm) - 2)} if len(norm) >= 3 else set()


def edition_number(name: str) -> str:
    """Extract an edition marker such as 第7版 / 原书第8版 / 第2版."""
    match = re.search(r"第\s*([0-9一二三四五六七八九十]+)\s*版", name)
    return match.group(1) if match else ""


def near_duplicate_coverage(
    new_units: list[str],
    existing_units: list[str],
    containment: float = 0.9,
    max_candidates: int = 40,
) -> float:
    """Share of new units that already exist in the corpus.

    A unit counts as existing when an existing unit covers at least
    ``containment`` of its character trigrams. Exact hashes cannot be used:
    re-OCR of the same page yields different hashes for identical content.
    """
    if not new_units or not existing_units:
        return 0.0
    existing_sets = [trigrams(unit) for unit in existing_units]
    index: dict[str, list[int]] = {}
    for position, grams in enumerate(existing_sets):
        for gram in grams:
            postings = index.setdefault(gram, [])
            if len(postings) < 60:
                postings.append(position)
    seen = 0
    for unit in new_units:
        grams = trigrams(unit)
        if not grams:
            continue
        votes: Counter[int] = Counter()
        for gram in grams:
            for position in index.get(gram, ()):
                votes[position] += 1
        for position, hits in votes.most_common(max_candidates):
            smaller = min(len(grams), len(existing_sets[position]))
            if smaller and hits / smaller >= containment:
                seen += 1
                break
    return seen / len(new_units)


def term_fingerprint(text: str, topk: int = 400) -> str:
    """Compact content signature: the most frequent CJK/Latin bigrams."""
    norm = normalize_text(text)
    grams = Counter(norm[i : i + 2] for i in range(len(norm) - 1))
    return json.dumps([gram for gram, _ in grams.most_common(topk)], ensure_ascii=False)


def fingerprint_jaccard(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    set_a, set_b = set(json.loads(a)), set(json.loads(b))
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 0.0


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    text = PAGE_MARKER.sub(" ", text)
    text = NON_CONTENT.sub("", text)
    return text.lower()


def content_sha256(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def chunk_sha256(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def shingles(text: str, size: int = 12, sample: int = 3) -> set[int]:
    norm = normalize_text(text)
    if len(norm) < size:
        return set()
    out: set[int] = set()
    for i in range(len(norm) - size + 1):
        h = hash(norm[i : i + size])
        if h % sample == 0:
            out.add(h)
    return out


def jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def extract_pdf_text(path: Path) -> str:
    import fitz

    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def title_tokens(name: str) -> set[str]:
    text = re.sub(r"\((?:z-library|1lib)[^)]*\)", " ", name)
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", text)
    words = set(re.findall(r"[A-Za-z]{2,}", text.lower()))
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
    bigrams = {cjk[i : i + 2] for i in range(len(cjk) - 1)}
    return words | bigrams


def title_similarity(a: str, b: str) -> float:
    ta, tb = title_tokens(a), title_tokens(b)
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def author_tokens(name: str) -> set[str]:
    """Author signatures: latin name words plus CJK names longer than one char."""
    cleaned = re.sub(r"\((?:z-library|1lib)[^)]*\)", " ", name)
    cleaned = re.sub(r"[（(]\s*原书第?\s*\d+\s*版\s*[）)]", " ", cleaned)
    groups = re.findall(r"[（(]([^）)]{2,80})[）)]", cleaned)
    tokens: set[str] = set()
    for group in groups:
        if re.match(r"^\s*\d", group) or "版" in group:
            continue
        tokens |= {word.lower() for word in re.findall(r"[A-Za-z]{3,}", group)}
        tokens |= {
            name for name in re.findall(r"[\u4e00-\u9fff]{2,4}", group) if len(name) >= 2
        }
    return tokens


def authors_match(a: str, b: str) -> bool:
    ta, tb = author_tokens(a), author_tokens(b)
    return bool(ta & tb)


def classify_pair(
    incoming_title: str, existing_title: str, threshold: float = 0.35
) -> tuple[str, float]:
    """Return (relation, title_similarity).

    relation: same_edition (shared author, similar title) / sibling (similar
    title, no shared author) / unrelated.
    """
    score = title_similarity(incoming_title, existing_title)
    if score < threshold:
        return "unrelated", round(score, 4)
    return (
        ("same_edition" if authors_match(incoming_title, existing_title) else "sibling"),
        round(score, 4),
    )


def check_document(
    pdf: Path,
    subject: str,
    registry: Path = DEFAULT_REGISTRY,
    threshold: float = 0.35,
    parsed_json: Path | None = None,
) -> dict:
    """Return the blocking decision for an incoming PDF."""
    file_hash = file_sha256(pdf)
    conn = connect(registry)
    row = conn.execute(
        "SELECT doc_id, subject, title, added_at FROM documents WHERE file_sha256 = ?",
        (file_hash,),
    ).fetchone()
    if row:
        conn.close()
        return {
            "decision": "blocked_L1",
            "reason": "同一文件已入库（L1 文件哈希相同）",
            "existing_doc_id": row[0],
            "existing_subject": row[1],
            "existing_title": row[2],
            "added_at": row[3],
        }

    if parsed_json is not None:
        parsed = json.loads(parsed_json.read_text(encoding="utf-8"))
        text = "".join(unit["text"] for unit in parsed.get("units", []))
    else:
        try:
            text = extract_pdf_text(pdf)
        except Exception as exc:  # corrupt file, encrypted PDF, missing text layer
            conn.close()
            return {
                "decision": "blocked_unreadable",
                "reason": f"无法读取 PDF 文本层（{type(exc).__name__}），先修复文件或走 OCR",
                "path": str(pdf),
            }
    has_text_layer = len(normalize_text(text)) >= 5000
    content_hash = content_sha256(text) if has_text_layer else None
    if content_hash:
        row = conn.execute(
            "SELECT doc_id, subject, title, source_path FROM documents WHERE content_sha256 = ?",
            (content_hash,),
        ).fetchone()
        if row:
            conn.close()
            return {
                "decision": "blocked_L2",
                "reason": "正文内容与已入库书籍完全一致（L2 内容哈希相同，来源不同）",
                "existing_doc_id": row[0],
                "existing_subject": row[1],
                "existing_title": row[2],
                "existing_source": row[3],
            }

    candidates = conn.execute(
        "SELECT doc_id, title, source_path, term_fingerprint FROM documents WHERE subject = ?",
        (subject,),
    ).fetchall()
    conn.close()

    incoming_fp = term_fingerprint(text) if has_text_layer else ""
    comparisons = []
    for doc_id, title, _source, existing_fp in candidates:
        text_score = (
            round(fingerprint_jaccard(incoming_fp, existing_fp), 4)
            if incoming_fp and existing_fp
            else None
        )
        title_relation, title_score = classify_pair(pdf.stem, title or "", threshold)
        incoming_edition = edition_number(pdf.stem)
        existing_edition = edition_number(title or "")
        if incoming_edition and existing_edition and incoming_edition != existing_edition:
            relation, evidence = "same_edition", "edition-number"
        elif text_score is not None and text_score >= 0.85:
            # near-identical text: only a duplicate when the coverage says the
            # content is already here, otherwise it may be a light revision.
            relation, evidence = "duplicate_candidate", "text"
        elif text_score is not None and text_score >= 0.6:
            relation, evidence = "same_edition", "text"
        else:
            relation, evidence = title_relation, "title+author"
        comparisons.append(
            {
                "doc_id": doc_id,
                "title": title,
                "relation": relation,
                "evidence": evidence,
                "text_similarity": text_score,
                "title_similarity": title_score,
                "incoming_edition": incoming_edition,
                "existing_edition": existing_edition,
            }
        )
    comparisons.sort(
        key=lambda item: item["text_similarity"] if item["text_similarity"] is not None else item["title_similarity"],
        reverse=True,
    )
    editions = [item for item in comparisons if item["relation"] == "same_edition"]
    duplicates = [item for item in comparisons if item["relation"] == "duplicate_candidate"]
    siblings = [item for item in comparisons if item["relation"] == "sibling"]

    coverage = None
    if duplicates and has_text_layer:
        coverage = near_duplicate_coverage(
            [part for part in re.split(r"\n\s*\n", text) if part.strip()][:600],
            _existing_units(subject),
        )
        duplicates[0]["coverage"] = round(coverage, 4)

    if duplicates and coverage is not None and coverage >= 0.98:
        decision = "rejected_duplicate"
        reason = (
            f"文本相似度 {duplicates[0]['text_similarity']:.3f} 且近似重复覆盖率 "
            f"{coverage:.3f} ≥ 0.98，视为同内容不同来源，拒绝入库"
        )
    elif editions:
        decision = "delta_edition"
        reason = (
            f"证据 {editions[0]['evidence']}：版次 {editions[0]['incoming_edition'] or '未知'} vs "
            f"{editions[0]['existing_edition'] or '未知'}，书名相似度 "
            f"{editions[0]['title_similarity']:.3f}，走增量导入"
        )
    elif duplicates:
        decision = "delta_edition"
        reason = (
            f"文本相似度 {duplicates[0]['text_similarity']:.3f} 但覆盖率 "
            f"{coverage if coverage is not None else '未知'} < 0.98，判为小幅修订，走增量导入"
        )
    elif siblings:
        decision = "sibling_book"
        reason = (
            f"书名相似 {siblings[0]['title_similarity']:.3f} 但作者不同，"
            "判为同科不同书，允许导入并提示"
        )
    else:
        decision = "new_book"
        reason = "未发现同作者或高相似度书籍，视为新书"
    return {
        "decision": decision,
        "reason": reason,
        "file_sha256": file_hash,
        "content_sha256": content_hash,
        "has_text_layer": has_text_layer,
        "needs_mineru": not has_text_layer,
        "coverage": round(coverage, 4) if coverage is not None else None,
        "comparisons": comparisons[:5],
    }


def register_run(
    run_dir: Path,
    subject: str,
    source_path: Path,
    registry: Path = DEFAULT_REGISTRY,
) -> dict:
    """Register a completed run directory and record its chunk hashes."""
    chunks_file = run_dir / "chunks.jsonl"
    if not chunks_file.exists():
        raise SystemExit(f"missing {chunks_file}")
    docs = [
        json.loads(line)
        for line in chunks_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    doc_id = docs[0]["doc_id"] if docs else None
    if not doc_id:
        raise SystemExit("no chunks in chunks.jsonl")
    manifest_path = run_dir / "manifest.json"
    title = ""
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("documents") or []
        if entries:
            title = entries[0].get("title") or Path(
                entries[0].get("source_path", "")
            ).stem
    if not title:
        title = source_path.stem
    text = "".join(item["content"] for item in docs)
    conn = connect(registry)
    seen = [
        conn.execute("SELECT doc_id FROM chunk_registry WHERE chunk_hash = ?", (h,)).fetchone()
        for h in (chunk_sha256(item["content"]) for item in docs)
    ]
    new_chunks = sum(1 for row in seen if row is None)
    duplicate_chunks = len(seen) - new_chunks
    conn.execute(
        "INSERT OR REPLACE INTO documents"
        "(doc_id, subject, title, source_path, file_sha256, content_sha256, chunk_count, term_fingerprint)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            doc_id,
            subject,
            title,
            str(source_path),
            file_sha256(source_path) if source_path.exists() else None,
            content_sha256(text),
            len(docs),
            term_fingerprint(text),
        ),
    )
    for item in docs:
        conn.execute(
            "INSERT OR IGNORE INTO chunk_registry(chunk_hash, doc_id) VALUES (?,?)",
            (chunk_sha256(item["content"]), doc_id),
        )
    conn.commit()
    conn.close()
    return {
        "doc_id": doc_id,
        "chunks": len(docs),
        "new_chunks": new_chunks,
        "duplicate_chunks": duplicate_chunks,
    }


def compare(a: Path, b: Path) -> dict:
    text_a = extract_pdf_text(a)
    text_b = extract_pdf_text(b)
    return {
        "a": a.name,
        "b": b.name,
        "a_chars": len(normalize_text(text_a)),
        "b_chars": len(normalize_text(text_b)),
        "jaccard": round(jaccard(shingles(text_a), shingles(text_b)), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="decide whether a PDF may be imported")
    check.add_argument("--pdf", required=True)
    check.add_argument("--subject", required=True)
    check.add_argument("--threshold", type=float, default=0.35)
    check.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    check.add_argument("--parsed", default="", help="parsed JSON to use as text source (post-parse check)")

    reg = sub.add_parser("register", help="record a completed run directory")
    reg.add_argument("--run-dir", required=True)
    reg.add_argument("--subject", required=True)
    reg.add_argument("--source", required=True)
    reg.add_argument("--registry", default=str(DEFAULT_REGISTRY))

    cmp = sub.add_parser("compare", help="similarity between two PDFs")
    cmp.add_argument("--a", required=True)
    cmp.add_argument("--b", required=True)

    args = parser.parse_args()
    if args.cmd == "check":
        result = check_document(
            Path(args.pdf),
            args.subject,
            Path(args.registry),
            args.threshold,
            Path(args.parsed) if args.parsed else None,
        )
    elif args.cmd == "register":
        result = register_run(
            Path(args.run_dir), args.subject, Path(args.source), Path(args.registry)
        )
    else:
        result = compare(Path(args.a), Path(args.b))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
