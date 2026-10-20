# Workflow

Create one run directory per ingestion task. Never mix two runs in one directory. A run is identified by `run_state.json`.

## Run directory

```text
<run-dir>/
├── run_state.json
├── manifest.json
├── inventory_report.md
├── parsed/
│   └── <doc_id>.json
├── parse_report.md
├── samples/
│   ├── <doc_id>_sample.txt
│   └── <doc_id>_integrity.json
├── integrity_report.md
├── chunk_plans/
│   └── <doc_id>.json
├── chunk_plan.md
├── chunk_plan.json            # aggregate
├── chunks/
│   └── <doc_id>.jsonl
├── chunks.jsonl               # aggregate
├── chunk_report.md
├── ingest_report.json
├── verification_report.json
├── verification_report.md
└── kb.sqlite
```

## Phase boundaries

### Phase 0 — inventory

Command:

```bash
python scripts/kb_pipeline.py inventory --input <input> --out <run-dir>
```

Actions:

1. Enumerate every file under the input root, excluding the run output directory (so a run created inside the input root cannot ingest itself).
2. Classify by extension. Supported: `.pdf`, `.docx`, `.doc`, `.txt`, `.md`, `.markdown`, `.rst`, `.csv`, `.tsv`, `.log`, `.html`, `.htm`.
3. Compute a SHA-256 hash and a stable `doc_id`.
4. Write `manifest.json` and `inventory_report.md`.
5. List unsupported files; do not silently drop them.

Report: number of supported/unsupported files, formats, sizes, and any file that needs conversion.

### Phase 1 — parse

Command:

```bash
python scripts/kb_pipeline.py run --input <input> --out <run-dir> --stop-after parse
```

Actions per format:

- **PDF**: PyMuPDF text extraction. Insert `[[PAGE:n]]` markers. Remove vertical sidebar text, page numbers, and repeated header/footer blocks. Use the PDF TOC to identify the first chapter and the back-matter boundary; skip front/back matter by default (`--include-front-matter` keeps it). If a page has fewer than 30 characters, try OCR (`pytesseract`) when `--ocr auto|force`. Record low-density pages. Never claim a scanned PDF is parsed if OCR is unavailable.
- **DOCX**: `python-docx`. Traverse body children in order, preserve heading levels, flatten tables to pipe-separated text. Warn about complex tables.
- **DOC**: convert with LibreOffice (`soffice --headless --convert-to docx`) or Word COM, then parse as DOCX. If neither exists, fail with a conversion instruction.
- **TXT/MD/CSV**: detect encoding with `charset-normalizer`, then fall back to UTF-8, GB18030, UTF-16. Record the actual encoding.
- **HTML**: BeautifulSoup; strip scripts/styles; preserve headings, paragraphs, list items, and table cells.

Output `parsed/<doc_id>.json` contains:

- full normalized `text`;
- ordered `units` (page/paragraph/line/block);
- `unit_type`, `language`, `char_count`, `unit_count`;
- `parse_method`, `metadata`, `warnings`.

Report: parsed/failed counts, method used, warnings, and any document that needs OCR or conversion.

### Phase 2 — 10% integrity sample

Command:

```bash
python scripts/kb_pipeline.py run --input <input> --out <run-dir> --stop-after sample
```

Algorithm:

1. Unit type: `page` for PDF, `paragraph` for DOCX, `line` for plain text, `block` for HTML.
2. `sample_count = max(round(total_units * ratio), min_units)`, capped at `total_units`.
3. Default `ratio=0.10`, `min_units=5`, `seed=42`, `windows=1`.
4. For one window, choose a random start uniformly and take `sample_count` contiguous units.
5. For multiple windows, choose non-overlapping contiguous windows and merge them.
6. Save the exact sampled text, the window ranges, the seed, and the requested/actual ratio.

Integrity checks:

- replacement-character ratio;
- mojibake patterns;
- control-character ratio;
- CJK ratio vs detected language;
- symbol ratio;
- empty-line ratio and average line length;
- repeated-line ratio (headers/footers);
- heading/question/code line counts;
- PDF page text density.

Verdicts:

- `pass`: proceed.
- `warn`: proceed with a conservative chunk plan and manual spot-check.
- `fail`: stop. Repair encoding/OCR/parser, then re-run. Do not chunk a failed document.

A 10% sample is a spot check, not proof of full-document quality. For heterogeneous documents (mixed scanned/text pages, multiple columns, tables), run additional windows with a different seed and record why.

Report: sample range(s), seed, verdict, metrics table, preview, and recommended actions.

### Phase 3 — chunk plan (approval gate)

Command:

```bash
python scripts/kb_pipeline.py run --input <input> --out <run-dir> --stop-after plan
```

The planner combines:

- integrity verdict and sample metrics (10%);
- a cheap full-document line scan for headings/questions/code;
- language and document metadata.

It chooses one mode:

- `hierarchical`: headings >= 3; textbooks, manuals, structured reports.
- `paragraph`: no strong structure; prose, guidelines, articles.
- `question`: question count >= 8, or >= 5 with strong option/answer/blank signals; exam papers, question banks.
- `code`: code-like line ratio > 15%; source code or code-heavy notes.

It chooses target/max/min chars and overlap. Write `chunk_plans/<doc_id>.json` and `chunk_plan.md`.

Gate: show the plan to the user/agent. If the mode is wrong, override with `--mode hierarchical|paragraph|question|code`. Do not proceed to chunking without an explicit plan.

### Phase 4 — chunk

Command:

```bash
python scripts/kb_pipeline.py chunk --out <run-dir> [--mode ...]
```

When `--mode auto` is used, `chunk` reuses existing `chunk_plans/<doc_id>.json` files. This allows manual size/mode edits after the plan gate without the plan being overwritten. Passing an explicit `--mode` regenerates the plans.

Rules:

- split by the document's own structure, not fixed offsets;
- keep heading paths;
- keep page ranges when `[[PAGE:n]]` markers exist;
- skip PDF front/back matter using the TOC range unless `--include-front-matter` is set;
- drop empty and heading-only fragments;
- never split a formula/table/code block if it fits in the max size;
- for question mode, keep stem + options + answer + explanation together when possible.

Output: `chunks/<doc_id>.jsonl`, `chunks.jsonl`, `chunk_report.md`.

Report: chunk count, min/avg/max chars, chunk types, first-chunk preview, and any document with zero chunks.

### Phase 5 — ingest and verify

Commands:

```bash
python scripts/kb_pipeline.py ingest --out <run-dir>
python scripts/kb_pipeline.py verify --out <run-dir>
```

Ingestion:

1. Open/create `kb.sqlite`.
2. Insert/replace `documents` by `doc_id`.
3. Insert/replace `chunks` by `chunk_id`.
4. Rebuild/refresh FTS5 rows for those chunks.
5. Export `chunks.jsonl` for portability.

Verification:

- document/chunk counts;
- total and average chars;
- 3–5 probes built from existing chunks;
- at least one probe must return a hit;
- manual query example with `query`.

Report: stats, probe table, and any zero-hit condition.

## Stop conditions

Stop and ask the user before continuing when:

- integrity verdict is `fail`;
- a required format has no working parser;
- chunk plan is blocked;
- the user has not approved the chunk plan (default `--stop-after plan`);
- ingestion produces zero chunks;
- all verification probes return zero hits.

## Resume

The pipeline is file-based. Re-running a phase overwrites its own artifacts. Keep the failed run directory as evidence; create a new run directory for the repaired attempt. Do not edit `parsed/*.json` by hand unless the repair itself is recorded.
