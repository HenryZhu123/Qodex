# Quality gates and learned lessons

## Core sample invariants

Every erroneous sample must satisfy all of these:

1. **Valid clean baseline**: the source question is itself complete, correct for the targeted dimension, and not already contaminated by an unrelated obvious error.
2. **One root error**: the mutation introduces exactly one intended root error unless the approved plan says otherwise. A single edit that simultaneously creates two independently labelable errors fails this gate.
3. **Type fidelity**: the actual error, not the plan label, determines the type and subtype.
4. **Minimal repair**: the correction changes only the smallest necessary span.
5. **Exact restoration**: applying the correction to the erroneous text restores the clean baseline exactly, including punctuation and spacing where the dataset treats them as meaningful.
6. **Stable localization**: `original_text` appears in the erroneous question and the chosen `anchor_text` is continuous, searchable, and unique. Expand the anchor only as much as needed for uniqueness.
7. **No process traces**: questions and answers contain no wording such as “为了造错”, “按要求修改”, placeholders, template labels, or hidden work notes.

## Diversity is semantic, not just statistical

Balanced top-level counts are insufficient. Audit diversity at four levels: subtype, mutation operation, changed token/span, and location/question form. Configure caps in phase 1 according to dataset size. Flag long runs or dominant signatures.

Known failure patterns that must not recur:

- mass-changing many rows to the same visible token, such as `。。。`;
- adding quotation marks to the same word in dozens of questions;
- mechanically deleting the final punctuation from nearly every sample;
- using varied labels for effectively identical mutations;
- selecting different rows from the same source question and treating them as independent diversity.

Code may enforce quotas and identify repetition. It may not be the author of a semantic mutation template applied across the batch. Codex must choose context-appropriate mutations question by question.

## Error-type boundary checks

- **Quotation-mark position**: start from a context with legitimate quotation marks and move only the punctuation. Adding unjustified quotation marks creates quotation misuse, not merely an inside/outside-position error.
- **Quotation misuse/missing**: verify whether quotation marks are already justified by direct speech, titles, terms, irony, special emphasis, or other legitimate usage. Vary the targeted word and context.
- **Ellipsis**: use only unambiguous functions and valid six-dot/two-character Chinese ellipsis rules applicable to the prompt. Avoid a proposed repair that leaves or creates duplicate sentence-ending punctuation.
- **Missing punctuation**: a missing sentence-final mark counts only when the complete question convention requires it; do not dismiss it as a publishing preference if the approved standard treats it as an error.
- **Information missing**: remove a condition that is necessary and uniquely recoverable, while leaving a grammatical question. Do not simply truncate a sentence.
- **Option structure**: preserve option semantics and correct answer; change only the approved structural carrier.

Add analogous boundary rules for every new error type during phase 1.

## External model interpretation

Treat model output as a fallible candidate. A model response of `has_error=false` can mean:

- the mutation is ambiguous or not truly erroneous;
- the specialty prompt does not cover the subtype;
- the model missed a valid error;
- the request used the wrong prompt composition.

Investigate these possibilities rather than automatically forcing `has_error=true`. Conversely, a confident model answer can still fail exact restoration, single-error, anchor, or schema checks.

## Final audit checklist

For every row verify:

- expected message roles and prompt identity;
- valid parse and exact final schema;
- fixed top-level `error_type` where required;
- `has_error`, `total_errors`, and `errors` agree;
- all required nested fields are nonempty and sample-specific;
- error span, position, anchor, correction, explanation, and suggestion agree with one another;
- no hallucinated second error;
- exact clean-text restoration;
- no duplicated or near-duplicated source leakage;
- no answer copied as a generic fixed object across rows.

Summarize failures by reason and retain row ids so every reported count is reproducible.
