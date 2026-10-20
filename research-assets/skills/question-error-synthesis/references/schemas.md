# Artifact schemas

Use the target dataset's existing format when it is stricter. Keep provenance outside the training answer if extra fields would break its schema.

## Source registry JSONL

One record per state transition or one current record per source is acceptable, but reads must resolve the latest state by fingerprint. Recommended fields:

```json
{
  "source_fingerprint_sha256": "normalized full-text SHA-256",
  "source_text": "complete clean source question",
  "source_file": "absolute source path",
  "source_question_number": "row/id when available",
  "source_page": null,
  "status": "reserved|used|released",
  "reserved_for_run": "run id",
  "sample_id": "planned/final sample id",
  "task_type": "target error type",
  "reserved_at": "ISO-8601 timestamp",
  "used_at": null,
  "note": "optional"
}
```

Normalization for fingerprinting: Unicode NFKC, normalize line endings, trim each line's outer whitespace, collapse internal horizontal whitespace, remove leading/trailing blank lines, then SHA-256 the UTF-8 text. Preserve the original text separately; the normalized form is only for matching.

`used` blocks all later runs. `reserved` blocks other active runs. `released` does not block, but remains in history. Existing registries with fewer fields remain valid deny-lists when their status is `used`.

## Mutation manifest JSONL

```json
{
  "sample_id": "stable id",
  "source_fingerprint_sha256": "...",
  "source_origin": "existing_dataset|external",
  "clean_text": "clean complete question",
  "error_text": "mutated complete question",
  "error_type": "top-level type",
  "error_detailed_type": "specific subtype",
  "original_text": "minimal erroneous span",
  "correction": "minimal correct span",
  "anchor_text": "unique continuous erroneous context",
  "mutation_signature": "subtype|operation|location-class|changed-token-class",
  "rationale": "why this is one objective error",
  "phase2_status": "accepted|rejected"
}
```

## Candidate/final standard answer

For datasets using today's micro-tuning schema, each erroneous question's answer is sample-specific and follows:

```json
{
  "reason": "concise diagnosis of this question",
  "has_error": true,
  "total_errors": 1,
  "errors": [
    {
      "error_type": "approved fixed top-level error type",
      "position": "specific location in this question",
      "original_text": "minimal erroneous text actually present",
      "anchor_text": "unique continuous excerpt actually present",
      "correction": "minimal correct replacement",
      "description": "question-specific explanation",
      "suggestion": "question-specific repair instruction"
    }
  ]
}
```

These are field definitions, not fixed answer text. Never copy placeholder phrases such as “错误片段” or “对应错误类型的说明” into real answers. Clean rows, if included, must follow the target dataset's established no-error representation exactly.

## Model-call record JSONL

Preserve: `sample_id` or line number, request prompt/messages or prompt hashes, endpoint identifier without secrets, requested model, returned model, concurrency/run id, status, raw response, parsed response, attempts, elapsed time, token usage, and error details. Append or version records so retries do not erase evidence.

## Answer provenance JSONL

Preserve: `sample_id`, model candidate status, final origin (`model_accepted|codex_repaired|codex_supplied|excluded`), audit failure/reason codes, final-answer hash, auditor identity (`Codex`), audit timestamp, and output dataset version.
