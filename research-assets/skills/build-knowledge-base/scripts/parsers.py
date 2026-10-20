#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Document parsers for the build-knowledge-base skill.

Every parser returns a ParsedDocument with:
  - normalized full text
  - ordered units (page / paragraph / line / block)
  - metadata and warnings

The unit list is what the 10% integrity sampler operates on.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils import (
    detect_language,
    make_doc_id,
    normalize_text,
    sanitize_text,
    sha256_file,
    safe_slug,
)


@dataclass
class ParsedDocument:
    doc_id: str
    source_path: str
    format: str
    title: str
    text: str
    units: list[dict[str, Any]]
    unit_type: str
    parse_method: str
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "format": self.format,
            "title": self.title,
            "text": self.text,
            "units": self.units,
            "unit_type": self.unit_type,
            "parse_method": self.parse_method,
            "metadata": self.metadata,
            "warnings": self.warnings,
            "language": detect_language(self.text),
            "char_count": len(self.text),
            "unit_count": len(self.units),
        }


PDF_PAGE_NUM_RE = re.compile(r"^\s*[0-9IVXivx]{1,6}\s*$")
PDF_CHAPTER_RE = re.compile(
    r"^(?:第\s*[0-9一二三四五六七八九十百千]+\s*[章节]|Chapter\s+\d+|Appendix\s+[A-Z0-9]|[0-9]+\s*[.．]\s+\S)",
    re.IGNORECASE,
)
PDF_BACK_MATTER_RE = re.compile(r"^(?:参考文献|索引|参考答案|附录|Appendix|References|Index|Glossary)", re.IGNORECASE)


class UnsupportedFormatError(ValueError):
    pass


class ParseDependencyError(RuntimeError):
    pass


def parse_document(path: str | Path, ocr: str = "auto") -> ParsedDocument:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(p, ocr=ocr)
    if suffix == ".docx":
        return parse_docx(p)
    if suffix == ".doc":
        return parse_doc(p)
    if suffix in {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".log"}:
        return parse_text(p)
    if suffix in {".html", ".htm"}:
        return parse_html(p)
    raise UnsupportedFormatError(f"unsupported input format: {suffix}")


# ----------------------------- PDF -----------------------------

def _ocr_page(page, dpi: int = 200) -> str:
    """Render a PDF page and OCR it. Returns empty string if OCR is unavailable."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return ""
    try:
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        try:
            return pytesseract.image_to_string(img, lang="chi_sim+eng")
        except Exception:
            return pytesseract.image_to_string(img, lang="eng")
    except Exception:
        return ""


def _pdf_block_text(block: dict) -> str:
    lines = []
    for line in block.get("lines", []):
        line_text = "".join(span.get("text", "") for span in line.get("spans", []))
        lines.append(line_text)
    return "\n".join(lines).strip()


def parse_pdf(path: Path, ocr: str = "auto") -> ParsedDocument:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise ParseDependencyError("PyMuPDF is required for PDF parsing: pip install pymupdf") from exc

    doc = fitz.open(str(path))
    page_records: list[dict[str, Any]] = []
    warnings: list[str] = []
    low_density_pages: list[int] = []
    used_ocr = False
    toc = []
    try:
        toc = doc.get_toc()
    except Exception:
        toc = []

    # Use the PDF outline to skip cover/preface/index pages when possible.
    chapter_entries: list[tuple[str, int]] = []
    back_matter_pages: list[int] = []
    for lvl, title, page in toc:
        t = sanitize_text(str(title))
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        if lvl == 1 and PDF_CHAPTER_RE.match(t):
            chapter_entries.append((t, int(page)))
        if PDF_BACK_MATTER_RE.match(t):
            back_matter_pages.append(int(page))

    content_start_page = min((p for _, p in chapter_entries), default=None)
    content_end_page = (
        min(back_matter_pages) - 1 if back_matter_pages else len(doc)
    )
    if content_start_page is not None:
        content_start_page = max(1, min(content_start_page, len(doc)))
        content_end_page = max(content_start_page, min(content_end_page, len(doc)))
        if content_start_page > 1:
            warnings.append(
                f"Skipped front matter pages 1-{content_start_page - 1} based on the PDF TOC; "
                "use --include-front-matter to keep them."
            )
        if content_end_page < len(doc):
            warnings.append(
                f"Skipped back matter pages {content_end_page + 1}-{len(doc)} based on the PDF TOC; "
                "use --include-front-matter to keep them."
            )

    # Pass 1: collect blocks and find repeated header/footer strings.
    header_footer_counts: Counter[str] = Counter()
    for i in range(len(doc)):
        page = doc[i]
        h = page.rect.height
        raw_text = normalize_text(page.get_text("text"))
        blocks: list[dict[str, Any]] = []
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type") != 0:
                continue
            text = _pdf_block_text(b).strip()
            if not text:
                continue
            bbox = b["bbox"]
            blocks.append({"text": text, "bbox": bbox})
            # Header/footer candidates live near the top or bottom of the page.
            if (bbox[1] < 60 or bbox[3] > h - 60) and len(text) < 60:
                header_footer_counts[text] += 1
        page_records.append({
            "page": i + 1,
            "height": h,
            "raw_text": raw_text,
            "blocks": blocks,
        })

    repeat_threshold = max(3, int(len(doc) * 0.05))
    repeated_headers = {
        text for text, count in header_footer_counts.items() if count >= repeat_threshold
    }

    # Pass 2: remove vertical sidebars, page numbers, and repeated headers/footers.
    units: list[dict[str, Any]] = []
    removed_vertical = 0
    removed_header_footer = 0
    for rec in page_records:
        kept: list[str] = []
        h = rec["height"]
        for b in rec["blocks"]:
            text = b["text"]
            x0, y0, x1, y1 = b["bbox"]
            if text in repeated_headers:
                removed_header_footer += 1
                continue
            # Page numbers or short furniture in the top/bottom margin.
            if (y0 < 35 or y1 > h - 35) and (PDF_PAGE_NUM_RE.match(text) or len(text) < 30):
                removed_header_footer += 1
                continue
            # Vertical sidebar text: tall, narrow, one or two characters per line.
            lines = [ln for ln in text.splitlines() if ln.strip()]
            if (
                len(lines) >= 3
                and all(len(ln.strip()) <= 2 for ln in lines)
                and (y1 - y0) > 2.5 * max(1.0, x1 - x0)
            ):
                removed_vertical += 1
                continue
            kept.append(text)

        page_text = normalize_text("\n".join(kept))
        # Remove a vertical chapter marker at the very start of a page, e.g.
        # "第\n9\n章\n..." produced by some textbook layouts.
        page_text = re.sub(
            r"^第\s*\n\s*[0-9一二三四五六七八九十百千]+\s*\n\s*章\s*\n",
            "",
            page_text,
        ).lstrip()
        # If cleaning removed everything, fall back to the raw text layer.
        if len(page_text) < 30 and len(rec["raw_text"]) >= 30:
            page_text = rec["raw_text"]

        if len(page_text) < 30 and ocr in {"auto", "force"}:
            ocr_text = _ocr_page(doc[rec["page"] - 1])
            if ocr_text.strip():
                page_text = normalize_text(ocr_text)
                used_ocr = True
            else:
                low_density_pages.append(rec["page"])
        elif len(page_text) < 80:
            low_density_pages.append(rec["page"])

        units.append({"index": rec["page"], "text": page_text, "page": rec["page"]})

    full_parts = []
    for unit in units:
        full_parts.append(f"[[PAGE:{unit['page']}]]\n{unit['text']}")
    full_text = normalize_text("\n\n".join(full_parts))

    if low_density_pages:
        warnings.append(
            f"{len(low_density_pages)} page(s) have low text density; "
            f"first pages: {low_density_pages[:10]}. OCR may be required."
        )
    if used_ocr:
        warnings.append("OCR was used on at least one page; verify OCR text integrity before ingestion.")
    if removed_vertical:
        warnings.append(f"Removed {removed_vertical} vertical sidebar block(s).")
    if removed_header_footer:
        warnings.append(f"Removed {removed_header_footer} header/footer block(s).")

    title = path.stem
    try:
        pdf_meta = doc.metadata or {}
        if pdf_meta.get("title"):
            title = str(pdf_meta["title"]).strip() or title
    except Exception:
        pdf_meta = {}

    doc.close()
    source_hash = sha256_file(path)
    return ParsedDocument(
        doc_id=make_doc_id(path, source_hash),
        source_path=str(path.resolve()),
        format="pdf",
        title=title,
        text=full_text,
        units=units,
        unit_type="page",
        parse_method="pymupdf+ocr" if used_ocr else "pymupdf",
        metadata={
            "page_count": len(units),
            "size_bytes": path.stat().st_size,
            "source_hash": source_hash,
            "pdf_metadata": pdf_meta,
            "toc": toc,
            "content_start_page": content_start_page,
            "content_end_page": content_end_page,
            "low_density_pages": low_density_pages,
            "removed_vertical_blocks": removed_vertical,
            "removed_header_footer_blocks": removed_header_footer,
            "repeated_header_footer_strings": sorted(repeated_headers)[:20],
        },
        warnings=warnings,
    )


# ----------------------------- DOCX -----------------------------

def _parse_docx_fallback(path: Path) -> ParsedDocument:
    """Fallback when python-docx is unavailable: extract text with docx2txt."""
    try:
        import docx2txt  # type: ignore
    except ImportError as exc:
        raise ParseDependencyError(
            "python-docx (preferred) or docx2txt is required for DOCX parsing. "
            "Install one: pip install python-docx  # or: pip install docx2txt"
        ) from exc
    text = normalize_text(docx2txt.process(str(path)))
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    units = [{"index": i + 1, "text": b, "kind": "paragraph"} for i, b in enumerate(blocks)]
    source_hash = sha256_file(path)
    return ParsedDocument(
        doc_id=make_doc_id(path, source_hash),
        source_path=str(path.resolve()),
        format="docx",
        title=path.stem,
        text=text,
        units=units,
        unit_type="paragraph",
        parse_method="docx2txt",
        metadata={
            "size_bytes": path.stat().st_size,
            "source_hash": source_hash,
            "paragraph_count": len(units),
        },
        warnings=[
            "python-docx is not installed; docx2txt was used. "
            "Heading styles and table structure were not preserved."
        ],
    )


def parse_docx(path: Path) -> ParsedDocument:
    try:
        import docx  # type: ignore
        from docx.table import Table  # type: ignore
        from docx.text.paragraph import Paragraph  # type: ignore
        from docx.oxml.ns import qn  # type: ignore
    except ImportError:
        return _parse_docx_fallback(path)

    document = docx.Document(str(path))
    blocks: list[str] = []
    units: list[dict[str, Any]] = []
    warnings: list[str] = []

    def add_block(text: str, kind: str = "paragraph") -> None:
        text = normalize_text(text)
        if not text:
            return
        blocks.append(text)
        units.append({"index": len(units) + 1, "text": text, "kind": kind})

    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            if "heading" in style:
                # Preserve heading level for the chunker.
                level = 1
                for token in style.split():
                    if token.isdigit():
                        level = int(token)
                        break
                add_block(f"{'#' * min(level, 6)} {text}", kind="heading")
            else:
                add_block(text, kind="paragraph")
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows = []
            for row in table.rows:
                cells = [normalize_text(cell.text).replace("\n", " ") for cell in row.cells]
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                add_block("\n".join(rows), kind="table")
                warnings.append("A table was flattened to pipe-separated text; complex tables may need manual review.")

    full_text = normalize_text("\n\n".join(blocks))
    source_hash = sha256_file(path)
    core = getattr(document, "core_properties", None)
    title = path.stem
    if core is not None and getattr(core, "title", None):
        title = str(core.title).strip() or title

    return ParsedDocument(
        doc_id=make_doc_id(path, source_hash),
        source_path=str(path.resolve()),
        format="docx",
        title=title,
        text=full_text,
        units=units,
        unit_type="paragraph",
        parse_method="python-docx",
        metadata={
            "size_bytes": path.stat().st_size,
            "source_hash": source_hash,
            "paragraph_count": len(units),
        },
        warnings=warnings,
    )


# ----------------------------- DOC -----------------------------

def _find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def parse_doc(path: Path) -> ParsedDocument:
    """Convert legacy .doc to .docx, then parse. Requires LibreOffice or Word automation."""
    soffice = _find_soffice()
    if soffice:
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [soffice, "--headless", "--convert-to", "docx", "--outdir", tmp, str(path)]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=180)
            except Exception as exc:
                raise ParseDependencyError(
                    f"LibreOffice failed to convert {path.name}: {exc}"
                ) from exc
            converted = Path(tmp) / (path.stem + ".docx")
            if not converted.exists():
                raise ParseDependencyError(f"LibreOffice produced no docx for {path.name}")
            parsed = parse_docx(converted)
            original_hash = sha256_file(path)
            parsed.doc_id = make_doc_id(path, original_hash)
            parsed.source_path = str(path.resolve())
            parsed.format = "doc"
            parsed.parse_method = "libreoffice+python-docx"
            parsed.title = path.stem
            parsed.metadata["source_hash"] = original_hash
            parsed.metadata["original_source_hash"] = original_hash
            return parsed

    # Optional Windows Word automation.
    try:
        import win32com.client  # type: ignore

        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(str(path.resolve()))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / (path.stem + ".docx")
            doc.SaveAs2(str(out), FileFormat=16)  # wdFormatXMLDocument
            doc.Close(False)
            word.Quit()
            parsed = parse_docx(out)
            original_hash = sha256_file(path)
            parsed.doc_id = make_doc_id(path, original_hash)
            parsed.source_path = str(path.resolve())
            parsed.format = "doc"
            parsed.parse_method = "word-com+python-docx"
            parsed.title = path.stem
            parsed.metadata["source_hash"] = original_hash
            parsed.metadata["original_source_hash"] = original_hash
            return parsed
    except Exception:
        pass

    raise ParseDependencyError(
        "Legacy .doc requires LibreOffice (soffice) or Microsoft Word. "
        "Install LibreOffice, or convert the file to .docx before ingestion."
    )


# ----------------------------- TEXT -----------------------------

def _decode_bytes(raw: bytes, path: Path) -> tuple[str, str]:
    try:
        from charset_normalizer import from_bytes  # type: ignore

        best = from_bytes(raw).best()
        if best is not None:
            return str(best), best.encoding or "unknown"
    except Exception:
        pass
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def parse_text(path: Path) -> ParsedDocument:
    raw = path.read_bytes()
    text, encoding = _decode_bytes(raw, path)
    text = normalize_text(text)
    lines = text.splitlines()
    units = [{"index": i + 1, "text": line, "kind": "line"} for i, line in enumerate(lines)]
    source_hash = sha256_file(path)
    return ParsedDocument(
        doc_id=make_doc_id(path, source_hash),
        source_path=str(path.resolve()),
        format=path.suffix.lower().lstrip("."),
        title=path.stem,
        text=text,
        units=units,
        unit_type="line",
        parse_method=f"text({encoding})",
        metadata={
            "size_bytes": path.stat().st_size,
            "source_hash": source_hash,
            "encoding": encoding,
            "line_count": len(lines),
        },
        warnings=[],
    )


# ----------------------------- HTML -----------------------------

def parse_html(path: Path) -> ParsedDocument:
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError as exc:
        raise ParseDependencyError("beautifulsoup4 is required for HTML parsing: pip install beautifulsoup4") from exc

    raw = path.read_bytes()
    text, encoding = _decode_bytes(raw, path)
    soup = BeautifulSoup(text, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else path.stem
    blocks: list[str] = []
    units: list[dict[str, Any]] = []
    for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "pre", "blockquote"]):
        t = normalize_text(node.get_text(" ", strip=True))
        if not t:
            continue
        name = node.name
        if name.startswith("h") and len(name) == 2 and name[1].isdigit():
            blocks.append(f"{'#' * int(name[1])} {t}")
        elif name == "li":
            blocks.append(f"- {t}")
        elif name in {"td", "th"}:
            blocks.append(f"| {t} |")
        else:
            blocks.append(t)
        units.append({"index": len(units) + 1, "text": blocks[-1], "kind": name})
    full_text = normalize_text("\n\n".join(blocks))
    source_hash = sha256_file(path)
    return ParsedDocument(
        doc_id=make_doc_id(path, source_hash),
        source_path=str(path.resolve()),
        format=path.suffix.lower().lstrip("."),
        title=title,
        text=full_text,
        units=units,
        unit_type="block",
        parse_method="beautifulsoup",
        metadata={
            "size_bytes": path.stat().st_size,
            "source_hash": source_hash,
            "encoding": encoding,
            "block_count": len(units),
        },
        warnings=[],
    )
