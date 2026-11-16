from contextlib import asynccontextmanager
import os
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
import httpx
from .contracts import AssemblyRequest, PaperRequest
from .paper import assemble_paper
from .repository import BankError, HttpQuestionBankRepository
from .service import assemble
from .history import HistoryError, PostgresHistory
from .semantic_selection import ModelReviewer


def create_app(repository=None, output_root=None, history=None, database_url=None, semantic_reviewer=None):
    reviewer = semantic_reviewer
    if reviewer is None and os.getenv("EXAM_ASSEMBLY_SEMANTIC_ENABLED") == "1":
        reviewer = ModelReviewer()
    dsn = database_url if database_url is not None else os.getenv("EXAM_ASSEMBLY_DATABASE_URL", os.getenv("EXAM_CHECKER_DATABASE_URL", ""))
    history_store = history if history is not None else (PostgresHistory(dsn) if dsn else None)
    @asynccontextmanager
    async def lifespan(application):
        if history is None and history_store is not None:
            await history_store.open()
        try:
            async with httpx.AsyncClient(
                base_url=os.getenv("QUESTION_BANK_SERVICE_URL", "http://127.0.0.1:8091").rstrip("/"),
                timeout=float(os.getenv("QUESTION_BANK_TIMEOUT_SECONDS", "30")), trust_env=False,
            ) as client:
                application.state.repository = repository if repository is not None else HttpQuestionBankRepository(client)
                yield
        finally:
            if history is None and history_store is not None:
                await history_store.close()

    application = FastAPI(title="Exam Assembly Service", lifespan=lifespan)
    root = Path(output_root or os.getenv("EXAM_ASSEMBLY_OUTPUT_DIR", "outputs/exam_assembly"))

    @application.get("/health")
    async def health():
        return {"status": "ok", "bank_source": "QUESTION_BANK_API", "mock_fallback": False,
                "semantic_model_enabled": reviewer is not None,
                "semantic_model_call_limit": getattr(reviewer, "max_calls", 8) if reviewer is not None else 0,
                "history_enabled": history_store is not None}

    async def persist(request, result):
        if history_store is not None:
            try:
                result["history"] = await history_store.save(request.model_dump(), result)
            except HistoryError as exc:
                raise HTTPException(503, detail={"status": "TOOL_ERROR", "error_code": "HISTORY_SAVE_FAILED"}) from exc
        return result

    def require_history():
        if history_store is None:
            raise HTTPException(503, detail="Assembly history database is not configured")

    async def stored(exam_id):
        require_history()
        row = await history_store.get(exam_id)
        if row is None:
            raise HTTPException(404, detail="Assembly history not found")
        return row

    @application.get("/v1/exam-assembly/history")
    async def list_history(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        require_history()
        return {"exams": await history_store.list(limit, offset), "limit": limit, "offset": offset}

    @application.get("/v1/exam-assembly/history/{exam_id}")
    async def get_history(exam_id: UUID):
        row = await stored(exam_id)
        report = row["report_json"]
        return {"exam_id": row["exam_id"], "created_at": row["created_at"], "status": row["status"],
                "request": row["request_json"], "validation": report.get("validation"),
                "errors": report.get("errors", []), "deficits": report.get("deficits", []),
                "message": report.get("message"), "error_code": report.get("error_code"),
                "similarity_review": report.get("similarity_review"),
                "semantic_review": report.get("semantic_review"),
                "rejected_records": report.get("rejected_records", []),
                "student_exam": [item["student_json"] for item in row["items"]],
                "selected_sources": [item["source_json"] for item in row["items"]]}

    @application.get("/v1/exam-assembly/history/{exam_id}/answers")
    async def get_answers(exam_id: UUID):
        row = await stored(exam_id)
        return {"exam_id": row["exam_id"], "answer_key": [item["answer_json"] for item in row["items"]]}

    @application.get("/v1/exam-assembly/history/{exam_id}/student.html", response_class=HTMLResponse)
    async def download_student(exam_id: UUID):
        row = await stored(exam_id)
        if row["student_html"] is None:
            raise HTTPException(409, detail="This attempt has no completed exam")
        return HTMLResponse(row["student_html"])

    @application.get("/v1/exam-assembly/history/{exam_id}/answer.html", response_class=HTMLResponse)
    async def download_answer(exam_id: UUID):
        row = await stored(exam_id)
        if row["answer_html"] is None:
            raise HTTPException(409, detail="This attempt has no completed exam")
        return HTMLResponse(row["answer_html"])

    @application.post("/v1/exam-assembly/assemble")
    async def run(request: AssemblyRequest | PaperRequest):
        fields, errors = (None, []) if isinstance(request, PaperRequest) else request.selection_request()
        if errors:
            return await persist(request, {"schema_version": "1.0", "request_id": request.request_id, "status": "INVALID_REQUEST",
                    "mode": "POSTGRES_QUESTION_BANK_API", "errors": errors})
        try:
            if isinstance(request, PaperRequest):
                return await assemble_paper(request.model_dump(), application.state.repository, root, history_store, reviewer)
            return await assemble(fields, application.state.repository, root, pdf=request.export_pdf,
                                  public_request=request.model_dump(),
                                  similarity_decisions=[d.model_dump() for d in request.similarity_decisions], history=history_store)
        except HistoryError as exc:
            raise HTTPException(503, detail={"status": "TOOL_ERROR", "error_code": "HISTORY_SAVE_FAILED"}) from exc
        except BankError as exc:
            result = await persist(request, {"status": "TOOL_ERROR", "error_code": exc.code,
                                "upstream_http_status": exc.status, "detail": exc.detail})
            return JSONResponse(status_code=502, content=result)
        except (OSError, ImportError, ValueError) as exc:
            result = await persist(request, {"status": "TOOL_ERROR", "error_code": "EXPORT_FAILED",
                                             "reason": type(exc).__name__})
            return JSONResponse(status_code=500, content=result)

    return application


app = create_app()
