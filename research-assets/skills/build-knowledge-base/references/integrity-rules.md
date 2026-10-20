# Text integrity rules

The integrity sample answers one question: **is the parsed text clean enough to become evidence?** It does not prove the entire document is clean. Treat `pass` as permission to proceed, not as a guarantee.

## Sampling

- Default ratio: **10%**.
- Default unit: page for PDF, paragraph for DOCX, line for plain text, block for HTML.
- Default minimum: **5 units**. If 10% of a short document is fewer than 5 units, take 5.
- Selection: **random contiguous window(s)**, not random individual lines.
- Default seed: `42`; record it so the sample is reproducible.
- Default windows: `1`. Use more windows for heterogeneous documents.
- Always save the exact sampled text and the window ranges (`start_index`, `end_index`).

Why contiguous: random isolated lines hide layout problems. A contiguous window exposes page headers, footers, column order, table fragmentation, and OCR drift.

## Metrics and thresholds

| Metric | Meaning | Warn | Fail |
|---|---|---|---|
| `chars` | sample length | < 100 (short sample) | < 10 |
| `replacement_ratio` | `�` / total chars | > 0.1% | > 0.5% |
| `mojibake_hits` | known garbled patterns | >= 1 | >= 5 |
| `control_ratio` | control/format chars | > 0.5% | > 2% |
| `cjk_ratio` | CJK chars / non-space | < 5% for a Chinese doc | - |
| `symbol_ratio` | symbol/private-use chars | > 35% | - |
| `empty_line_ratio` | blank lines / all lines | > 55% | - |
| `avg_line_len` | average line length | < 10 chars (and > 20 lines) | - |
| `repeated_line_ratio` | duplicate non-empty lines | > 25% | - |
| `page_density` | chars per page (PDF) | < 80 | - |

Mojibake patterns include:

```text
锟斤拷  烫烫烫  屯屯屯  Ã  Â  â€  ï¿½  �  \x00
```

These are signals, not proof. Inspect the saved sample before deciding.

## Verdict semantics

- **pass**: no strong signal. Proceed to the chunk plan.
- **warn**: readable but suspicious. Proceed with a conservative plan (smaller target, more overlap) and a manual spot-check. Record the warning in the final report.
- **fail**: not safe to index. Stop. Repair the cause, keep the failed report, and re-run in a new run directory.

`warn` is not a failure. Do not silently "clean" a warn into a pass; document what was changed.

## Common causes and repairs

| Symptom | Likely cause | Repair |
|---|---|---|
| `�` or `锟斤拷` | wrong encoding / double decode | re-read with `gb18030`/`utf-8-sig`; confirm in the sample |
| Many control chars | binary/PDF stream decoded as text | re-parse with the correct parser; exclude the file |
| Very low CJK ratio in a Chinese doc | English-only page or wrong encoding | inspect sample; fix encoding or language detection |
| Low page density | scanned/image PDF | run OCR (`--ocr force`) and inspect OCR text |
| Repeated lines | running headers/footers | strip repeated header/footer lines before chunking |
| Many empty lines / fragmented lines | multi-column PDF or bad extraction | use a layout-aware parser or manual cleanup |
| Huge symbol ratio | formulas, tables, or garbage | inspect; preserve formulas but remove garbage |

## OCR rules

- `--ocr auto`: OCR only pages with fewer than 30 extracted characters.
- `--ocr force`: OCR every page; use only when the text layer is known bad.
- `--ocr off`: never OCR; a scanned PDF will produce low-density warnings and likely fail.
- OCR requires `pytesseract` and the Tesseract binary with the relevant language pack (`chi_sim`, `eng`).
- OCR text is never assumed clean. Run the 10% sample again after OCR.

## Limitations

- A 10% sample can miss a bad page. For long textbooks, sample additional windows in the middle and end.
- Repeated headers/footers are acceptable if they are stripped later; the repeated-line warning is not a hard failure.
- Formula-heavy pages may have a high symbol ratio without being corrupted. Inspect the sample.
- Language detection is heuristic. For mixed Chinese/English documents, use `mixed` and choose chunk sizes accordingly.

## Required report fields

Every integrity report must include:

- document title, `doc_id`, source path, format;
- unit type and total units;
- seed, requested ratio, actual ratio, window ranges;
- metrics table;
- verdict and reasons;
- recommended actions;
- sample preview or a path to the full sample.
