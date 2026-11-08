---
name: build-knowledge-base
description: Use when ingesting PDF, Word, HTML, or plain-text documents into a retrieval knowledge base. Covers format-specific parsing, a random contiguous 10% text-integrity sample, sample-driven chunk-plan selection, SQLite/FTS5 ingestion, and retrieval verification.
---

# Build Knowledge Base

Turn a folder of user documents into a reproducible, anchor-preserving knowledge base. The skill separates **parsing**, **integrity sampling**, **chunk planning**, **chunking**, and **ingestion** so a bad PDF or a bad encoding decision cannot silently poison the index.

All commands below assume the current directory is this skill directory (`hku_agent/skills/build-knowledge-base`). Scripts resolve their own imports, so `--input` and `--out` may be absolute paths. Replace `<file-or-dir>` and `<run-dir>` with real paths; do not paste the angle brackets into PowerShell.

## Required references

Read these before starting a run:

- [workflow.md](references/workflow.md): phases, gates, artifacts, and commands.
- [integrity-rules.md](references/integrity-rules.md): sampling method, metrics, verdict thresholds, and repair actions.
- [chunking-policy.md](references/chunking-policy.md): mode decision matrix, target sizes, and anti-patterns.
- [schemas.md](references/schemas.md): parsed document, chunk, SQLite, and report schemas.
- [reference-question-bank.md](references/reference-question-bank.md): 408 reference-question ingestion (exam papers + answer keys).
- [development-plan.md](references/development-plan.md): how to build, test, and extend the skill (for maintainers).

## Non-negotiable rules

1. **Never chunk raw bytes.** Parse first; every chunk must come from a parsed document with `doc_id`, `source_path`, and text units.
2. **The 10% sample is a gate, not a formality.** Randomly select a contiguous 10% of units (pages for PDF, paragraphs for DOCX, lines for plain text). Record the seed, unit indices, and sampled text. If 10% is fewer than 5 units, sample at least 5.
3. **Integrity failure stops the pipeline.** If the sample verdict is `fail`, do not chunk. Repair encoding/OCR/parsing, re-run, and keep the failed report as evidence.
4. **Chunking is sample-driven and explicit.** Write a `chunk_plan.json` with mode, target size, overlap, and rationale before producing chunks. Use the 10% sample for integrity and a cheap full-document line scan for structure (headings/questions/code); do not silently switch to fixed-size chunking.
5. **Every chunk keeps provenance.** Preserve `doc_id`, `source_path`, heading path, and page range. No anchor, no evidence.
6. **Ingestion is idempotent.** Re-running must replace the same `doc_id`/`chunk_id`, not duplicate them.

## Workflow

The default `run` command stops after **plan** so the integrity report and chunk plan can be reviewed before ingestion.

### Phase 0 — inventory

```bash
python scripts/kb_pipeline.py inventory --input <file-or-dir> --out <run-dir>
```

Lists supported files, hashes them, and writes `manifest.json` + `inventory_report.md`. Unsupported files are reported, not silently skipped.

### Phase 1 — parse

```bash
python scripts/kb_pipeline.py run --input <file-or-dir> --out <run-dir> --stop-after parse
```

Format-specific paths:

| Input | Parser | Notes |
|---|---|---|
| `.txt`, `.md`, `.rst`, `.csv` | encoding detection + line units | tries UTF-8, GB18030, UTF-16; records actual encoding |
| `.docx` | `python-docx` | preserves heading styles and tables as text; falls back to `docx2txt` with a warning if unavailable |
| `.doc` | LibreOffice/Word conversion, then DOCX parser | requires LibreOffice or Word |
| `.pdf` | PyMuPDF | preserves `[[PAGE:n]]` markers; removes vertical sidebars, page numbers, and repeated headers/footers; uses the PDF TOC to skip front/back matter by default; optional OCR fallback |
| `.html`, `.htm` | BeautifulSoup | headings/paragraphs/lists |

Use `--include-front-matter` if cover, preface, or index pages are required. Artifacts: `parsed/<doc_id>.json`, `parse_report.md`.

### Phase 2 — 10% sample and integrity check

```bash
python scripts/kb_pipeline.py run --input <file-or-dir> --out <run-dir> --stop-after sample
```

The sampler chooses random contiguous unit windows, default ratio `0.10`, seed `42`, `--sample-windows 1`, minimum 5 units. It writes:

- `samples/<doc_id>_sample.txt` — the exact sampled text;
- `samples/<doc_id>_integrity.json` — metrics + verdict;
- `integrity_report.md` — preview and recommended actions.

Verdicts: `pass`, `warn`, `fail`. Only `fail` blocks. `warn` proceeds with a conservative plan and manual spot-check.

### Phase 3 — chunk plan (approval gate)

```bash
python scripts/kb_pipeline.py run --input <file-or-dir> --out <run-dir> --stop-after plan
```

Writes `chunk_plans/<doc_id>.json` and `chunk_plan.md`. Review:

- mode: `hierarchical` / `paragraph` / `question` / `code`;
- target/max/min chars and overlap;
- evidence from the 10% sample and full-document structure scan.

If the automatic mode is wrong, override it:

```bash
python scripts/kb_pipeline.py run --input <file-or-dir> --out <run-dir> \
  --stop-after ingest --mode question
```

Add `--include-front-matter` if the PDF's cover/preface/index pages should remain in the knowledge base.

### Phase 4 — chunk

```bash
python scripts/kb_pipeline.py chunk --out <run-dir> [--mode hierarchical|paragraph|question|code]
```

Writes `chunks/<doc_id>.jsonl` and `chunks.jsonl`. Each chunk has `chunk_id`, `doc_id`, `content`, `char_count`, `chunk_type`, `heading_path`, `page_start`, `page_end`, and `content_hash`. Heading-only fragments smaller than `min_chars` are dropped. With `--mode auto`, existing `chunk_plans/*.json` are reused, so manual plan edits survive; an explicit `--mode` regenerates them.

### Phase 5 — ingest and verify

```bash
python scripts/kb_pipeline.py ingest --out <run-dir>
python scripts/kb_pipeline.py verify --out <run-dir>
```

Writes `kb.sqlite` (documents + chunks + FTS5), `ingest_report.json`, and `verification_report.md`. Verify with a real query:

```bash
python scripts/kb_pipeline.py query --db <run-dir>/kb.sqlite --q "操作系统的目标" --top-k 5
```

## One-shot run

```bash
python scripts/kb_pipeline.py run --input <file-or-dir> --out <run-dir> --stop-after ingest
```

Use this only after the integrity report and plan have been reviewed, or when the user explicitly accepts automatic decisions.

## Stop and report

Stop immediately and report to the user when:

- a document fails integrity (`verdict=fail`);
- parsing fails for a required format and no fallback exists;
- a chunk plan is blocked;
- the database contains zero chunks after ingestion;
- verification returns zero hits for every probe.

Report the phase reached, artifacts produced, document/chunk counts, verdicts, sample ranges, and the exact repair action needed.

## Completion rule

A run is complete only when:

1. every supported input has a parsed artifact;
2. every parsed document has a 10% integrity report with recorded seed and range;
3. every non-failed document has an explicit chunk plan;
4. `chunks.jsonl` and `kb.sqlite` exist and `documents`/`chunks` counts match;
5. `verification_report.md` shows at least one successful retrieval probe;
6. `run_state.json` shows `phase=done`.
