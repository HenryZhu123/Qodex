---
name: question-error-synthesis
description: Use when planning, constructing, labeling, or auditing synthetic erroneous Chinese exam-question datasets (造错、错题负样本、错误类型配比、调用外部模型生成标准答案). Enforces a four-phase user-confirmed workflow, source-question non-reuse, diverse Codex-authored mutations, recorded 8-concurrency answer generation, and Codex final audit.
---

# Question Error Synthesis

Build synthetic erroneous-question datasets through four strictly separated phases. This skill treats the user-approved plan, clean source question, mutation record, raw model answer, and audited gold answer as different artifacts.

## Required references

Read these before beginning a run:

- [workflow.md](references/workflow.md): phase boundaries, artifacts, and user reports.
- [quality-gates.md](references/quality-gates.md): construction and audit standards learned from prior runs.
- [schemas.md](references/schemas.md): manifests, source registry, and gold-answer schema.

Read the relevant error-specific prompt under `C:\hyt-agent\提示词-微调版` and inspect comparable rows in the target training dataset before fixing field names or prompt composition. The target dataset's established system prompt, specialty prompt, JSON constraint, and column schema take precedence over legacy agent formats.

## Non-negotiable workflow

1. Execute only the current phase.
2. End every phase with the report defined in `references/workflow.md`.
3. Stop after the report and wait for explicit user approval before starting the next phase.
4. An earlier approval of the overall task is not approval of later phases.
5. Never mutate the original dataset. Work in a new, clearly versioned output directory and retain a backup or immutable source reference.

## Division of responsibility

- Phase 1: Codex plans types, proportions, sources, and diversity constraints. No mutation and no API call.
- Phase 2: Codex itself constructs the erroneous questions. Scripts may select, diff, hash, count, and validate; they must not mass-produce semantic mutations from a fixed replacement rule. No external-model call.
- Phase 3: A script calls the approved external model to generate candidate standard answers, normally with concurrency 8. Save every raw result. Do not write candidates into the final dataset.
- Phase 4: Codex audits every candidate and supplies or repairs answers. Only audited answers may be written to the new final dataset.

## Source reuse control

Use `scripts/source_registry.ps1` for newly selected external questions. The default long-term registry should live under `C:\hyt-agent\数据集`; also check existing project registries such as `source_usage_registry.jsonl` as legacy deny-lists. Reserve sources during phase 1, mark them used only after phase 2 accepts the mutation, and release unused reservations. A prior `used` fingerprint blocks reuse unless the user explicitly authorizes reuse.

## Existing workspace tools

Reuse compatible workspace scripts after inspecting them. `C:\hyt-agent\scripts\generate_punctuation_answers.py` already implements OpenAI-compatible calls, eight-way concurrency, retries, resumability, and raw JSONL logging; despite its name, use it only when its input/output contract matches the current dataset. Never place API keys in prompts, datasets, reports, or source control.

## Completion rule

Do not call a dataset trainable merely because every row contains JSON. It is complete only after phase 4 passes structural checks, semantic checks, exact repair checks, source/provenance checks, and diversity checks, with all failures resolved or explicitly excluded.
