#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI for the build-knowledge-base skill.

Typical use:
  python scripts/kb_pipeline.py run --input <file-or-dir> --out <run-dir> --stop-after sample
  # inspect <run-dir>/integrity_report.md and chunk_plan.md
  python scripts/kb_pipeline.py run --input <file-or-dir> --out <run-dir> --stop-after ingest
  python scripts/kb_pipeline.py query --db <run-dir>/kb.sqlite --q "银行家算法"
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

# Make sibling imports work no matter which directory the CLI is called from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunker import choose_chunk_plan, chunk_document  # noqa: E402
from integrity import (  # noqa: E402
    check_integrity,
    render_integrity_report,
    sample_contiguous,
    write_integrity_outputs,
)
from parsers import ParseDependencyError, UnsupportedFormatError, parse_document  # noqa: E402
from store import delete_document_chunks, export_chunks_jsonl, get_stats, init_db, insert_chunks, insert_document, query_fts  # noqa: E402
from utils import (  # noqa: E402
    SUPPORTED_EXTENSIONS,
    format_bytes,
    iter_input_files,
    make_doc_id,
    now_iso,
    relative_posix,
    sha256_file,
    write_json,
    write_jsonl,
)


def _run_id() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + f"{random.randint(0, 9999):04d}"


def _load_state(out_dir: Path) -> dict[str, Any]:
    p = out_dir / "run_state.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _save_state(out_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    write_json(out_dir / "run_state.json", state)


def _print(msg: str = "") -> None:
    print(msg, flush=True)


# ----------------------------- phases -----------------------------

def inventory(input_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    root = Path(input_path).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not root.exists():
        raise FileNotFoundError(f"input does not exist: {root}")

    all_files: list[Path] = []
    if root.is_file():
        all_files = [root]
    else:
        out_resolved = out_dir.resolve()
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            try:
                if out_resolved == p.resolve() or out_resolved in p.resolve().parents:
                    continue
            except OSError:
                pass
            all_files.append(p)

    documents: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for p in all_files:
        suffix = p.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            unsupported.append({"path": str(p), "suffix": suffix, "size_bytes": p.stat().st_size})
            continue
        digest = sha256_file(p)
        documents.append({
            "doc_id": make_doc_id(p, digest),
            "source_path": str(p),
            "relative_path": relative_posix(p, root if root.is_dir() else root.parent),
            "format": suffix.lstrip("."),
            "size_bytes": p.stat().st_size,
            "size_human": format_bytes(p.stat().st_size),
            "source_hash": digest,
        })

    manifest = {
        "run_id": _run_id(),
        "input_root": str(root),
        "output_dir": str(out_dir.resolve()),
        "created_at": now_iso(),
        "documents": documents,
        "unsupported": unsupported,
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
    }
    write_json(out_dir / "manifest.json", manifest)

    lines = ["# Input inventory", ""]
    lines.append(f"- input: `{root}`")
    lines.append(f"- output (excluded from inventory): `{out_dir.resolve()}`")
    lines.append(f"- supported documents: {len(documents)}")
    lines.append(f"- unsupported files: {len(unsupported)}")
    lines.append("")
    lines.append("| doc_id | format | size | source |")
    lines.append("|---|---|---|---|")
    for d in documents:
        lines.append(f"| `{d['doc_id']}` | {d['format']} | {d['size_human']} | `{d['relative_path']}` |")
    if unsupported:
        lines.append("")
        lines.append("## Unsupported")
        for u in unsupported[:50]:
            lines.append(f"- `{u['path']}` ({u['suffix'] or 'no extension'})")
    (out_dir / "inventory_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _print(f"[inventory] {len(documents)} supported document(s), {len(unsupported)} unsupported file(s)")
    return manifest


def parse_all(manifest: dict[str, Any], out_dir: str | Path, ocr: str = "auto") -> list[dict[str, Any]]:
    out_dir = Path(out_dir)
    parsed_dir = out_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    docs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for entry in manifest.get("documents", []):
        path = Path(entry["source_path"])
        _print(f"[parse] {path.name}")
        try:
            parsed = parse_document(path, ocr=ocr)
            data = parsed.to_dict()
            data["created_at"] = now_iso()
            write_json(parsed_dir / f"{data['doc_id']}.json", data)
            docs.append(data)
        except (UnsupportedFormatError, ParseDependencyError, Exception) as exc:
            errors.append({"source_path": str(path), "error": str(exc)})
            _print(f"[parse] FAILED: {exc}")

    lines = ["# Parse report", ""]
    lines.append(f"- parsed: {len(docs)}")
    lines.append(f"- failed: {len(errors)}")
    lines.append("")
    lines.append("| doc_id | title | format | method | chars | units | warnings |")
    lines.append("|---|---|---|---|---|---|---|")
    for d in docs:
        warnings = "; ".join(d.get("warnings", [])) or "-"
        lines.append(
            f"| `{d['doc_id']}` | {d.get('title')} | {d.get('format')} | {d.get('parse_method')} "
            f"| {d.get('char_count')} | {d.get('unit_count')} | {warnings} |"
        )
    if errors:
        lines.append("")
        lines.append("## Errors")
        for e in errors:
            lines.append(f"- `{e['source_path']}`: {e['error']}")
    (out_dir / "parse_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _print(f"[parse] done: {len(docs)} ok, {len(errors)} failed")
    return docs


def sample_and_check(
    docs: list[dict[str, Any]],
    out_dir: str | Path,
    ratio: float = 0.10,
    seed: int = 42,
    windows: int = 1,
    min_units: int = 5,
) -> list[dict[str, Any]]:
    out_dir = Path(out_dir)
    reports: list[dict[str, Any]] = []
    for doc in docs:
        _print(f"[sample] {doc.get('title')} ({doc.get('unit_type')}, {doc.get('unit_count')} units)")
        sample = sample_contiguous(
            doc.get("units", []),
            doc.get("unit_type", "line"),
            ratio=ratio,
            seed=seed,
            windows=windows,
            min_units=min_units,
        )
        report = check_integrity(sample, doc)
        paths = write_integrity_outputs(doc, sample, report, out_dir)
        report["paths"] = paths
        reports.append(report)
        _print(f"[sample] verdict={report['verdict']} sample={report['sample']['sample_units']} units")
    render_integrity_report(docs, reports, out_dir)
    return reports


def plan_chunks(
    docs: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    out_dir: str | Path,
    forced_mode: str = "auto",
) -> list[dict[str, Any]]:
    out_dir = Path(out_dir)
    plans_dir = out_dir / "chunk_plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    report_by_doc = {r["doc_id"]: r for r in reports}
    plans: list[dict[str, Any]] = []
    for doc in docs:
        plan = choose_chunk_plan(report_by_doc.get(doc["doc_id"], {}), doc, forced_mode=forced_mode)
        plans.append(plan)
        write_json(plans_dir / f"{doc['doc_id']}.json", plan)

    lines = ["# Chunk plans", ""]
    for plan in plans:
        lines.append(f"## {plan.get('title')}")
        lines.append("")
        lines.append(f"- doc_id: `{plan.get('doc_id')}`")
        lines.append(f"- mode: **{plan.get('mode')}**")
        lines.append(f"- target/max/min chars: {plan.get('target_chars')}/{plan.get('max_chars')}/{plan.get('min_chars')}")
        lines.append(f"- overlap chars: {plan.get('overlap_chars')}")
        lines.append(
            f"- content page range: {plan.get('content_start_page')}-{plan.get('content_end_page')}"
        )
        lines.append(f"- blocked: {plan.get('blocked')}")
        lines.append("- rationale:")
        for reason in plan.get("rationale", []):
            lines.append(f"  - {reason}")
        lines.append("")
    (out_dir / "chunk_plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(out_dir / "chunk_plan.json", {"plans": plans})
    return plans


def chunk_all(
    docs: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    out_dir: str | Path,
    include_front_matter: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    out_dir = Path(out_dir)
    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    plan_by_doc = {p["doc_id"]: p for p in plans}
    by_doc: dict[str, list[dict[str, Any]]] = {}
    all_chunks: list[dict[str, Any]] = []

    for doc in docs:
        plan = plan_by_doc.get(doc["doc_id"])
        if not plan or plan.get("blocked"):
            _print(f"[chunk] SKIP {doc.get('title')}: plan blocked")
            continue
        chunks = chunk_document(doc, plan, include_front_matter=include_front_matter)
        by_doc[doc["doc_id"]] = chunks
        write_jsonl(chunks_dir / f"{doc['doc_id']}.jsonl", chunks)
        all_chunks.extend(chunks)
        sizes = [c["char_count"] for c in chunks]
        _print(
            f"[chunk] {doc.get('title')}: {len(chunks)} chunks, "
            f"avg={sum(sizes)/len(sizes):.0f}" if chunks else f"[chunk] {doc.get('title')}: 0 chunks"
        )

    write_jsonl(out_dir / "chunks.jsonl", all_chunks)
    _write_chunk_report(docs, by_doc, out_dir)
    return by_doc


def _write_chunk_report(docs: list[dict[str, Any]], by_doc: dict[str, list[dict[str, Any]]], out_dir: Path) -> None:
    lines = ["# Chunk report", ""]
    total = 0
    for doc in docs:
        chunks = by_doc.get(doc["doc_id"], [])
        total += len(chunks)
        sizes = [c["char_count"] for c in chunks]
        lines.append(f"## {doc.get('title')}")
        lines.append("")
        lines.append(f"- chunks: {len(chunks)}")
        if sizes:
            lines.append(f"- chars: min={min(sizes)}, avg={sum(sizes)/len(sizes):.0f}, max={max(sizes)}")
        lines.append(f"- chunk types: {', '.join(sorted({c['chunk_type'] for c in chunks})) or '-'}")
        if chunks:
            hashes = [c.get("content_hash") for c in chunks if c.get("content_hash")]
            duplicates = len(hashes) - len(set(hashes))
            with_heading = sum(1 for c in chunks if c.get("heading_path"))
            with_pages = sum(1 for c in chunks if c.get("page_start") is not None)
            lines.append(f"- duplicate content hashes: {duplicates}")
            lines.append(f"- chunks with heading path: {with_heading}/{len(chunks)}")
            lines.append(f"- chunks with page anchor: {with_pages}/{len(chunks)}")
        if chunks:
            preview = chunks[0]["content"][:600].replace("\n", " ")
            lines.append("")
            lines.append("First chunk preview:")
            lines.append("")
            lines.append("```text")
            lines.append(preview)
            lines.append("```")
        lines.append("")
    lines.append(f"Total chunks: {total}")
    (out_dir / "chunk_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def ingest_all(
    docs: list[dict[str, Any]],
    by_doc: dict[str, list[dict[str, Any]]],
    out_dir: str | Path,
    db_name: str = "kb.sqlite",
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    db_path = out_dir / db_name
    conn = init_db(db_path)
    for doc in docs:
        insert_document(conn, doc)
        delete_document_chunks(conn, doc["doc_id"])
        chunks = by_doc.get(doc["doc_id"], [])
        insert_chunks(conn, chunks)
    stats = get_stats(conn)
    conn.close()
    report = {"db_path": str(db_path), "stats": stats, "generated_at": now_iso()}
    write_json(out_dir / "ingest_report.json", report)
    _print(f"[ingest] {stats['documents']} docs, {stats['chunks']} chunks -> {db_path}")
    return report


def verify(out_dir: str | Path, top_k: int = 3) -> dict[str, Any]:
    out_dir = Path(out_dir)
    db_path = out_dir / "kb.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    conn = init_db(db_path)
    stats = get_stats(conn)
    rows = conn.execute(
        "SELECT chunk_id, content, heading_path FROM chunks ORDER BY rowid LIMIT 5"
    ).fetchall()
    probes = []
    for row in rows:
        query = row["content"][:60].strip()
        if not query:
            continue
        hits = query_fts(conn, query, top_k=top_k)
        probes.append({
            "query": query,
            "hits": len(hits),
            "top_chunk": hits[0]["chunk_id"] if hits else None,
            "top_score": hits[0]["score"] if hits else None,
        })
    conn.close()
    report = {"stats": stats, "probes": probes, "generated_at": now_iso()}
    write_json(out_dir / "verification_report.json", report)
    lines = ["# Verification report", ""]
    lines.append(f"- documents: {stats['documents']}")
    lines.append(f"- chunks: {stats['chunks']}")
    lines.append(f"- total chars: {stats['total_chars']:,}")
    lines.append(f"- avg chars/chunk: {stats['avg_chars']}")
    lines.append("")
    lines.append("| probe query | hits | top chunk | score |")
    lines.append("|---|---|---|---|")
    for p in probes:
        q = p["query"].replace("\n", " ").replace("\r", " ").replace("\t", " ").replace("|", " ")[:50]
        lines.append(f"| {q} | {p['hits']} | `{p['top_chunk']}` | {p['top_score']} |")
    (out_dir / "verification_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _print(f"[verify] {stats['documents']} docs, {stats['chunks']} chunks, {len(probes)} probes")
    return report


# ----------------------------- CLI -----------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build a knowledge base from documents.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--out", required=True, help="output run directory")

    run = sub.add_parser("run", help="run the pipeline")
    run.add_argument("--input", required=True, help="input file or directory")
    common(run)
    run.add_argument("--sample-ratio", type=float, default=0.10)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--sample-windows", type=int, default=1, help="number of contiguous sample windows")
    run.add_argument("--min-sample-units", type=int, default=5, help="minimum sample units even if 10%% is smaller")
    run.add_argument("--ocr", choices=["auto", "off", "force"], default="auto")
    run.add_argument(
        "--mode",
        choices=["auto", "hierarchical", "paragraph", "question", "code"],
        default="auto",
        help="force a chunking mode instead of auto-detecting it",
    )
    run.add_argument(
        "--include-front-matter",
        action="store_true",
        help="include cover/preface/index pages (PDF TOC range is skipped by default)",
    )
    run.add_argument(
        "--stop-after",
        choices=["parse", "sample", "plan", "chunk", "ingest"],
        default="plan",
        help="stop after this phase (default: plan; review integrity and chunk plan before chunking)",
    )

    inv = sub.add_parser("inventory", help="list supported files")
    inv.add_argument("--input", required=True)
    common(inv)

    parse = sub.add_parser("parse", help="parse documents")
    parse.add_argument("--input", required=True)
    common(parse)
    parse.add_argument("--ocr", choices=["auto", "off", "force"], default="auto")

    sample = sub.add_parser("sample", help="sample 10%% and check integrity")
    common(sample)
    sample.add_argument("--sample-ratio", type=float, default=0.10)
    sample.add_argument("--seed", type=int, default=42)
    sample.add_argument("--sample-windows", type=int, default=1)
    sample.add_argument("--min-sample-units", type=int, default=5)

    chunk = sub.add_parser("chunk", help="create chunk plan and chunk parsed docs")
    common(chunk)
    chunk.add_argument(
        "--mode",
        choices=["auto", "hierarchical", "paragraph", "question", "code"],
        default="auto",
    )
    chunk.add_argument("--include-front-matter", action="store_true")

    ingest = sub.add_parser("ingest", help="ingest chunks into SQLite/FTS5")
    common(ingest)
    ingest.add_argument("--db", default="kb.sqlite")

    verify_p = sub.add_parser("verify", help="verify the built database")
    common(verify_p)
    verify_p.add_argument("--top-k", type=int, default=3)

    query = sub.add_parser("query", help="query the built database")
    query.add_argument("--db", required=True)
    query.add_argument("--q", required=True)
    query.add_argument("--top-k", type=int, default=5)

    return p


def _load_parsed(out_dir: Path) -> list[dict[str, Any]]:
    parsed_dir = out_dir / "parsed"
    docs = []
    if parsed_dir.exists():
        for p in sorted(parsed_dir.glob("*.json")):
            docs.append(json.loads(p.read_text(encoding="utf-8")))
    return docs


def _load_reports(out_dir: Path) -> list[dict[str, Any]]:
    sample_dir = out_dir / "samples"
    reports = []
    if sample_dir.exists():
        for p in sorted(sample_dir.glob("*_integrity.json")):
            reports.append(json.loads(p.read_text(encoding="utf-8")))
    return reports


def _load_plans(out_dir: Path) -> list[dict[str, Any]]:
    plans_dir = out_dir / "chunk_plans"
    plans = []
    if plans_dir.exists():
        for p in sorted(plans_dir.glob("*.json")):
            plans.append(json.loads(p.read_text(encoding="utf-8")))
    return plans


def _load_chunks(out_dir: Path) -> dict[str, list[dict[str, Any]]]:
    chunks_dir = out_dir / "chunks"
    by_doc: dict[str, list[dict[str, Any]]] = {}
    if chunks_dir.exists():
        for p in sorted(chunks_dir.glob("*.jsonl")):
            rows = []
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
            if rows:
                by_doc[rows[0]["doc_id"]] = rows
    return by_doc


def main() -> int:
    args = _build_parser().parse_args()
    out_dir = Path(args.out) if getattr(args, "out", None) else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "inventory":
        manifest = inventory(args.input, out_dir)
        _save_state(out_dir, {"phase": "inventory", "input": args.input, "documents": len(manifest["documents"])})
        return 0

    if args.command == "run":
        state = _load_state(out_dir) or {
            "run_id": _run_id(),
            "input": str(Path(args.input).resolve()),
            "out_dir": str(out_dir.resolve()),
            "started_at": now_iso(),
            "config": {
                "sample_ratio": args.sample_ratio,
                "seed": args.seed,
                "sample_windows": args.sample_windows,
                "min_sample_units": args.min_sample_units,
                "ocr": args.ocr,
                "mode": args.mode,
            },
        }
        state["config"] = {
            "sample_ratio": args.sample_ratio,
            "seed": args.seed,
            "sample_windows": args.sample_windows,
            "min_sample_units": args.min_sample_units,
            "ocr": args.ocr,
            "mode": args.mode,
            "include_front_matter": args.include_front_matter,
        }
        state["phase"] = "inventory"
        _save_state(out_dir, state)
        manifest = inventory(args.input, out_dir)
        state["phase"] = "parse"
        _save_state(out_dir, state)
        docs = parse_all(manifest, out_dir, ocr=args.ocr)
        if not docs:
            _print("\nSTOP: no documents were parsed.")
            state["phase"] = "blocked_parse"
            _save_state(out_dir, state)
            return 1
        if args.stop_after == "parse":
            return 0
        if args.stop_after == "sample":
            sample_and_check(docs, out_dir, args.sample_ratio, args.seed, args.sample_windows, args.min_sample_units)
            _print("\nReview integrity_report.md. Re-run with --stop-after plan to generate the chunk plan.")
            return 0

        state["phase"] = "sample"
        _save_state(out_dir, state)
        reports = sample_and_check(docs, out_dir, args.sample_ratio, args.seed, args.sample_windows, args.min_sample_units)
        if any(r["verdict"] == "fail" for r in reports):
            _print("\nSTOP: at least one document failed integrity checks. Fix parsing/encoding/OCR first.")
            state["phase"] = "blocked_integrity"
            _save_state(out_dir, state)
            return 2

        state["phase"] = "plan"
        _save_state(out_dir, state)
        plans = plan_chunks(docs, reports, out_dir, forced_mode=args.mode)
        if any(p.get("blocked") for p in plans):
            _print("\nSTOP: at least one chunk plan is blocked.")
            state["phase"] = "blocked_plan"
            _save_state(out_dir, state)
            return 2
        if args.stop_after == "plan":
            _print("\nReview integrity_report.md and chunk_plan.md. Re-run with --stop-after ingest to build the KB.")
            return 0

        state["phase"] = "chunk"
        _save_state(out_dir, state)
        by_doc = chunk_all(docs, plans, out_dir, include_front_matter=args.include_front_matter)
        total_chunks = sum(len(v) for v in by_doc.values())
        if total_chunks == 0:
            _print("\nSTOP: no chunks were produced.")
            state["phase"] = "blocked_chunk"
            _save_state(out_dir, state)
            return 1
        if args.stop_after == "chunk":
            _save_state(out_dir, state)
            return 0

        state["phase"] = "ingest"
        _save_state(out_dir, state)
        ingest_report = ingest_all(docs, by_doc, out_dir)
        if ingest_report.get("stats", {}).get("chunks", 0) == 0:
            _print("\nSTOP: ingestion produced zero chunks.")
            state["phase"] = "blocked_ingest"
            _save_state(out_dir, state)
            return 1
        verify_report = verify(out_dir)
        state["phase"] = "done" if verify_report.get("stats", {}).get("chunks", 0) else "blocked_verify"
        _save_state(out_dir, state)
        return 0 if state["phase"] == "done" else 1

    if args.command == "parse":
        manifest = inventory(args.input, out_dir)
        docs = parse_all(manifest, out_dir, ocr=args.ocr)
        _save_state(out_dir, {"phase": "parse", "documents": len(docs)})
        return 0 if docs else 1

    if args.command == "sample":
        docs = _load_parsed(out_dir)
        if not docs:
            _print("No parsed documents found. Run parse first.")
            return 1
        reports = sample_and_check(docs, out_dir, args.sample_ratio, args.seed, args.sample_windows, args.min_sample_units)
        _save_state(out_dir, {"phase": "sample", "documents": len(docs)})
        return 2 if any(r["verdict"] == "fail" for r in reports) else 0

    if args.command == "chunk":
        docs = _load_parsed(out_dir)
        reports = _load_reports(out_dir)
        if not docs or not reports:
            _print("Missing parsed docs or integrity reports. Run parse and sample first.")
            return 1
        existing_plans = _load_plans(out_dir)
        if args.mode == "auto" and existing_plans and len(existing_plans) >= len(docs):
            plans = existing_plans
            _print("[chunk] reusing existing chunk plans (edit them before this step)")
        else:
            plans = plan_chunks(docs, reports, out_dir, forced_mode=args.mode)
        if any(p.get("blocked") for p in plans):
            _print("At least one plan is blocked by integrity failure.")
            return 2
        by_doc = chunk_all(docs, plans, out_dir, include_front_matter=args.include_front_matter)
        total_chunks = sum(len(v) for v in by_doc.values())
        _save_state(out_dir, {"phase": "chunk", "documents": len(docs), "chunks": total_chunks})
        return 0 if total_chunks else 1

    if args.command == "ingest":
        docs = _load_parsed(out_dir)
        by_doc = _load_chunks(out_dir)
        if not docs or not by_doc:
            _print("Missing parsed docs or chunks. Run parse, sample, and chunk first.")
            return 1
        ingest_all(docs, by_doc, out_dir, db_name=args.db)
        _save_state(out_dir, {"phase": "ingest", "documents": len(docs)})
        return 0

    if args.command == "verify":
        rep = verify(out_dir, top_k=args.top_k)
        return 0 if rep.get("stats", {}).get("chunks", 0) else 1

    if args.command == "query":
        conn = init_db(args.db)
        hits = query_fts(conn, args.q, top_k=args.top_k)
        conn.close()
        if not hits:
            print("No hits.")
            return 1
        for i, hit in enumerate(hits, 1):
            print(f"\n[{i}] score={hit['score']:.4f} chunk={hit['chunk_id']}")
            print(f"heading: {hit['heading_path']}")
            print(f"pages: {hit['page_start']}-{hit['page_end']}")
            print(hit["content"][:500].replace("\n", " "))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
