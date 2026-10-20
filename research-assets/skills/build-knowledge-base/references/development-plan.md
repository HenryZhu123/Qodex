# Development plan

This document is for the engineer maintaining or extending the skill. The runtime workflow is in `workflow.md`; this file explains how to build, test, and ship the skill itself.

## 1. Scope

Build a self-contained skill that turns a folder of user documents into a knowledge base:

- **Inputs**: PDF, DOCX, DOC, TXT/MD/CSV, HTML.
- **Normalized intermediate**: one JSON per document with text, units, metadata, warnings.
- **Quality gate**: random contiguous 10% integrity sample per document.
- **Chunking**: sample-driven plan + structure-aware chunks with anchors.
- **Storage**: SQLite + FTS5 + JSONL export.
- **Verification**: counts and retrieval probes.

Out of scope for v1:

- embedding/vector index (the SQLite schema and chunk JSONL are ready for it);
- OCR model download/management (pytesseract adapter is present, but the binary is external);
- automatic web crawling;
- question-answer quality judgment.

## 2. Architecture

```text
cli (kb_pipeline.py)
  ├─ inventory        -> manifest.json
  ├─ parse            -> parsed/<doc_id>.json
  ├─ sample           -> samples/*_integrity.json + integrity_report.md
  ├─ plan             -> chunk_plans/<doc_id>.json + chunk_plan.md
  ├─ chunk            -> chunks/<doc_id>.jsonl + chunks.jsonl
  ├─ ingest           -> kb.sqlite
  └─ verify/query     -> verification_report.*
```

Module boundaries:

| Module | Responsibility | Must not do |
|---|---|---|
| `parsers.py` | format-specific extraction, unit model, PDF cleaning, OCR fallback | chunking, scoring |
| `integrity.py` | contiguous sampling, metrics, verdict | reading the whole document again for structure |
| `chunker.py` | plan selection, heading/question/code detection, packing | parsing bytes, writing SQLite |
| `store.py` | schema, idempotent upsert, FTS5 tokenization, query | parsing, chunk-policy decisions |
| `kb_pipeline.py` | phase orchestration, reports, state | format-specific hacks |

## 3. Build order

### Milestone 1 — contract and fixtures

1. Freeze the JSON contracts in `schemas.md`.
2. Create fixtures:
   - `good.txt` (Chinese headings + paragraphs);
   - `bad_encoding.txt` (mojibake);
   - `exam.txt` (numbered questions + options + answers);
   - `sample.docx` (headings + table);
   - `sample.pdf` (text layer + vertical sidebar + page numbers);
   - `scanned.pdf` (image-only, if OCR is in scope).
3. Decide the unit type per format: page / paragraph / line / block.

Acceptance: every fixture parses into the same `ParsedDocument` shape.

### Milestone 2 — parsers

1. Implement TXT/MD encoding detection and line units.
2. Implement DOCX with ordered body traversal; fallback to `docx2txt`.
3. Implement DOC with LibreOffice/Word conversion; fail clearly if unavailable.
4. Implement PDF with `[[PAGE:n]]`, block cleaning, TOC content range, OCR fallback.
5. Implement HTML with BeautifulSoup.
6. Sanitize surrogates in all strings before JSON/SQLite writes.

Acceptance: parse report shows method, warnings, unit counts; no Unicode crash on malformed PDF metadata.

### Milestone 3 — integrity gate

1. Implement contiguous sampling with seed and minimum units.
2. Implement metrics and thresholds from `integrity-rules.md`.
3. Write sample text, JSON, and Markdown report.
4. Return exit code 2 on `fail`.

Acceptance: `bad_encoding.txt` fails; `good.txt` passes; `sample.pdf` reports low density if OCR is off.

### Milestone 4 — chunk plan and chunker

1. Implement full-document structure scan (headings/questions/code).
2. Implement mode selection and size policy.
3. Implement heading stack, paragraph packing, question grouping, code packing.
4. Implement page anchors and front-matter filtering.
5. Drop empty/heading-only chunks; keep `content_hash`.

Acceptance: an exam fixture produces one chunk per question; a textbook fixture preserves chapter/section paths; no chunk starts with a lone page number.

### Milestone 5 — storage

1. Create documents/chunks/FTS5 schema.
2. Implement tokenization: jieba when available, CJK unigrams+bigrams otherwise.
3. Implement idempotent re-ingest: delete existing doc chunks before insert.
4. Implement FTS query and verification probes.

Acceptance: re-running `ingest` twice produces the same counts; a query for a known heading returns the expected chunk.

### Milestone 6 — CLI and reports

1. Implement `inventory`, `parse`, `sample`, `plan`, `chunk`, `ingest`, `verify`, `query`.
2. Implement `run --stop-after` gates.
3. Write `run_state.json`, `parse_report.md`, `integrity_report.md`, `chunk_plan.md`, `chunk_report.md`, `verification_report.md`.
4. Add `smoke_test.py`.

Acceptance: `python scripts/smoke_test.py` passes; `run --stop-after plan` stops before chunking.

### Milestone 7 — agent integration

1. Add the skill to the agent's skill registry.
2. The agent reads `SKILL.md`, runs the phases, and stops at the plan gate.
3. Map the user's intent to `--mode` and `--include-front-matter` overrides.
4. Expose `query` as a tool if the agent needs retrieval.

Acceptance: a user can point the agent at a folder and receive `chunk_plan.md` + `integrity_report.md` before any ingestion.

## 4. Test matrix

| Fixture | Expected |
|---|---|
| Chinese TXT with headings | hierarchical plan, heading paths, page null |
| English TXT with headings | hierarchical/paragraph, target ~1200 |
| Exam TXT | question plan, one chunk per question |
| DOCX with headings/tables | heading paths, table text preserved |
| DOCX without python-docx | docx2txt fallback + warning |
| Text PDF | page anchors, vertical sidebar removed, front matter skipped |
| Scanned PDF, OCR off | low-density warning, likely fail |
| PDF with malformed TOC | parse succeeds, surrogates sanitized |
| Mojibake TXT | integrity fail, exit 2, no chunks |
| Empty file | parse warning/fail, no crash |

## 5. Quality gates

Before calling the skill done:

- `python -m py_compile scripts/*.py` passes.
- `python scripts/smoke_test.py` passes.
- `run --stop-after plan` produces both reports.
- `run --stop-after ingest` produces `kb.sqlite` and a verification hit.
- Re-running `ingest` does not increase chunk count.
- A real textbook PDF produces chunks with page ranges and no cover/preface chunks by default.
- A malformed PDF does not crash on surrogates.

## 6. Extension points

- **Embeddings**: add `scripts/embed.py` that reads `chunks.jsonl`, writes `embeddings.npy` + `chunk_ids.json`, and a `--vector` query path. Keep FTS as the default.
- **OCR**: add PaddleOCR or a vision model adapter behind `_ocr_page`.
- **Tables**: use `pdfplumber`/Camelot for table extraction and store tables as separate chunks with `chunk_type=table`.
- **Formulas**: add LaTeX normalization and a formula-signature index.
- **New formats**: add a parser returning `ParsedDocument`; no CLI change needed.
- **Vector DB**: migrate `store.py` to Qdrant/PostgreSQL only when concurrency or scale requires it.

## 7. Risks

| Risk | Mitigation |
|---|---|
| PDF extraction noise (headers, vertical text) | block-level cleaning + repeated-line removal + sample review |
| 10% sample misses a bad region | support multiple windows; record seed; additional spot checks |
| DOCX library unavailable | docx2txt fallback with warning |
| OCR not installed | fail with a clear message; do not pretend scanned PDF is parsed |
| Surrogates in PDF metadata | sanitize all JSON/SQLite writes |
| Chunk explosion on exam papers | question mode; target 500, max 1500 |
| Stale chunks after re-ingest | delete by `doc_id` before insert |
| Agent overrides chunk mode incorrectly | record override in plan and report |
