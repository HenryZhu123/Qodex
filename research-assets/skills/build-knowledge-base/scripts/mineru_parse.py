#!/usr/bin/env python3
"""MinerU-based PDF parsing for the knowledge base (D1 + D2).

Replaces the Tesseract path. Constraints that shape this module:

  * MinerU Agent API accepts at most 10 MB per file, so large books are split
    into page-range parts (~9 MB each) and stitched back in order.
  * MinerU returns Markdown without guaranteed page numbers, so each part is
    wrapped in a ``[[PAGES:start-end]]`` marker and every unit records the part
    page range with ``page_precision = "volume"``.

Output keeps the existing pipeline contract: ``parsed/<doc_id>.json`` with a
``units`` list of ``{index, text, page}``, so the current chunker can consume it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import fitz

SERVICE_SRC = Path(r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src")
if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from exam_checker.integrations.mineru_agent import (  # noqa: E402
    MinerUAgentClient,
    MinerULimitError,
)

MAX_PART_BYTES = 9 * 1024 * 1024
MAX_PAGES_PER_PART = 20  # hard API limit, independent of the 10 MB cap
BLOCK_SPLIT = re.compile(r"\n\s*\n")


def doc_id_for(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def split_pdf(pdf: Path, out_dir: Path, max_bytes: int = MAX_PART_BYTES, max_pages: int = MAX_PAGES_PER_PART) -> list[dict]:
    """Split a PDF into page-range parts no larger than ``max_bytes``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    total_bytes = pdf.stat().st_size
    with fitz.open(pdf) as doc:
        total_pages = doc.page_count
        estimate = min(max_pages, max(1, int(total_pages * max_bytes / max(total_bytes, 1) * 0.9)))
        parts: list[dict] = []
        start = 0
        while start < total_pages:
            count = min(estimate, total_pages - start)
            while True:
                end = start + count - 1
                part_path = out_dir / f"part_{start + 1:04d}_{end + 1:04d}.pdf"
                with fitz.open() as part:
                    part.insert_pdf(doc, from_page=start, to_page=end)
                    part.save(part_path, garbage=3, deflate=True)
                size = part_path.stat().st_size
                if (size <= max_bytes and count <= max_pages) or count == 1:
                    break
                part_path.unlink(missing_ok=True)
                count = max(1, count // 2)
            parts.append(
                {
                    "path": part_path,
                    "page_start": start + 1,
                    "page_end": end + 1,
                    "bytes": size,
                }
            )
            start = end + 1
    return parts


async def parse_parts(
    parts: list[dict],
    base_url: str,
    language: str,
    use_ocr: bool,
    max_attempts: int = 4,
) -> list[dict]:
    """Send each part to MinerU sequentially (IP rate limited) with backoff."""
    results: list[dict] = []
    client = MinerUAgentClient(base_url=base_url)
    try:
        for index, part in enumerate(parts, start=1):
            md_path = part["path"].with_suffix(".md")
            if md_path.exists() and md_path.stat().st_size > 0:
                results.append(
                    {
                        **part,
                        "markdown": md_path.read_text(encoding="utf-8"),
                        "provider_task_id": "cached",
                        "elapsed_s": 0.0,
                        "attempts": 0,
                    }
                )
                print(
                    f"[{index}/{len(parts)}] pages {part['page_start']}-{part['page_end']} cached",
                    flush=True,
                )
                continue
            payload = part["path"].read_bytes()
            delay = 5.0
            for attempt in range(1, max_attempts + 1):
                started = time.perf_counter()
                try:
                    extracted = await client.parse_file(
                        payload,
                        part["path"].name,
                        language=language,
                        is_ocr=use_ocr,
                        enable_table=True,
                        enable_formula=True,
                    )
                    results.append(
                        {
                            **part,
                            "markdown": extracted.markdown,
                            "provider_task_id": extracted.provider_task_id,
                            "elapsed_s": round(time.perf_counter() - started, 1),
                            "attempts": attempt,
                        }
                    )
                    md_path.write_text(extracted.markdown, encoding="utf-8")
                    print(
                        f"[{index}/{len(parts)}] pages {part['page_start']}-{part['page_end']} "
                        f"ok in {results[-1]['elapsed_s']}s, {len(extracted.markdown)} chars",
                        flush=True,
                    )
                    break
                except MinerULimitError as exc:
                    print(f"  part {index} rate limited (attempt {attempt}): {exc}", flush=True)
                    await asyncio.sleep(delay * 2)
                    delay *= 2
                except Exception as exc:  # noqa: BLE001
                    print(f"  part {index} failed (attempt {attempt}): {type(exc).__name__}: {exc}", flush=True)
                    if attempt == max_attempts:
                        raise
                    await asyncio.sleep(delay)
                    delay *= 2
    finally:
        await client.close()
    return results


def merge_markdown(results: list[dict]) -> str:
    chunks: list[str] = []
    for part in results:
        chunks.append(
            f"[[PAGES:{part['page_start']}-{part['page_end']}]]\n{part['markdown'].strip()}"
        )
    return "\n\n".join(chunks)


def markdown_to_units(markdown: str) -> list[dict]:
    """Split merged markdown into units, carrying the enclosing page range."""
    units: list[dict] = []
    current_range = (0, 0)
    index = 0
    for block in BLOCK_SPLIT.split(markdown):
        block = block.strip()
        if not block:
            continue
        marker = re.match(r"\[\[PAGES:(\d+)-(\d+)\]\]\s*(.*)", block, re.S)
        if marker:
            current_range = (int(marker.group(1)), int(marker.group(2)))
            block = marker.group(3).strip()
            if not block:
                continue
        index += 1
        units.append(
            {
                "index": index,
                "text": block,
                "page": current_range[0],
                "page_start": current_range[0],
                "page_end": current_range[1],
                "page_precision": "volume",
            }
        )
    return units


async def run(args: argparse.Namespace) -> int:
    pdf = Path(args.pdf).resolve()
    out_root = Path(args.out).resolve()
    doc_id = doc_id_for(pdf)
    run_dir = out_root
    parts_dir = run_dir / "mineru_parts"
    parsed_dir = run_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)

    parts = split_pdf(pdf, parts_dir, args.max_bytes, args.max_pages)
    print(
        json.dumps(
            [
                {"pages": f"{p['page_start']}-{p['page_end']}", "MB": round(p["bytes"] / 1048576, 2)}
                for p in parts
            ],
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.dry_run:
        return 0

    results = await parse_parts(
        parts,
        "https://mineru.net/api/v1/agent",
        args.language,
        not args.no_ocr,
        args.max_attempts,
    )
    merged = merge_markdown(results)
    (run_dir / "mineru_raw.md").write_text(merged, encoding="utf-8")

    units = markdown_to_units(merged)
    parsed = {
        "doc_id": doc_id,
        "source_path": str(pdf),
        "title": pdf.stem,
        "format": "pdf",
        "parse_method": "mineru-agent",
        "unit_type": "page_range",
        "unit_count": len(parts),
        "char_count": sum(len(unit["text"]) for unit in units),
        "language": args.language,
        "page_precision": "volume",
        "parts": [
            {"pages": f"{p['page_start']}-{p['page_end']}", "task_id": p["provider_task_id"]}
            for p in results
        ],
        "units": units,
    }
    target = parsed_dir / f"{doc_id}.json"
    target.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "doc_id": doc_id,
                "parts": len(results),
                "units": len(units),
                "chars": parsed["char_count"],
                "parsed": str(target),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-bytes", type=int, default=MAX_PART_BYTES)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES_PER_PART)
    parser.add_argument("--language", default="ch")
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true", help="only split, do not call MinerU")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
