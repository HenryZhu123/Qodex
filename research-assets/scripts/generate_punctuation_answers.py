from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


def load_inputs(
    path: Path,
    limit: int | None,
    include_lines: set[int] | None = None,
    system_override: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            if include_lines is not None and line_number not in include_lines:
                continue
            payload = json.loads(line)
            messages = [
                message
                for message in payload.get("messages", [])
                if message.get("role") in {"system", "user"}
            ]
            roles = [message.get("role") for message in messages]
            if roles != ["system", "user"]:
                raise ValueError(f"line {line_number}: expected system+user, got {roles}")
            if system_override is not None:
                messages[0] = {"role": "system", "content": system_override}
            rows.append({"line_number": line_number, "messages": messages})
            if limit is not None and len(rows) >= limit:
                break
    if not rows:
        raise ValueError("input dataset is empty")
    system_prompts = {row["messages"][0]["content"] for row in rows}
    if len(system_prompts) != 1:
        raise ValueError(f"expected one shared system prompt, got {len(system_prompts)}")
    return rows


def load_completed(path: Path) -> set[int]:
    completed: set[int] = set()
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") == "success":
                completed.add(int(row["line_number"]))
    return completed


async def run(args: argparse.Namespace) -> int:
    api_key = os.environ.get("TOKEN_PLAN_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TOKEN_PLAN_API_KEY is required")

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    summary_path = output_path.with_suffix(".summary.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    include_lines = None
    if args.include_lines:
        include_lines = {
            int(value.strip())
            for value in args.include_lines.split(",")
            if value.strip()
        }
    system_override = None
    if args.system_part:
        system_override = "\n".join(
            Path(part).resolve().read_text(encoding="utf-8").strip()
            for part in args.system_part
        )
    rows = load_inputs(input_path, args.limit, include_lines, system_override)
    if include_lines is not None:
        found_lines = {row["line_number"] for row in rows}
        missing_lines = sorted(include_lines - found_lines)
        if missing_lines:
            raise ValueError(f"requested source lines not found: {missing_lines}")
    completed = load_completed(output_path) if args.resume else set()
    pending = [row for row in rows if row["line_number"] not in completed]
    semaphore = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()
    counters: Counter[str] = Counter()
    usage: Counter[str] = Counter()
    started = time.time()
    endpoint = f"{args.base_url.rstrip('/')}/chat/completions"

    timeout = httpx.Timeout(args.timeout, connect=30.0)
    limits = httpx.Limits(
        max_connections=max(args.concurrency * 2, 16),
        max_keepalive_connections=max(args.concurrency, 8),
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=timeout, limits=limits, headers=headers) as client:
        async def generate(row: dict[str, Any]) -> None:
            last_error = ""
            result: dict[str, Any] | None = None
            elapsed = 0.0
            for attempt in range(1, args.retries + 1):
                request_started = time.time()
                try:
                    async with semaphore:
                        response = await client.post(
                            endpoint,
                            json={
                                "model": args.model,
                                "messages": row["messages"],
                                "temperature": args.temperature,
                                "response_format": {"type": "json_object"},
                            },
                        )
                    elapsed += time.time() - request_started
                    response.raise_for_status()
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    if not isinstance(parsed, dict):
                        raise ValueError("model response is not a JSON object")
                    result = {
                        "line_number": row["line_number"],
                        "status": "success",
                        "model": body.get("model", args.model),
                        "answer": parsed,
                        "raw_answer": content,
                        "usage": body.get("usage", {}),
                        "attempts": attempt,
                        "elapsed_seconds": round(elapsed, 3),
                    }
                    break
                except Exception as exc:  # noqa: BLE001
                    elapsed += time.time() - request_started
                    detail = ""
                    if isinstance(exc, httpx.HTTPStatusError):
                        detail = f" body={exc.response.text[:1000]}"
                    last_error = f"{type(exc).__name__}: {exc}{detail}"
                    if attempt < args.retries:
                        await asyncio.sleep(min(2 ** (attempt - 1), 8))

            if result is None:
                result = {
                    "line_number": row["line_number"],
                    "status": "failed",
                    "model": args.model,
                    "error": last_error,
                    "attempts": args.retries,
                    "elapsed_seconds": round(elapsed, 3),
                }

            async with write_lock:
                with output_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                    handle.flush()
                counters[result["status"]] += 1
                for key, value in (result.get("usage") or {}).items():
                    if isinstance(value, int):
                        usage[key] += value
                done = sum(counters.values())
                if done == 1 or done % args.progress_every == 0 or done == len(pending):
                    print(
                        json.dumps(
                            {
                                "done": done,
                                "pending_batch": len(pending),
                                "success": counters["success"],
                                "failed": counters["failed"],
                                "elapsed_seconds": round(time.time() - started, 1),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )

        await asyncio.gather(*(generate(row) for row in pending))

    all_results: list[dict[str, Any]] = []
    with output_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                all_results.append(json.loads(line))
    latest_by_line = {int(row["line_number"]): row for row in all_results}
    scoped_results = [latest_by_line[row["line_number"]] for row in rows if row["line_number"] in latest_by_line]
    final_counts = Counter(row.get("status", "unknown") for row in scoped_results)
    schema_invalid = 0
    has_error_counts: Counter[str] = Counter()
    for row in scoped_results:
        if row.get("status") != "success":
            continue
        answer = row.get("answer") or {}
        required = {"reason", "has_error", "total_errors", "errors"}
        if not required.issubset(answer) or not isinstance(answer.get("errors"), list):
            schema_invalid += 1
        has_error_counts[str(answer.get("has_error")).lower()] += 1
    summary = {
        "input": str(input_path),
        "output": str(output_path),
        "model": args.model,
        "base_url": args.base_url,
        "concurrency": args.concurrency,
        "temperature": args.temperature,
        "requested_rows": len(rows),
        "previously_completed": len(completed),
        "attempted_this_run": len(pending),
        "results_present": len(scoped_results),
        "status_counts": dict(final_counts),
        "basic_schema_invalid": schema_invalid,
        "has_error_counts": dict(has_error_counts),
        "usage_this_run": dict(usage),
        "elapsed_seconds": round(time.time() - started, 3),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if final_counts.get("success", 0) == len(rows) and schema_invalid == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate punctuation answers with an OpenAI-compatible API")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="qwen3.8-max")
    parser.add_argument(
        "--base-url",
        default="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--include-lines",
        default="",
        help="Comma-separated 1-based source JSONL line numbers",
    )
    parser.add_argument(
        "--system-part",
        action="append",
        default=[],
        help="System prompt part; repeat in the exact composition order",
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.concurrency < 1 or args.retries < 1:
        raise SystemExit("concurrency and retries must be positive")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
