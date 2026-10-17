# Artifact schemas

All JSON is UTF-8 and uses `ensure_ascii=false`.

## `manifest.json`

```json
{
  "run_id": "20261017-211500-0421",
  "input_root": "D:\\data\\books",
  "output_dir": "D:\\runs\\books-20261017",
  "created_at": "2026-10-17T21:15:00+08:00",
  "documents": [
    {
      "doc_id": "a1b2c3d4e5f60718",
      "source_path": "D:\\data\\books\\os.pdf",
      "relative_path": "os.pdf",
      "format": "pdf",
      "size_bytes": 28264243,
      "size_human": "27.0 MB",
      "source_hash": "sha256..."
    }
  ],
  "unsupported": [
    {"path": "D:\\data\\books\\cover.psd", "suffix": ".psd", "size_bytes": 12345}
  ],
  "supported_extensions": [".pdf", ".docx", ".doc", ".txt", ".md"]
}
```

## `parsed/<doc_id>.json`

```json
{
  "doc_id": "a1b2c3d4e5f60718",
  "source_path": "D:\\data\\books\\os.pdf",
  "format": "pdf",
  "title": "计算机操作系统",
  "text": "[[PAGE:1]]\n第1章 ...",
  "units": [
    {"index": 1, "page": 1, "text": "第1章 ..."}
  ],
  "unit_type": "page",
  "parse_method": "pymupdf",
  "metadata": {
    "page_count": 410,
    "size_bytes": 28264243,
    "source_hash": "sha256...",
    "pdf_metadata": {},
    "toc": [],
    "content_start_page": 22,
    "content_end_page": 410,
    "low_density_pages": [],
    "removed_vertical_blocks": 120,
    "removed_header_footer_blocks": 240
  },
  "warnings": [],
  "language": "zh",
  "char_count": 478601,
  "unit_count": 410,
  "created_at": "2026-10-17T21:15:00+08:00"
}
```

`unit_type` is one of `page`, `paragraph`, `line`, `block`.

## `samples/<doc_id>_integrity.json`

```json
{
  "doc_id": "a1b2c3d4e5f60718",
  "source_path": "D:\\data\\books\\os.pdf",
  "title": "计算机操作系统",
  "unit_type": "page",
  "sample": {
    "seed": 42,
    "total_units": 410,
    "sample_units": 41,
    "ratio_requested": 0.1,
    "ratio_actual": 0.1,
    "min_units": 5,
    "windows": [
      {"start_index": 101, "end_index": 142, "unit_count": 41}
    ]
  },
  "metrics": {
    "chars": 98000,
    "lines": 4200,
    "replacement_chars": 0,
    "replacement_ratio": 0.0,
    "control_chars": 0,
    "control_ratio": 0.0,
    "mojibake_hits": 0,
    "cjk_ratio": 0.71,
    "latin_ratio": 0.18,
    "digit_ratio": 0.04,
    "symbol_ratio": 0.02,
    "empty_line_ratio": 0.12,
    "avg_line_len": 23.3,
    "max_line_len": 120,
    "repeated_line_ratio": 0.03,
    "heading_count": 12,
    "question_count": 2,
    "code_line_ratio": 0.0,
    "page_density": 2390.0
  },
  "verdict": "pass",
  "reasons": [],
  "recommended_actions": ["proceed to chunk-plan selection"],
  "paths": {
    "sample_path": "<run-dir>/samples/<doc_id>_sample.txt",
    "integrity_json": "<run-dir>/samples/<doc_id>_integrity.json"
  }
}
```

`verdict` is `pass`, `warn`, or `fail`.

## `chunk_plans/<doc_id>.json`

```json
{
  "doc_id": "a1b2c3d4e5f60718",
  "title": "计算机操作系统",
  "mode": "hierarchical",
  "blocked": false,
  "target_chars": 700,
  "max_chars": 1540,
  "min_chars": 210,
  "overlap_chars": 100,
  "preserve_pages": true,
  "content_start_page": 22,
  "content_end_page": 407,
  "full_heading_count": 48,
  "full_question_count": 12,
  "question_signal": 18,
  "question_ratio": 0.03,
  "exam_heading_count": 1,
  "full_code_line_ratio": 0.0,
  "rationale": [
    "integrity=pass (based on 10% sample)",
    "full-doc headings=48, questions=12, question_signal=18, code_ratio=0.00%",
    "selected mode=hierarchical"
  ],
  "sample_metrics": {}
}
```

`mode` is `hierarchical`, `paragraph`, `question`, `code`, or `blocked`.

## `chunks/<doc_id>.jsonl`

One chunk per line:

```json
{
  "chunk_id": "a1b2c3d4e5f60718:00001",
  "doc_id": "a1b2c3d4e5f60718",
  "chunk_index": 1,
  "content": "1.1 操作系统的目标和作用\n\n操作系统...",
  "content_hash": "sha256...",
  "char_count": 820,
  "chunk_type": "hierarchical",
  "heading_path": ["第1章 操作系统引论", "1.1 操作系统的目标和作用"],
  "page_start": 22,
  "page_end": 24,
  "metadata": {
    "source_path": "D:\\data\\books\\os.pdf",
    "title": "计算机操作系统",
    "format": "pdf",
    "language": "zh",
    "unit_type": "page"
  }
}
```

## SQLite schema

```sql
CREATE TABLE documents (
  doc_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  source_hash TEXT,
  title TEXT,
  format TEXT,
  parse_method TEXT,
  unit_type TEXT,
  unit_count INTEGER,
  char_count INTEGER,
  language TEXT,
  created_at TEXT,
  metadata_json TEXT
);

CREATE TABLE chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT,
  char_count INTEGER,
  chunk_type TEXT,
  heading_path TEXT,
  page_start INTEGER,
  page_end INTEGER,
  metadata_json TEXT
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  content_tokens,
  heading_path,
  doc_id UNINDEXED,
  chunk_id UNINDEXED,
  tokenize='unicode61 remove_diacritics 2'
);
```

`content_tokens` is produced by `tokenize_for_fts()`: jieba search-mode tokens when jieba is available; otherwise CJK unigrams + bigrams and ASCII words.

## `ingest_report.json`

```json
{
  "db_path": "<run-dir>/kb.sqlite",
  "stats": {
    "documents": 1,
    "chunks": 880,
    "total_chars": 455000,
    "avg_chars": 517.0,
    "chunks_by_type": {"hierarchical": 880}
  },
  "generated_at": "2026-10-17T21:20:00+08:00"
}
```

## `run_state.json`

```json
{
  "run_id": "20261017-211500-0421",
  "input": "D:\\data\\books",
  "out_dir": "D:\\runs\\books-20261017",
  "started_at": "2026-10-17T21:15:00+08:00",
  "updated_at": "2026-10-17T21:20:00+08:00",
  "phase": "done",
  "config": {
    "sample_ratio": 0.1,
    "seed": 42,
    "sample_windows": 1,
    "min_sample_units": 5,
    "ocr": "auto",
    "mode": "auto",
    "include_front_matter": false
  }
}
```

Allowed `phase` values: `inventory`, `parse`, `sample`, `plan`, `chunk`, `ingest`, `done`, `blocked_parse`, `blocked_integrity`, `blocked_plan`, `blocked_chunk`, `blocked_ingest`, `blocked_verify`.
