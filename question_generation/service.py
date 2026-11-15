"""HTTP bridge for Pi. Successful question packages are queued before returning."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from typing import Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from .batch import generate_batch
from .comprehensive import generate_comprehensive, revise_comprehensive
from .generation import failure_result, generate_question

OPERATIONS = {
    "single": generate_question,
    "batch": generate_batch,
    "comprehensive": generate_comprehensive,
    "revise": revise_comprehensive,
}


class QueueConflict(Exception):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.environ.get("QUESTION_GENERATION_DATABASE_URL")
    if not dsn:
        raise RuntimeError("QUESTION_GENERATION_DATABASE_URL must be set")
    async with asyncpg.create_pool(dsn, min_size=1, max_size=4, timeout=5, command_timeout=5) as pool:
        app.state.queue_pool = pool
        yield


app = FastAPI(title="Qodex Question Generation", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/question-generation/{operation}")
async def submit(
    operation: Literal["single", "batch", "comprehensive", "revise"],
    request: Request,
    payload: dict = Body(),
):
    raw_task_id = payload.pop("task_id", None)
    try:
        task_id = UUID(raw_task_id) if raw_task_id is not None else uuid4()
    except (TypeError, ValueError, AttributeError):
        return JSONResponse(
            failure_result("INVALID_REQUEST", "task_id 必须是 UUID 字符串。", payload.get("request_id")),
            status_code=422,
        )
    generation_request = dict(payload)
    result = await asyncio.to_thread(OPERATIONS[operation], generation_request)
    result = {**result, "task_id": str(task_id)}
    questions = result["questions"]
    previous = json.dumps(generation_request["current_question"]) if operation == "revise" else None
    receipts = {}
    try:
        async with request.app.state.queue_pool.acquire(timeout=5) as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO question_generation.generation_tasks (
                    task_id, request_id, generation_mode, status, question_count,
                    request_json, model_name, prompt_version, completed_at, failure_reason
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)
                ON CONFLICT (task_id) DO UPDATE SET
                    updated_at = now(),
                    status = EXCLUDED.status,
                    completed_at = EXCLUDED.completed_at,
                    failure_reason = EXCLUDED.failure_reason
                """,
                task_id,
                result.get("request_id") or "unknown",
                operation,
                "PENDING_REVIEW" if questions else "FAILED",
                len(questions),
                json.dumps(generation_request),
                os.environ.get("QUESTION_GENERATION_MODEL", "deterministic-local"),
                os.environ.get("QUESTION_GENERATION_PROMPT_VERSION", "0.1"),
                datetime.now(timezone.utc) if questions else None,
                None if questions else result.get("message", result.get("status")),
            )
            # Lock question IDs in the same order when concurrent batches overlap.
            for question in sorted(questions, key=lambda item: item["question_id"]):
                question_id = question["question_id"]
                version = question["version"]
                status = await conn.fetchval(
                    "SELECT question_generation.enqueue_question($1, $2::jsonb, $3, $4::jsonb)",
                    task_id, json.dumps(question), result["request_id"], previous,
                )
                if status in {"VERSION_CONFLICT", "SUPERSEDED"}:
                    raise QueueConflict(f"题目 {question_id} v{version} 已被替代，或与待审版本不一致。")
                receipts[question_id, version] = {"question_id": question_id, "version": version, "status": status}
    except QueueConflict as error:
        return JSONResponse(failure_result("QUEUE_VERSION_CONFLICT", str(error), result["request_id"]), status_code=409)
    except (asyncpg.PostgresError, OSError, TimeoutError):
        return JSONResponse(
            failure_result("QUEUE_UNAVAILABLE", "待审表暂不可用，本次未确认入队，可使用同一请求重试。", result["request_id"]),
            status_code=503,
        )

    return {
        **result,
        "queue_receipts": [receipts[question["question_id"], question["version"]] for question in questions],
    }
