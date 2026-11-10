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
- [knowledge-relations.md](references/knowledge-relations.md): when a second source covers the same subject, how chunks are merged, kept, related, or flagged as conflicts.
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
7. **Never drop or silently merge content from a second source.** When a new source covers a subject that already has content, decide every overlapping chunk pair as `equivalent` / `exclusive` / `conflict` / `complementary` per [knowledge-relations.md](references/knowledge-relations.md). Conflicts are judged first, kept on both sides, and shared via `conflict_group_id`; retrieval must return all sides. A whole-book hash match is only a fast path — it still records the new source in `source_versions`.

## Tests

Run the suite after touching `chunker.py`, `store.py`, `registry.py`, `utils.py` or `textclean.py`:

```bash
python -m pytest tests/ -q -p no:cacheprovider        # 140 cases, ~10 s
python tests/_mutation_check.py                        # 14 mutations, ~50 s
```

`-p no:cacheprovider` avoids a sandbox warning about the cache directory.

### The five layers, and why each one exists

| Layer | Example | What it catches that the layer below misses |
| --- | --- | --- |
| Predicate | `_looks_like_title`, `is_stub`, `detect_heading_level` | Wrong classification of a single line |
| Consumer | `build_sections`, `chunk_document` | The predicate is right but the wiring is wrong — heading nesting, neighbour replacement |
| Data contract | `insert_chunks` vs `chunks_fts`, `rebuild_fts` | Rows stored but not indexed, stale index after re-ingest |
| Idempotency / determinism | same input twice → same hashes | Silent duplication, order-dependent output |
| End to end | text or PDF → queryable index | A phase that never runs, a flag that is ignored |

The first pass of this suite tested only predicates. `build_sections` — the function that actually builds `heading_path` — had no coverage at all, and a size test passed with `max_chars` multiplied by ten because the fixture never approached the limit. Both gaps were found by mutation testing, not by reading the tests.

### Mutation testing is the real check

A test that passes with and without the fix is not a test. `tests/_mutation_check.py` breaks each fix in turn and asserts the suite goes red:

```
CAUGHT   heading gate disabled        11 failed
CAUGHT   fragment filter disabled      6 failed
CAUGHT   packing ignores max_chars     1 failed
...
```

Two lessons that cost real time:

- **A mutation can be a no-op.** Changing `sha256(content)` to `sha256(content + len*7)` is still deterministic, and a comment-only edit changes nothing; both report `NOT CAUGHT` while the test is fine. When a mutation escapes, decide first whether the test is too loose or the mutation too weak.
- **A passing suite is not evidence of coverage.** The 1,600-character chunks that reached production passed every test because no fixture was that large.

When a test fails, decide which side is wrong before editing either: `test_heading_gate.py` encodes cases lifted from the real corpus, while `test_tokenizer.py` documents deliberate choices such as punctuation-insensitive hashing for OCR drift.

### Golden counts belong in the gate, not in the docs

Per-book chunk counts change whenever chunking changes, so they live in `run_quality_gate.py` and are compared with a tolerance. Do not write them into prose; it goes stale within one rebuild. And derive the rebuild list from the filesystem (`rglob("kb*.sqlite")`), never from a hardcoded list — a hardcoded list that omitted one book let its 1,768-character chunks survive three rebuilds unnoticed.

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

#### Heading detection is a quality gate, not a heuristic

Three defects shipped in the 2026.11 indexes and are now blocked in code. Check any new build against all three.

**Defect 1 — body lines became headings.** The old rule accepted any line starting with digits, so `100 个数据中心分布于…`, `1110 1101 1100 1011…` and `1 /* 定义并声明一个信号量 */` all became `heading_path`. 902 of 2,698 chunks (33%) carried such a segment, worst in 计组 (440/625) and 计网 (306/1,061).

Fix: `chunker._looks_like_title()` rejects a candidate that is longer than 48 chars, contains `。；！？，：`, contains code markers (`/*`, `//`, `#include`, `wake_up`), is all-binary, or is all digits. All heading rules — chapter, numbered, markdown `#` — run through it.

**Defect 2 — short fragments outranked real content.** A chunk holding `虚拟存储器` or `26` scores well in BM25 precisely because it is short. 158 fragments sat in the index.

Fix: `store.is_stub()` treats a chunk under 120 chars without `。；！？` as a fragment. The row stays in `chunks` (so nothing is lost) but is skipped in `chunks_fts`, so it can never be returned as evidence. Ingest logs the count.

**Defect 3 — headings were indexed twice.** 46% of chunks open with their own heading line, so heading words got double weight.

Fix: `store.strip_leading_heading()` removes the leading line when it equals the last heading segment, and the FTS tokens come from the body only. Stored `content` keeps the heading for context.

Verified by rebuilding all indexes from the parsed artefacts: bad heading segments 902 → 0, chunk count 2,698 → 2,556, of which 2,399 are indexed (157 fragments kept but not indexed). The retrieval set was re-labelled by hand afterwards; the strict numbers are in the evaluation report, not here, because they move with the corpus.

#### Two ways a correct chunker still ships bad chunks

**A giant "sentence".** Splitting on sentence punctuation assumes sentences are short. A table row or a code line can be 2,000 characters with no punctuation at all, so the split never fires and the chunk exceeds `max_chars`. Split any over-long sentence by characters before packing (`chunker._split_large_paragraph`).

**The overlap top-up.** After `emit()`, the last paragraph is kept so the next chunk starts with context. The old loop appended the next paragraph without re-checking the limit, producing chunks of `max_chars + overlap` — 20 chunks of 1,600–1,773 characters in the network book. Always re-check capacity after `emit()`, and assert `max(char_count) <= max_chars` in a test whose fixture actually reaches the limit.

#### Rebuild paths must reuse the ingest rules

`store.rebuild_fts()` reconstructs the index from `chunks`. Written naively it skips the fragment filter and the heading strip, so **one rebuild silently undoes both fixes**: fragments become searchable again and headings get double weight, with nothing in the report to show it. Any function that can recreate index state must call the same helpers as ingest, and a test must assert the two paths agree.

The same rule applies to a tokenizer or alias change: use `reindex`, which rebuilds FTS from stored chunks without touching content.

### Phase 5 — ingest and verify

```bash
python scripts/kb_pipeline.py ingest --out <run-dir>
python scripts/kb_pipeline.py verify --out <run-dir>
```

Writes `kb.sqlite` (documents + chunks + FTS5), `ingest_report.json`, and `verification_report.md`. Verify with a real query:

```bash
python scripts/kb_pipeline.py query --db <run-dir>/kb.sqlite --q "操作系统的目标" --top-k 5
```

Then run the quality gate. It is the acceptance step, not an optional extra:

```bash
python scripts/run_quality_gate.py            # six gates, exits non-zero on failure
python scripts/run_quality_gate.py --skip-retrieval   # structural gates only, ~5 s
```

| Gate | Checks | Failure means |
| --- | --- | --- |
| G1 index consistency | `chunks_fts` rows == `chunks` minus fragments | A rebuild path drifted, or rows were lost |
| G2 heading hygiene | No body line, binary row or code line as a heading segment | The title gate regressed |
| G3 heading duplication | Token stream does not start with the title | The heading strip stopped applying |
| G4 text hygiene | Mojibake and running-watermark leakage | OCR cleaning regressed |
| G5 coverage | Per-book chunk counts within 5% of golden | A book was skipped or chunking changed |
| G6 retrieval quality | recall@2 above the floor | Ranking or the corpus changed materially |

When only the tokenizer changed, rebuild the index without touching content:

```bash
python scripts/kb_pipeline.py reindex --db <db> [--db <db> ...]
```

## Cleaning rules: three tiers

Cleaning rules go wrong in the same way every time — someone writes a plausible substitution and applies it to the whole corpus. Sort every rule into one of three tiers before writing code.

**Tier 1 — shape-unique, apply automatically.** The replacement is either impossible in legitimate text or a fixed collocation.

| Rule | Why it is safe |
| --- | --- |
| 千→于 in 对千 / 由千 / 关千 / 千是 / 千此 / 千其 | Those bigrams are not words; 千 is a number elsewhere |
| 巳→已 in 巳经 / 巳有 / 而巳 | 巳 is a zodiac character, never these words |
| 阙值 / 阔值 → 阈值 | The term is always 阈值 |
| ｀ ｢ ｣ → delete | Half-width marks never belong in Chinese prose |
| `<!--…-->`, `&lt;` → delete / unescape | Markup leaked from the converter |
| Bullet runs (••••) → delete | Figure remnants |

Applied to this corpus: 553 substitutions, verified zero residual afterwards. **千 appears 519 times; only 140 were wrong.** A blanket 千→于 would have corrupted 以千计, 成千上, 数千个.

**Tier 2 — context-dependent, guard + sample first.** The rule is right in prose and wrong in code or formulas.

- `l`→`1` between digits (`20l6` → `2016`) or before two or more digits (`l00KB` → `100KB`): skip chunks that look like code (`#include`, `for(`, `int x`, `;`, `{`).
- `2Oxx` → `20xx`: years only, never `0NT`→`ONT`, which is the opposite direction and needs a whitelist.
- Leading numbers: strip only when at least three lines share the shape **and** most of them carry code punctuation. Plain tables also start with numbers.

A rule that looks obvious can still be wrong: `2l/R` in "总时延是2l/R" is 2·L/R, where L is the packet length. Replacing it produced `21/R`. That rule was written, sampled, and deleted. **Every Tier 2 rule needs a dry run and a sample read before it lands.**

**Tier 3 — never automated.**

- English names glued by OCR (`JamesF.Kurose`): do not insert spaces, because `TCP/IP` and `IEEE802.11` must not be split. Index a joined alias token instead (see `utils.english_aliases`). Even then, an OR-matched query is often outranked by a common token such as `f`; the alias fixes reachability, not ranking.
- Sentence-level errors (`图5.23` embedded mid-sentence): no reliable detector. Mark as a known blind spot rather than pretending coverage.

### Dry run before you apply

Any cleaning pass over a built index must print the before/after pairs first:

```bash
python scripts/textclean.py repair --db <db>            # dry run: counts + samples
python scripts/textclean.py repair --db <db> --apply    # writes, rehashes, reindexes
```

Read the samples. In this corpus the sample read is what caught the `2l/R` error; the counts alone looked correct.

## OCR-sourced documents (MinerU, scanned PDFs)

A text-layer PDF and an OCR pipeline fail differently, so they need separate gates. In this corpus the 8th edition came through MinerU while the other four were text-layer, and every defect below was unique to the OCR path.

| Symptom | Cause | Fix |
| --- | --- | --- |
| Every `heading_path` is empty | MinerU emits blocks, not a section tree | Track the most recent **section-shaped** markdown heading (`第N章`, `1.2`) and assign it to following blocks |
| Cover and copyright pages in the index | The scan starts at the cover | Skip blocks matching 原书第8版 / ISBN / 防伪标签 / 图书在版编目 until the first section heading appears |
| A 5,515-character chunk | MinerU returns whole blocks | Split to `max_chars` on blank lines, then lines, then characters |
| Headings that are not headings | A cover carries `# <book title>` | Accept only section-shaped headings; a bare title must not satisfy the "we have seen a heading" test |

Ordering matters: check the front-matter pattern **before** treating a `#` line as a heading. Written the other way round, the cover's own title defeats the gate and the cover stays in the index — which is exactly what happened on the first attempt.

Result on this edition: 207 blocks with no anchors and 5 cover pages → 204 chunks, all anchored (40 distinct headings), longest chunk 1,200, zero cover pages.

Page numbers from MinerU are per-volume, not per-page. Record them, but do not present them as precise citations.

## Evaluation caliber

Two numbers can describe the same system and differ by five points, purely because of how "a hit" is defined.

| Caliber | Definition | This corpus |
| --- | --- | ---: |
| Rank-inferred | The chunk at rank 1 counts as a hit | recall@2 86.25% |
| Hand-judged | Each candidate read; only one that answers the query counts | recall@2 81.82% |

Rules that follow from this:

1. **Publish one caliber and name it.** A reviewer cannot compare 86% (rank-inferred) with 81% (hand-judged) and conclude anything.
2. **Store labels by query id and rank, not by chunk id.** Then a rebuild that preserves boundaries keeps the labels valid.
3. **Verify boundary stability after any rebuild.** Snapshot `chunk_id → content hash` before and after; if ids moved, the old labels point at different text and must be re-judged. This corpus: 0 id drift, 16 chunks changed content, labels still valid.
4. **Report misses with a cause**: content gap, wrong-book routing, or a document-quality problem. Only the last one is a build defect; the first needs more books, and no amount of tuning fixes it.

## One-shot run

```bash
python scripts/kb_pipeline.py run --input <file-or-dir> --out <run-dir> --stop-after ingest
```

Use this only after the integrity report and plan have been reviewed, or when the user explicitly accepts automatic decisions.

### Phase 6 — multi-source alignment (required when the subject already has content)

Only applies when the target subject is not empty. Skip it for the first book of a subject.

1. Generate candidate pairs deterministically: same subject, high term-fingerprint overlap or
   high character-trigram containment. Cast wide; this stage may over-produce.
2. Judge every candidate pair into exactly one of `equivalent` / `exclusive` / `conflict` /
   `complementary`, **conflicts first**. Record the reason.
3. Every `conflict` goes to human review before it is written. A missed conflict is the worst
   failure mode: the model will blend two incompatible answers into one.
4. Write relation metadata per [knowledge-relations.md](references/knowledge-relations.md):
   `canonical_id`, `source`, `source_versions`, `relation`, plus `conflict_group_id` /
   `conflict_stance` for conflicts and `related_to` for complementary pairs.
5. Emit the delta as its own file (`delta/<doc_id>.jsonl`) plus a report of counts per relation.
   Do not merge into the existing `kb.sqlite` without an explicit decision; the delta file keeps
   the merge reversible.
6. Retrieval must return every member of a `conflict_group_id` together and label each side by
   source. Never let similarity ranking silently pick one side.

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
6. `run_state.json` shows `phase=done`;
7. for a subject that already had content, every overlapping candidate pair carries a relation
   label, every conflict is human-reviewed, and the delta report lists counts per relation.
