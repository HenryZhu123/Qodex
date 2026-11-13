"""HTTP bridge for Pi. Successful question packages are queued before returning."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import cache
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Literal

import asyncpg
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from . import observability
from .batch import generate_batch
from .brief_authoring import generate_from_brief
from .comprehensive import generate_comprehensive, revise_comprehensive
from .generation import failure_result, generate_question
from .knowledge import KnowledgeEvidence, with_knowledge
from .material_discovery import discover
from .replenishment import generate_replenishment

OPERATIONS = {
    "single": generate_question,
    "batch": generate_batch,
    "replenishment": generate_replenishment,
    "comprehensive": generate_comprehensive,
    "revise": revise_comprehensive,
}
QUEUE_FAILURE_STATUSES = {
    "KNOWLEDGE_BASE_UNAVAILABLE", "MODEL_UNAVAILABLE", "AUTHORING_CACHE_UNAVAILABLE",
    "AUTHORING_IN_PROGRESS",
}
DEFAULT_MAX_CONCURRENT = 2
ADMISSION_TIMEOUT_SECONDS = 0.5


class QueueConflict(Exception):
    pass


def _max_concurrent() -> int:
    raw = os.environ.get("QUESTION_GENERATION_MAX_CONCURRENT", str(DEFAULT_MAX_CONCURRENT))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_CONCURRENT
    return max(1, value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    observability.configure()
    dsn = os.environ.get("QUESTION_GENERATION_DATABASE_URL")
    if not dsn:
        raise RuntimeError("QUESTION_GENERATION_DATABASE_URL must be set")
    kb_root = os.environ.get("QUESTION_GENERATION_KB_ROOT")
    kb_catalog = os.environ.get("QUESTION_GENERATION_KB_CATALOG")
    if bool(kb_root) != bool(kb_catalog):
        raise RuntimeError("QUESTION_GENERATION_KB_ROOT and QUESTION_GENERATION_KB_CATALOG must be set together")
    app.state.knowledge = KnowledgeEvidence(Path(kb_root), Path(kb_catalog)) if kb_root and kb_catalog else None
    app.state.admission = asyncio.Semaphore(_max_concurrent())
    async with asyncpg.create_pool(dsn, min_size=1, max_size=4, timeout=5, command_timeout=5) as pool:
        app.state.queue_pool = pool
        yield


app = FastAPI(title="Qodex Question Generation", lifespan=lifespan)


def _admission(app: FastAPI) -> asyncio.Semaphore:
    semaphore = getattr(app.state, "admission", None)
    if semaphore is None:
        semaphore = asyncio.Semaphore(_max_concurrent())
        app.state.admission = semaphore
    return semaphore


async def _database_health(app: FastAPI) -> dict:
    pool = getattr(app.state, "queue_pool", None)
    if pool is None:
        return {"ok": False, "reason": "database pool is not configured"}
    try:
        value = await pool.fetchval("SELECT 1")
    except Exception as error:  # noqa: BLE001 - health probes must not raise
        return {"ok": False, "reason": type(error).__name__}
    return {"ok": True} if value == 1 else {"ok": False, "reason": "SELECT 1 returned an unexpected value"}


def _knowledge_health(app: FastAPI) -> dict:
    knowledge = getattr(app.state, "knowledge", None)
    if knowledge is None:
        return {"ok": True, "id": None, "configured": False}
    try:
        return knowledge.sample()
    except Exception as error:  # noqa: BLE001 - a probe must never collapse /health
        return {"ok": False, "reason": type(error).__name__}


def _cache_health() -> dict:
    configured = os.environ.get(
        "QUESTION_GENERATION_AUTHORING_CACHE", ".local/question-generation/authoring-cache.sqlite",
    )
    directory = Path(configured).expanduser().parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".health-", dir=directory):
            pass
    except OSError as error:
        return {"ok": False, "reason": f"{type(error).__name__}: {error}"[:300]}
    return {"ok": True}


def _model_health() -> dict:
    missing = [name for name in ("DEEPSEEK_MODEL", "DEEPSEEK_API_KEY") if not (os.environ.get(name) or "").strip()]
    if missing:
        return {"ok": False, "reason": "missing " + ", ".join(missing)}
    return {"ok": True}


def _component(value: object) -> dict:
    if isinstance(value, dict) and isinstance(value.get("ok"), bool):
        return value
    return {"ok": False, "reason": "invalid health probe result"}


def _sync_probe(probe) -> dict:
    try:
        return _component(probe())
    except Exception as error:  # noqa: BLE001 - a probe must never collapse /health
        return {"ok": False, "reason": type(error).__name__}


async def _health_report(app: FastAPI) -> dict:
    components = {
        "database": _component(await _database_health(app)),
        "knowledge": _component(_knowledge_health(app)),
        "cache": _sync_probe(_cache_health),
        "model": _sync_probe(_model_health),
    }
    return {
        "status": "ok" if all(component["ok"] for component in components.values()) else "degraded",
        **components,
    }


@app.get("/health")
async def health(request: Request) -> dict:
    try:
        return await _health_report(request.app)
    except Exception as error:  # noqa: BLE001 - health must answer 200 with a status
        component = {"ok": False, "reason": type(error).__name__}
        return {
            "status": "degraded", "database": component, "knowledge": component,
            "cache": component, "model": component,
        }


def _generate(operation: str, payload: dict, knowledge: KnowledgeEvidence | None) -> dict:
    if operation == "author":
        return generate_from_brief(payload, knowledge=knowledge)
    if operation == "revise":
        return revise_comprehensive(payload, knowledge=knowledge)
    find_evidence = cache(knowledge.find) if knowledge else lambda subject, topic: []
    discover_evidence = knowledge.discover if knowledge else lambda item: discover(None, item)
    if operation in {"batch", "replenishment"}:
        return OPERATIONS[operation](
            payload, single_generator=lambda item: with_knowledge(
                generate_question, item, find_evidence, discover_evidence=discover_evidence),
        )
    return with_knowledge(OPERATIONS[operation], payload, find_evidence, discover_evidence=discover_evidence)


@app.post("/v1/question-generation/{operation}")
async def submit(
    operation: Literal["single", "batch", "replenishment", "comprehensive", "revise", "author"],
    request: Request,
    payload: dict = Body(),
):
    started = time.monotonic()
    observability.new_trace_id()
    identifier = payload.get("request_id") if isinstance(payload, dict) else None
    observability.event(
        "request.start", operation=operation, request_id=identifier, status="STARTED",
        elapsed_ms=0.0, questions=0, queue_status="not_queued",
    )
    status, questions, queue_status = "ERROR", 0, "not_queued"
    admission = None
    acquired = False
    try:
        admission = _admission(request.app)
        try:
            await asyncio.wait_for(admission.acquire(), timeout=ADMISSION_TIMEOUT_SECONDS)
            acquired = True
        except (TimeoutError, asyncio.TimeoutError):
            status, queue_status = "SERVER_BUSY", "busy"
            return JSONResponse(
                failure_result("SERVER_BUSY", "服务当前并发已满，请稍后重试。", identifier),
                status_code=503,
            )

        result = await asyncio.to_thread(
            _generate, operation, payload, getattr(request.app.state, "knowledge", None),
        )
        status = str(result["status"])
        question_items = result["questions"]
        questions = len(question_items)
        if status in QUEUE_FAILURE_STATUSES:
            return JSONResponse(result, status_code=503)
        if not question_items:
            return result

        previous = json.dumps(payload["current_question"]) if operation == "revise" else None
        receipts = {}
        try:
            async with request.app.state.queue_pool.acquire(timeout=5) as conn, conn.transaction():
                # Lock question IDs in the same order when concurrent batches overlap.
                for question in sorted(question_items, key=lambda item: item["question_id"]):
                    question_id = question["question_id"]
                    version = question["version"]
                    queued = await conn.fetchval(
                        "SELECT question_generation.enqueue_question($1::jsonb, $2, $3::jsonb)",
                        json.dumps(question), result["request_id"], previous,
                    )
                    if queued in {"VERSION_CONFLICT", "SUPERSEDED"}:
                        raise QueueConflict(f"题目 {question_id} v{version} 已被替代，或与待审版本不一致。")
                    receipts[question_id, version] = {"question_id": question_id, "version": version, "status": queued}
        except QueueConflict as error:
            status, queue_status = "QUEUE_VERSION_CONFLICT", "conflict"
            return JSONResponse(failure_result("QUEUE_VERSION_CONFLICT", str(error), result["request_id"]), status_code=409)
        except (asyncpg.PostgresError, OSError, TimeoutError, asyncio.TimeoutError):
            status, queue_status = "QUEUE_UNAVAILABLE", "unavailable"
            return JSONResponse(
                failure_result("QUEUE_UNAVAILABLE", "待审表暂不可用，本次未确认入队，可使用同一请求重试。", result["request_id"]),
                status_code=503,
            )

        receipt_statuses = {receipt["status"] for receipt in receipts.values()}
        queue_status = "queued" if receipt_statuses and receipt_statuses <= {"QUEUED", "ALREADY_QUEUED"} else "partial"
        return {
            **result,
            "queue_receipts": [receipts[question["question_id"], question["version"]] for question in question_items],
        }
    finally:
        if acquired and admission is not None:
            admission.release()
        observability.event(
            "request.end", operation=operation, request_id=identifier, status=status,
            elapsed_ms=round((time.monotonic() - started) * 1000, 1),
            questions=questions, queue_status=queue_status,
        )
