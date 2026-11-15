#!/usr/bin/env python3
"""Generate Phase-3 candidate answers for the Blind-v2 overlap expansion.

The output is append-only and resumable. It is deliberately kept separate
from every final/gold dataset; Phase 4 remains responsible for auditing.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[2]
PROMPT_ROOT = ROOT / "提示词-微调版"
FACTUAL_CARD = ROOT / "提示词" / "事实、逻辑错误.txt"
DEFAULT_RUN = ROOT / "review_eval" / "blind_v2_expansion" / "runs" / "blind_v2_overlap_expansion_20261031"

TASK_CARDS = {
    "ambiguity": PROMPT_ROOT / "语义不清.txt",
    "answer_leakage": PROMPT_ROOT / "答案泄露.txt",
    "factual_logical": FACTUAL_CARD,
    "option_structure": PROMPT_ROOT / "选项结构错误.txt",
    "punctuation": PROMPT_ROOT / "标点符号错误.txt",
    "solvability_failure": PROMPT_ROOT / "题目无解.txt",
    "type_mismatch": PROMPT_ROOT / "题目与题型不一致_v2.txt",
}

EXPECTED_LABELS = {
    "ambiguity": "语义不清",
    "answer_leakage": "答案泄露",
    "factual_logical": "事实/逻辑错误",
    "option_structure": "选项错误",
    "punctuation": "标点符号错误",
    "solvability_failure": "题目无解",
    "type_mismatch": "题目与题型不一致",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def resolve_api_key() -> str:
    value = os.environ.get("TALKWEB_API_KEY", "")
    if value:
        return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            value, _ = winreg.QueryValueEx(key, "TALKWEB_API_KEY")
    except Exception:
        value = ""
    return value


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found")
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                parsed = json.loads(text[start : idx + 1])
                if not isinstance(parsed, dict):
                    raise ValueError("top-level JSON is not an object")
                return parsed
    raise ValueError("incomplete JSON object")


def validate_candidate(parsed: dict[str, Any], expected_label: str) -> list[str]:
    problems: list[str] = []
    if not isinstance(parsed.get("reason"), str):
        problems.append("reason_not_string")
    if not isinstance(parsed.get("has_error"), bool):
        problems.append("has_error_not_bool")
    if not isinstance(parsed.get("total_errors"), int):
        problems.append("total_errors_not_int")
    errors = parsed.get("errors")
    if not isinstance(errors, list):
        problems.append("errors_not_list")
        return problems
    if isinstance(parsed.get("total_errors"), int) and parsed["total_errors"] != len(errors):
        problems.append("total_errors_mismatch")
    if parsed.get("has_error") is False and errors:
        problems.append("false_with_errors")
    if parsed.get("has_error") is True and not errors:
        problems.append("true_without_errors")
    required = ["error_type", "position", "original_text", "anchor_text", "correction", "description", "suggestion"]
    for index, error in enumerate(errors):
        if not isinstance(error, dict):
            problems.append(f"error_{index}_not_object")
            continue
        for field in required:
            if field not in error or not isinstance(error.get(field), str):
                problems.append(f"error_{index}_{field}_invalid")
        if error.get("error_type") != expected_label:
            problems.append(f"error_{index}_wrong_type")
    return problems


def make_prompts() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    shared_path = PROMPT_ROOT / "共享核心.txt"
    json_path = PROMPT_ROOT / "JSON约束.txt"
    shared = shared_path.read_text(encoding="utf-8").strip()
    json_constraint = json_path.read_text(encoding="utf-8").strip()
    prompts: dict[str, str] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for error_type, card_path in TASK_CARDS.items():
        card = card_path.read_text(encoding="utf-8").strip()
        prompt = "\n\n".join([shared, card, json_constraint])
        prompts[error_type] = prompt
        metadata[error_type] = {
            "shared_core": str(shared_path),
            "task_card": str(card_path),
            "json_constraint": str(json_path),
            "system_prompt_sha256": sha256_text(prompt),
        }
    return prompts, metadata


def build_client(timeout: float) -> httpx.AsyncClient:
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or ""
    ).strip()
    try:
        return httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=proxy or None)
    except Exception:
        return httpx.AsyncClient(timeout=timeout, trust_env=False)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--base-url", default="https://llm.talkweb.com.cn/v1")
    parser.add_argument("--model", default="gpu-qwen3.8-27b")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=0)
    args = parser.parse_args()

    api_key = resolve_api_key()
    if not api_key:
        raise SystemExit("TALKWEB_API_KEY is not configured")

    run_dir = args.run_dir.resolve()
    input_path = run_dir / "phase2_questions.jsonl"
    output_path = run_dir / "model_outputs.jsonl"
    rows = read_jsonl(input_path)
    prompts, prompt_metadata = make_prompts()
    input_sha = hashlib.sha256(input_path.read_bytes()).hexdigest()

    config = {
        "run_id": run_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path),
        "input_sha256": input_sha,
        "requested_rows": len(rows),
        "endpoint": f"{args.base_url.rstrip('/')}/chat/completions",
        "requested_model": args.model,
        "concurrency": args.concurrency,
        "timeout_seconds": args.timeout,
        "max_attempts": args.max_attempts,
        "temperature": 0.0,
        "seed": 42,
        "response_format": {"type": "json_object"},
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": args.max_tokens or None,
        "prompt_composition": "shared_core + task_card + JSON_constraint",
        "prompts": prompt_metadata,
    }
    config_path = run_dir / "phase3_config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    history_path = run_dir / "phase3_config_history.jsonl"
    if not history_path.exists():
        baseline_config = json.loads(config_path.read_text(encoding="utf-8"))
        history_path.write_text(json.dumps(baseline_config, ensure_ascii=False) + "\n", encoding="utf-8")
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(config, ensure_ascii=False) + "\n")

    prior = read_jsonl(output_path)
    successful_ids = {row["sample_id"] for row in prior if row.get("status") == "success"}
    pending = [row for row in rows if row["sample_id"] not in successful_ids]
    prior_attempts = Counter(row.get("sample_id") for row in prior)
    semaphore = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()

    async with build_client(args.timeout + 30.0) as client:
        async def process(row: dict[str, Any]) -> None:
            async with semaphore:
                sample_id = str(row["sample_id"])
                error_type = str(row["error_type"])
                system_prompt = prompts[error_type]
                user_payload = "[INPUT_PAYLOAD]\n" + json.dumps(
                    {
                        "reference": row["reference"],
                        "detection_content": row["detection_content"],
                    },
                    ensure_ascii=False,
                )
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ]
                request_hash = sha256_text(json.dumps(messages, ensure_ascii=False, sort_keys=True))
                for local_attempt in range(1, args.max_attempts + 1):
                    attempt = prior_attempts[sample_id] + local_attempt
                    started = datetime.now(timezone.utc).isoformat()
                    t0 = time.perf_counter()
                    status = "exception"
                    raw_response = ""
                    parsed_response: dict[str, Any] | None = None
                    returned_model = ""
                    usage: dict[str, Any] | None = None
                    raw_api_response: dict[str, Any] | None = None
                    finish_reason = ""
                    http_status: int | None = None
                    error_details: dict[str, Any] | None = None
                    try:
                        request_body = {
                            "model": args.model,
                            "messages": messages,
                            "temperature": 0.0,
                            "seed": 42,
                            "response_format": {"type": "json_object"},
                            "enable_thinking": False,
                            "chat_template_kwargs": {"enable_thinking": False},
                        }
                        if args.max_tokens > 0:
                            request_body["max_tokens"] = args.max_tokens
                        response = await client.post(
                            f"{args.base_url.rstrip('/')}/chat/completions",
                            headers={"Authorization": f"Bearer {api_key}"},
                            json=request_body,
                            timeout=args.timeout,
                        )
                        http_status = response.status_code
                        if response.status_code != 200:
                            status = "http_error"
                            raw_response = response.text
                            error_details = {"message": response.text[:2000]}
                        else:
                            body = response.json()
                            raw_api_response = body
                            returned_model = str(body.get("model") or "")
                            usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
                            finish_reason = str(body["choices"][0].get("finish_reason") or "")
                            raw_response = str(body["choices"][0]["message"].get("content") or "")
                            try:
                                parsed_response = parse_json_object(raw_response)
                                schema_errors = validate_candidate(
                                    parsed_response, EXPECTED_LABELS[error_type]
                                )
                                if schema_errors:
                                    status = "schema_invalid"
                                    error_details = {"schema_errors": schema_errors}
                                else:
                                    status = "success"
                            except Exception as exc:  # noqa: BLE001
                                status = "parse_error"
                                error_details = {"type": type(exc).__name__, "message": str(exc)}
                    except Exception as exc:  # noqa: BLE001
                        error_details = {"type": type(exc).__name__, "message": str(exc)}

                    record = {
                        "run_id": run_dir.name,
                        "sample_id": sample_id,
                        "error_type": error_type,
                        "attempt": attempt,
                        "started_at": started,
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                        "endpoint": f"{args.base_url.rstrip('/')}/chat/completions",
                        "requested_model": args.model,
                        "returned_model": returned_model,
                        "concurrency": args.concurrency,
                        "max_tokens": args.max_tokens or None,
                        "system_prompt_sha256": sha256_text(system_prompt),
                        "user_prompt_sha256": sha256_text(user_payload),
                        "request_messages_sha256": request_hash,
                        "status": status,
                        "http_status": http_status,
                        "raw_response": raw_response,
                        "raw_api_response": raw_api_response,
                        "finish_reason": finish_reason,
                        "parsed_response": parsed_response,
                        "usage": usage,
                        "error_details": error_details,
                    }
                    async with write_lock:
                        with output_path.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    print(f"[{sample_id}] attempt={attempt} status={status}", flush=True)
                    if status == "success":
                        return
                    if local_attempt < args.max_attempts:
                        await asyncio.sleep(min(2 ** (local_attempt - 1), 4))

        await asyncio.gather(*(process(row) for row in pending))

    attempts = read_jsonl(output_path)
    latest_success: dict[str, dict[str, Any]] = {}
    for record in attempts:
        if record.get("status") == "success":
            latest_success[str(record["sample_id"])] = record
    missing = [row["sample_id"] for row in rows if row["sample_id"] not in latest_success]
    successful = list(latest_success.values())
    usage_totals = Counter()
    for record in successful:
        for key, value in (record.get("usage") or {}).items():
            if isinstance(value, (int, float)):
                usage_totals[key] += value
    baseline_config = json.loads(config_path.read_text(encoding="utf-8"))
    summary = {
        "requested_rows": len(rows),
        "successes": len(successful),
        "failures": len(missing),
        "rows_still_needing_generation": missing,
        "total_attempt_records": len(attempts),
        "retry_attempts": max(0, len(attempts) - len({row.get('sample_id') for row in attempts})),
        "attempt_status_counts": dict(Counter(row.get("status") for row in attempts)),
        "schema_invalid_attempts": sum(row.get("status") == "schema_invalid" for row in attempts),
        "model_declared_has_error_true": sum(
            bool((row.get("parsed_response") or {}).get("has_error")) for row in successful
        ),
        "model_declared_has_error_false": sum(
            (row.get("parsed_response") or {}).get("has_error") is False for row in successful
        ),
        "requested_model": args.model,
        "returned_models": dict(Counter(row.get("returned_model") or "<missing>" for row in successful)),
        "primary_concurrency": baseline_config.get("concurrency"),
        "last_invocation_concurrency": args.concurrency,
        "attempt_concurrency_counts": dict(Counter(str(row.get("concurrency")) for row in attempts)),
        "usage_totals_successful_rows": dict(usage_totals),
        "output_path": str(output_path),
    }
    (run_dir / "phase3_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
