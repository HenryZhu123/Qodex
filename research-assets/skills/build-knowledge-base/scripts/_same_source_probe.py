"""Measure similarity between two different extractions of the SAME pages.

PyMuPDF text vs MinerU OCR of the same 20 pages tells us the floor for
"same content, different source", which is what the >0.9 duplicate band must
catch without swallowing legitimate new editions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

SCRIPTS = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\skills\build-knowledge-base\scripts")
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\src")

import asyncio  # noqa: E402

from exam_checker.integrations.mineru_agent import MinerUAgentClient  # noqa: E402
from kb_registry import fingerprint_jaccard, normalize_text, term_fingerprint  # noqa: E402

PDF = Path(
    r"D:\Code\hku\LLM\hku_agent\research-assets\408exam\参考教材\数据结构（C语言版）（第2版） (严蔚敏 李冬梅 吴伟民) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
)
PAGES = (0, 19)


def pymupdf_text(path: Path, start: int, end: int) -> str:
    with fitz.open(path) as doc:
        return "\n".join(doc[i].get_text("text") for i in range(start, end + 1))


async def main() -> None:
    with fitz.open(PDF) as doc:
        part = fitz.open()
        part.insert_pdf(doc, from_page=PAGES[0], to_page=PAGES[1])
        tmp = Path(r"D:\Code\hku\LLM\kb_review\_same_source_probe.pdf")
        part.save(tmp)
        part.close()

    client = MinerUAgentClient("https://mineru.net/api/v1/agent")
    try:
        extracted = await client.parse_file(tmp.read_bytes(), tmp.name, is_ocr=True)
    finally:
        await client.close()

    text_a = pymupdf_text(PDF, *PAGES)
    text_b = extracted.markdown
    fp_a = term_fingerprint(text_a)
    fp_b = term_fingerprint(text_b)

    print(f"pymupdf_chars={len(normalize_text(text_a))} mineru_chars={len(normalize_text(text_b))}")
    print(f"same_pages_exact_hash_match={normalize_text(text_a) == normalize_text(text_b)}")
    print(f"top400_fingerprint_jaccard={fingerprint_jaccard(fp_a, fp_b):.4f}")


if __name__ == "__main__":
    asyncio.run(main())
