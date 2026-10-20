# Chunking policy

Chunking is a **decision**, not a default constant. Record the decision in `chunk_plans/<doc_id>.json` before producing chunks.

## Decision inputs

1. **Integrity verdict** from the random contiguous 10% sample.
2. **Sample metrics** (headings, questions, code lines, empty lines, line length).
3. **Full-document structure scan** (cheap line-level counts). This catches a sample that happened to miss headings; it is not a substitute for the integrity sample.
4. **Language**: `zh`, `en`, or `mixed`.
5. **Document metadata**: PDF TOC, DOCX heading styles, filename/title.
6. **User override**: `--mode hierarchical|paragraph|question|code`.

## Mode selection

| Mode | Choose when | Typical documents |
|---|---|---|
| `hierarchical` | full-doc heading count >= 3 | textbooks, manuals, structured reports |
| `paragraph` | no strong heading/question/code signal | articles, guidelines, prose |
| `question` | question count >= 8, or >= 5 with option/answer/blank signals | exam papers, question banks, workbooks |
| `code` | code-like line ratio > 15% | source code, code-heavy notes |

Priority: `question` > `code` > `hierarchical` > `paragraph`.

Do not choose `question` just because a document has numbered list items. Require at least one of:

- many question starts;
- option markers (`A.`, `B.`, ...);
- answer/explanation markers (`答案`, `解析`, `Answer`);
- blanks (`（ ）`, `( )`, `____`).

## Size policy

| Mode | Target chars | Max chars | Min chars | Overlap |
|---|---|---|---|---|
| `hierarchical` (zh) | 700 | 1540 | 210 | 100 |
| `hierarchical` (en) | 1200 | 2640 | 360 | 150 |
| `paragraph` (zh) | 700 | 1540 | 210 | 100 |
| `paragraph` (en) | 1200 | 2640 | 360 | 150 |
| `question` | 500 | 1500 | 120 | 0 |
| `code` | 1200 | 2400 | 200 | 0 |

If integrity is `warn`, reduce the target by 20% and keep overlap. If a document is dense with formulas/tables, prefer smaller chunks and preserve the original page anchor.

These are starting points, not laws. Adjust only with a recorded reason in the chunk plan.

## Hierarchical chunking

- Detect headings with:
  - Chinese: `第X章`, `X.Y`, `一、`, `（一）`;
  - English: `Chapter N`, `N.N`, `Appendix`;
  - Markdown: `#` through `######`.
- Maintain a heading stack (`chapter > section > subsection`).
- Start a new section at each heading.
- Include the heading text at the start of the section's first chunk.
- Store `heading_path` as an ordered list.
- Drop heading-only fragments smaller than `min_chars`.

## Paragraph chunking

- Split on blank lines.
- If no blank lines, group lines into paragraphs by sentence boundaries.
- Pack paragraphs up to `target_chars`, hard-stop at `max_chars`.
- Overlap by keeping the last paragraph when it is not huge.
- Do not split a paragraph unless it exceeds `max_chars`.

## Question chunking

- Start a new group at a question boundary:
  - `1.`, `2.`, `（1）`, `第1题`, etc.
- Keep stem, options, answer, and explanation together when they fit.
- If a question exceeds `max_chars`, split at option/paragraph boundaries, not mid-sentence.
- Preserve the question number in the chunk content.
- Store `chunk_type=question` so downstream consumers can filter.

## Code chunking

- Preserve indentation.
- Heading detection is disabled in code mode, so Python `#` comments are not mistaken for Markdown headings.
- Prefer blank-line/function/class boundaries.
- Do not split inside a function if it fits in `max_chars`.
- Use zero overlap; code duplication hurts retrieval.
- If a code block exceeds `max_chars`, split at blank lines and repeat the language/function header when known.

## Page anchors and content range

- PDF parsing inserts `[[PAGE:n]]`.
- The chunker tracks the current page per paragraph.
- Every chunk records `page_start` and `page_end`.
- If a chunk spans pages, keep the full range.
- For non-PDF inputs, page fields are `null`.
- For PDFs with a TOC, the parser records `content_start_page` (first chapter) and `content_end_page` (before back matter). The chunker skips paragraphs outside that range unless `--include-front-matter` is set.
- Skipping front matter is a default, not a silent deletion: the parsed JSON still contains all pages and the range is recorded in metadata.

## Heading paths

- Store as a list, not a joined string, in JSONL.
- SQLite stores a `" > "`-joined string for convenience.
- Include enough path to locate the chunk: book/chapter/section/subsection.
- Do not include the document title in every path unless it helps disambiguate.

## Anti-patterns

| Anti-pattern | Why it hurts |
|---|---|
| Fixed 500-character windows for everything | splits definitions, formulas, and questions |
| Chunking before the 10% integrity check | silently indexes garbled text |
| Heading-only chunks | zero retrieval value, wastes index slots |
| Dropping page numbers | no citation, no evidence anchor |
| Mixing textbook facts and exam questions in one index | exam questions are samples, not subject facts |
| Using prediction/mock questions as ground truth | unverified and often wrong |
| Duplicate chunks after re-ingest | inflated index and duplicate retrieval |
| Overlap larger than 30% of target | near-duplicate chunks dominate top-k |

## Quality checks after chunking

1. Count chunks per document; zero is a failure.
2. Check min/avg/max chars; extreme outliers need review.
3. Check empty or heading-only chunks; should be zero.
4. Check duplicate `content_hash`; exact duplicates should be removed or explained.
5. Check page coverage for PDFs; large gaps may indicate parse loss.
6. Check heading coverage; a textbook with zero heading paths is suspicious.
7. Run 3–5 queries after ingestion; at least one must hit.

## Overrides

The automatic decision is a recommendation. Override it when:

- the document is an exam paper but the question threshold was missed;
- the document is a textbook but the sample missed headings;
- the document is code-heavy but the code ratio was diluted by prose;
- the user explicitly requests a mode.

Record the override in `chunk_plan.json` and the final report.
