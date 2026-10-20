# Four-phase workflow

Create a run directory for every task. Keep at least: `plan.md`, `source_selection.jsonl`, `mutation_manifest.jsonl`, `model_outputs.jsonl`, `answer_provenance.jsonl`, `audit_report.md`, and the final versioned dataset. Intermediate smoke-test files belong in a temporary subdirectory and should not be mixed with final deliverables.

Maintain a small `run_state.json` with `run_id`, target dataset, current phase, approval timestamps or quoted approvals, output paths, requested counts, and model configuration. Do not advance its phase without explicit user approval.

## Phase 1 — plan error types, proportions, and sources

1. Inspect the original dataset, its real schema, existing prompts, current type distribution, answer completeness, duplicates, and existing source registries.
2. Convert requested proportions into exact integer counts. Show the rounding rule and verify the counts sum to the requested total.
3. For every type, define:
   - exact count and proportion;
   - allowed subtypes and subtype quotas/ranges;
   - eligible question forms and excluded contexts;
   - whether rows are modified in place or sourced externally;
   - diversity constraints, repeated-signature caps, and ambiguity exclusions;
   - how the single intended error can be minimally repaired.
4. For externally sourced questions, inspect `C:\hyt-agent\外部数据源`, confirm that each source is a clean and usable question, calculate its normalized fingerprint, check all known registries, then reserve it in the long-term registry. Do not use a source merely because its hash is new: also check near-duplicate wording where practical.
5. Detect split leakage: do not put the clean original, or several nearly identical corrupted variants, across train/validation/test unless the user explicitly requests that design.

### Phase 1 report

Report the total, exact type/subtype counts and percentages, number of existing versus external source questions, unavailable or unsuitable source count, registry path and duplicate blocks, diversity rules, ambiguity risks, planned files, and any decisions needed. Then stop and ask for approval to begin phase 2.

## Phase 2 — Codex constructs the errors

1. Work only from the approved plan and reserved/approved sources.
2. Codex must understand each question and author its mutation. Do not use deterministic bulk replacement to create the semantic error. Deterministic tooling is allowed only for bookkeeping, format preservation, diffing, counting, and validation.
3. Construct one high-confidence root error per erroneous sample unless the approved plan explicitly calls for multiple errors.
4. Preserve all unrelated content exactly: knowledge, values, formulas, units, question structure, and answer-bearing information that the type does not authorize changing.
5. Record clean text, erroneous text, intended type/subtype, minimal before/after span, location/anchor candidate, source fingerprint, and a human-readable rationale in `mutation_manifest.jsonl`.
6. Review diversity continuously, not only at the end. If one surface mutation, token, location, stem pattern, or subtype dominates beyond the approved cap, redesign samples rather than merely relabeling them.
7. Mark accepted external sources `used`; release reservations for rejected sources.

### Phase 2 report

Report requested, constructed, skipped, and replaced counts; distribution by type/subtype; existing/external source counts; mutation-signature concentration; exact duplicate and near-duplicate findings; single-error and round-trip validation results; files produced; and unresolved ambiguous samples. Include a small representative sample, not the whole dataset. Then stop and ask for approval to begin phase 3.

## Phase 3 — external model generates candidate standard answers

1. Freeze the phase-2 questions. Prepare requests using the same prompt composition as comparable training rows: approved system prompt + approved specialty prompt + approved JSON constraint. Do not silently substitute a legacy prompt.
2. Run the approved model through a script, normally at concurrency 8. Record the requested model name and the actual model name returned by the endpoint.
3. Save one append-only record per attempt or preserve enough history to reconstruct attempts. Required information includes row/sample id, request messages or prompt hashes, model, status, raw response, parsed response, attempt count, timing, token usage when available, and error details.
4. Support retry and resume for failed rows only. A successful HTTP response or parse is not an accepted gold answer.
5. Keep candidate answers separate from the final dataset. Do not overwrite prior data or phase-2 manifests.

### Phase 3 report

Report requested rows, successes, failures, retries, schema-invalid outputs, model-declared `has_error=true/false`, actual model name, concurrency, token usage if available, output paths, and rows still needing generation. Then stop and ask for approval to begin phase 4.

## Phase 4 — Codex audits and finalizes

Codex reviews every generated candidate against the clean source, erroneous question, approved type, specialty prompt, and final schema. Do not delegate final acceptance to the same model that generated the candidate.

For each row, determine whether the model missed the intended error, invented another error, used the wrong type, proposed an invalid correction, selected a non-unique anchor, omitted fields, or returned boilerplate. Repair the candidate directly when the intended error is valid and uniquely supported. If the constructed question itself is ambiguous or contains multiple root errors, repair the question or exclude it; do not force a false-positive gold answer.

Run final structural and semantic checks described in `quality-gates.md`. Write only the audited answers to a new versioned dataset. Keep `answer_provenance.jsonl` with origin values such as `model_accepted`, `codex_repaired`, `codex_supplied`, or `excluded`, plus the audit reason.

### Phase 4 report

Report total audited, model answers accepted unchanged, Codex-repaired, Codex-supplied after model miss/failure, excluded, remaining unresolved, final type/subtype distribution, answer completeness, schema validity, single-error results, exact repair/round-trip results, duplicate/diversity results, model identity, and all final/backup/report paths. State “可用于训练” only if all required gates pass.
