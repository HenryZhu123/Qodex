from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import httpx
from .contracts import AssemblyRequest
from .repository import BankError, HttpQuestionBankRepository
from .service import assemble


def create_app(repository=None, output_root=None):
    @asynccontextmanager
    async def lifespan(application):
        if repository is not None:
            application.state.repository = repository
            yield
        else:
            # TUN routing remains an OS/client concern; no environmental HTTP proxy for local bank traffic.
            async with httpx.AsyncClient(
                base_url=os.getenv("QUESTION_BANK_SERVICE_URL", "http://127.0.0.1:8091").rstrip("/"),
                timeout=float(os.getenv("QUESTION_BANK_TIMEOUT_SECONDS", "30")), trust_env=False,
            ) as client:
                application.state.repository = HttpQuestionBankRepository(client)
                yield

    application = FastAPI(title="Exam Assembly Service", lifespan=lifespan)
    root = Path(output_root or os.getenv("EXAM_ASSEMBLY_OUTPUT_DIR", "outputs/exam_assembly"))

    @application.get("/health")
    async def health():
        return {"status": "ok", "bank_source": "QUESTION_BANK_API", "mock_fallback": False}

    @application.post("/v1/exam-assembly/assemble")
    async def run(request: AssemblyRequest):
        fields, errors = request.selection_request()
        if errors:
            return {"schema_version": "1.0", "request_id": request.request_id, "status": "INVALID_REQUEST",
                    "mode": "POSTGRES_QUESTION_BANK_API", "errors": errors}
        try:
            return await assemble(fields, application.state.repository, root, pdf=request.export_pdf,
                                  public_request=request.model_dump(),
                                  similarity_decisions=[d.model_dump() for d in request.similarity_decisions])
        except BankError as exc:
            return JSONResponse(status_code=502, content={"status": "TOOL_ERROR", "error_code": exc.code,
                                "upstream_http_status": exc.status, "detail": exc.detail})
        except (OSError, ImportError, ValueError) as exc:
            raise HTTPException(status_code=500, detail={"status": "TOOL_ERROR", "error_code": "EXPORT_FAILED",
                                                       "reason": type(exc).__name__}) from exc

    return application


app = create_app()
