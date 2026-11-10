#!/usr/bin/env python3
"""Run a dataset through the same eight-task scheduler used in production.

Unlike the legacy benchmark scripts, this runner never uses the gold category
to select a specialist. Clean and mutated questions follow the identical
QuestionReviewService path, including Jev routing, retries, aggregation, and
UNRESOLVED handling.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REVIEW_ROOT = SCRIPT_DIR.parent
REPO_SRC = REVIEW_ROOT.parents[1] / "pi-coding-agent" / "services" / "exam-checker" / "src"
sys.path.insert(0, str(REPO_SRC))
sys.path.insert(0, str(SCRIPT_DIR))

from evaluation_metrics import summarize  # noqa: E402
from exam_checker.config import Settings  # noqa: E402
from exam_checker.domain.models import CheckerPayload  # noqa: E402
from exam_checker.integrations.knowledge_base import KnowledgeBaseRetriever  # noqa: E402
from exam_checker.integrations.openrouter_decisions import OpenRouterJevClient  # noqa: E402
from exam_checker.integrations.specialist_reviewer import OpenAICompatibleSpecialistReviewer  # noqa: E402
from exam_checker.prompts.repositories import JevPromptRepository, ReviewPromptRepository  # noqa: E402
from exam_checker.services.question_review_service import QuestionReviewService  # noqa: E402

EXPECTED_ERROR_TYPES = {
    "typo": "错别字",
    "punctuation": "标点符号错误",
    "option_structure": "选项错误",
    "type_mismatch": "题目与题型不一致",
    "solvability_failure": "可解性错误",
    "ambiguity": "语义不清",
    "answer_leakage": "答案泄露",
    "factual_logical": "事实/逻辑错误",
}


def _resolve_api_key(name: str, fallback: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if fallback:
        value = os.environ.get(fallback, "").strip()
        if value:
            return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value).strip()
    except Exception:
        return ""


def _load_rows(dataset: Path) -> list[dict[str, str]]:
    with dataset.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _task_detail(check: Any) -> dict[str, Any]:
    result = check.result
    return {
        "task_id": check.task_id,
        "routing_mode": check.routing_mode,
        "execution_status": check.execution_status,
        "attempts": check.attempts,
        "latency_ms": check.latency_ms,
        "error_code": check.error_code,
        "retryable": check.retryable,
        "error": check.error,
        "has_error": bool(result and result.has_error),
        "error_types": [error.error_type for error in result.errors] if result else [],
        "errors": [error.model_dump() for error in result.errors] if result else [],
        "kb_queries": check.kb_queries,
        "kb_latency_ms": check.kb_latency_ms,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=REVIEW_ROOT / "blind_test_v2" / "dataset" / "blind_v2_dataset.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REVIEW_ROOT / "blind_test_v2" / "runs" / "end_to_end" / "results.jsonl",
    )
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--review-max-concurrency",
        type=int,
        default=0,
        help="Override specialist reviewer concurrency; 0 uses configured value.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--sample-id",
        action="append",
        default=[],
        help="Only evaluate the selected sample ID; may be repeated.",
    )
    parser.add_argument("--review-base-url", default="")
    parser.add_argument("--review-model", default="")
    args = parser.parse_args()

    settings = Settings.from_env()
    review_api_key = settings.review_llm_api_key or _resolve_api_key("TALKWEB_API_KEY")
    jev_api_key = settings.jev_api_key or _resolve_api_key("EXAM_CHECKER_JEV_API_KEY")
    if not review_api_key:
        raise SystemExit("Missing review LLM API key")
    if not jev_api_key:
        raise SystemExit(
            "Missing Jev router API key. Configure EXAM_CHECKER_JEV_API_KEY "
            "or OPENROUTER_API_KEY; evaluation refuses an accidental all-task fallback run."
        )

    prompts = ReviewPromptRepository(settings.review_prompt_root)
    jev_prompts = JevPromptRepository(settings.jev_prompt_root)
    knowledge_base = KnowledgeBaseRetriever(settings.knowledge_base_dir)
    reviewer = OpenAICompatibleSpecialistReviewer(
        args.review_base_url or settings.review_llm_base_url or "https://llm.talkweb.com.cn/v1",
        review_api_key,
        args.review_model or settings.review_llm_model or "gpu-qwen3.8-27b",
        prompts,
        timeout_seconds=settings.review_llm_timeout_seconds,
        max_concurrency=(
            args.review_max_concurrency
            if args.review_max_concurrency > 0
            else settings.review_llm_max_concurrency
        ),
        max_attempts=settings.review_llm_max_attempts,
        knowledge_base=knowledge_base,
        reasoning_effort=settings.review_reasoning_effort,
        max_tokens=settings.review_max_tokens,
        agentic_logic_prompt_path=settings.agentic_logic_prompt_path,
    )
    router = OpenRouterJevClient(
        settings.jev_base_url,
        jev_api_key,
        settings.jev_model,
        jev_prompts,
        endpoint_url=settings.jev_endpoint,
        timeout_seconds=settings.jev_timeout_seconds,
        max_concurrency=settings.jev_max_concurrency,
    )
    service = QuestionReviewService(router=router, reviewer=reviewer, jev_prompts=jev_prompts)

    rows = _load_rows(args.dataset)
    if args.sample_id:
        selected_ids = set(args.sample_id)
        rows = [row for row in rows if row.get("sample_id") in selected_ids]
        found_ids = {row.get("sample_id") for row in rows}
        missing_ids = sorted(selected_ids - found_ids)
        if missing_ids:
            raise SystemExit(f"Unknown sample IDs: {', '.join(missing_ids)}")
    if args.limit > 0:
        rows = rows[: args.limit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed: dict[str, dict[str, Any]] = {}
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                completed[record["sample_id"]] = record

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    write_lock = asyncio.Lock()
    output_handle = args.output.open("a", encoding="utf-8")

    async def evaluate(row: dict[str, str]) -> None:
        sample_id = row["sample_id"]
        if sample_id in completed:
            return
        async with semaphore:
            started = time.perf_counter()
            payload = CheckerPayload(
                reference=row.get("reference", ""),
                detection_content=row.get("full_text", ""),
            )
            try:
                reviewed = await service.review_question(
                    document_id="benchmark",
                    question_id=sample_id,
                    question_number=sample_id,
                    payload=payload,
                )
                review = reviewed.review
                if review.status == "UNRESOLVED":
                    status = "UNRESOLVED"
                elif review.summary.has_error:
                    status = "DETECTED"
                else:
                    status = "CLEAN"
                category = "clean" if row.get("label") == "clean" else row.get("error_type", "unknown")
                detected_error_types = [error.error_type for error in review.summary.errors]
                record = {
                    "sample_id": sample_id,
                    "category": category,
                    "is_clean": row.get("label") == "clean",
                    "status": status,
                    "detected_error_types": detected_error_types,
                    "target_type_hit": (
                        None if category == "clean"
                        else EXPECTED_ERROR_TYPES.get(category) in detected_error_types
                    ),
                    "unresolved_checks": review.summary.unresolved_checks,
                    "routing": {
                        task_id: decision.model_dump()
                        for task_id, decision in review.routing.items()
                    },
                    "checks": [_task_detail(check) for check in review.checks],
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            except Exception as exc:  # noqa: BLE001
                record = {
                    "sample_id": sample_id,
                    "category": "clean" if row.get("label") == "clean" else row.get("error_type", "unknown"),
                    "is_clean": row.get("label") == "clean",
                    "status": "UNRESOLVED",
                    "detected_error_types": [],
                    "target_type_hit": False,
                    "unresolved_checks": ["runner"],
                    "routing": {},
                    "checks": [],
                    "runner_error": {
                        "type": type(exc).__name__,
                        "message": str(exc)[:1000],
                    },
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            async with write_lock:
                output_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                output_handle.flush()
                completed[sample_id] = record
                print(f"[{len(completed)}/{len(rows)}] {sample_id} {record['status']}", flush=True)

    try:
        await asyncio.gather(*(evaluate(row) for row in rows))
    finally:
        output_handle.close()
        await router.close()
        await reviewer.close()

    summary = summarize(completed.values())
    summary_path = args.output.with_name("summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
