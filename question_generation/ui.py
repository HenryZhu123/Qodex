"""Loopback browser console for the local question generator.

By default every request must come from the loopback interface. Starting the
console with an explicit ``--public-origin`` (for example a temporary tunnel
domain) additionally allows that single origin for shared demos; the default
loopback-only behavior is unchanged.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import threading
import time
from urllib.parse import urlsplit

from .brief_authoring import generate_from_brief
from .generation import failure_result, generate_question
from .knowledge import KnowledgeEvidence
from .model_client import JsonModel, ModelError
from .preview import LocalPreviewModel, PreviewTrace

HOST = "127.0.0.1"
PORT = 8765
PACKAGE = Path(__file__).resolve().parent
ASSETS = {
    "/": (PACKAGE / "web" / "author.html", "text/html"),
    "/rules": (PACKAGE / "web" / "index.html", "text/html"),
    "/ui.css": (PACKAGE / "web" / "ui.css", "text/css"),
    "/ui.js": (PACKAGE / "web" / "ui.js", "text/javascript"),
    "/author.js": (PACKAGE / "web" / "author.js", "text/javascript"),
    "/api/example": (PACKAGE / "examples" / "paging.json", "application/json"),
    "/api/example/stack": (PACKAGE / "examples" / "stack.json", "application/json"),
    "/api/example/cache": (PACKAGE / "examples" / "cache.json", "application/json"),
    "/api/example/subnet": (PACKAGE / "examples" / "subnet.json", "application/json"),
    "/api/example/tcp": (PACKAGE / "examples" / "tcp.json", "application/json"),
}


def _clip(value, limit=600):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    return value


def _stage_summary(stage, result):
    """A small, display-oriented view of one model stage's output."""
    if not isinstance(result, dict):
        return {"text": _clip(str(result), 400)}
    if not result:
        return {}
    if "material_gaps" in result and isinstance(result["material_gaps"], list):
        return {"gaps": [_clip(str(item), 300) for item in result["material_gaps"][:8]]}
    if isinstance(result.get("plan"), dict):
        plan = result["plan"]
        return {
            "topic": _clip(plan.get("topic"), 200), "task": _clip(plan.get("task"), 600),
            "student_evidence": _clip(plan.get("student_evidence"), 600),
            "question_type": plan.get("question_type"), "objective": plan.get("objective"),
            "syllabus_areas": plan.get("syllabus_areas"),
            "evidence_count": len(plan.get("evidence_ids") or []),
            "material_queries": [_clip(str(item.get("query")), 120)
                                 for item in plan.get("material_queries") or [] if isinstance(item, dict)],
        }
    candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else result
    if isinstance(candidate.get("student_view"), dict):
        student = candidate["student_view"]
        parts = student.get("parts") if isinstance(student.get("parts"), list) else []
        options = student.get("options") if isinstance(student.get("options"), list) else []
        return {
            "stem": _clip(student.get("stem"), 1200),
            "shape": (f"综合题 · {len(parts)} 小问" if parts else f"单选题 · {len(options)} 个选项"),
            "parts": [_clip(str(part.get("prompt")), 240) for part in parts[:8] if isinstance(part, dict)],
            "options": [_clip(str(option.get("text")), 240) for option in options[:8] if isinstance(option, dict)],
        }
    if isinstance(result.get("quality"), dict):
        quality = result["quality"]
        return {
            "answer": _clip(result.get("answer"), 60),
            "quality": {key: quality[key] for key in ("answerability", "depth", "distractors", "clarity")
                        if type(quality.get(key)) is int},
            "depth_evidence": _clip(result.get("depth_evidence"), 600),
            "issues": [_clip(str(item), 240) for item in result.get("issues") or [] if isinstance(item, str)][:6],
        }
    if isinstance(result.get("checks"), dict):
        checks = result["checks"]
        return {
            "valid": result.get("valid"),
            "checks": {name: {"passed": value.get("passed"), "reason": _clip(value.get("reason"), 300)}
                       for name, value in checks.items() if isinstance(value, dict)},
            "issues": [_clip(str(item), 240) for item in result.get("issues") or [] if isinstance(item, str)][:6],
            "adversarial_case": _clip(result.get("adversarial_case"), 600),
        }
    return {"text": _clip(json.dumps(result, ensure_ascii=False), 600)}


class ProgressPreviewTrace(PreviewTrace):
    """PreviewTrace that reports each model stage to the workbench stream."""

    def __init__(self, client, emit):
        super().__init__(client)
        self.emit = emit

    def _report(self, event):
        try:
            self.emit(event)
        except Exception:
            pass

    def complete(self, system, payload):
        index = self.calls
        stage = self.stages[index] if index < len(self.stages) else f"扩展阶段 {index + 1}"
        self._report({"type": "stage", "state": "start", "index": index, "stage": stage})
        started = time.monotonic()
        try:
            result = super().complete(system, payload)
        except ModelError as error:
            diagnostics = getattr(error, "diagnostics", {}) or {}
            self._report({"type": "stage", "state": "fail", "index": index, "stage": stage,
                          "elapsed_seconds": round(time.monotonic() - started, 2),
                          "error": str(error), "diagnostics": diagnostics})
            raise
        usage = self.usage[-1] if self.usage else {}
        self._report({"type": "stage", "state": "ok", "index": index, "stage": stage,
                      "elapsed_seconds": usage.get("elapsed_seconds", round(time.monotonic() - started, 2)),
                      "tokens": {key: usage[key] for key in ("prompt_tokens", "completion_tokens",
                                                             "reasoning_tokens") if key in usage},
                      "summary": _stage_summary(stage, result)})
        return result


def preview_result(payload, knowledge, provider, *, progress=None):
    if not isinstance(payload, dict) or set(payload) - {"request", "cloud_confirmed"}:
        return failure_result("INVALID_REQUEST", "试题台请求格式不正确。")
    if provider == "deepseek" and payload.get("cloud_confirmed") is not True:
        return failure_result("CLOUD_CONFIRMATION_REQUIRED", "请确认本次云端试题请求。")
    request = payload.get("request")
    try:
        trace = PreviewTrace(JsonModel.from_env() if provider == "deepseek" else LocalPreviewModel())
    except ModelError as error:
        return failure_result("MODEL_UNAVAILABLE", str(error))
    if progress is not None:
        trace = ProgressPreviewTrace(trace, progress)
    result = generate_from_brief(request, knowledge=knowledge, client=trace,
                                 cache_path=".local/question-generation/workbench/cache.sqlite")
    preview = {"model": trace.model, "last_stage": trace.stage, "calls": trace.calls,
               "usage": trace.usage}
    if result["status"] != "GENERATED":
        if trace.draft:
            preview["unverified_draft"] = trace.draft
        if trace.proposed_plan and not result.get("authoring_report", {}).get("plan"):
            preview["unverified_plan"] = trace.proposed_plan
    return {**result, "preview": preview}


class QuestionConsole(BaseHTTPRequestHandler):
    timeout = 5

    def _send(self, status: HTTPStatus, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(data)

    def _local_request(self) -> bool:
        port = self.server.server_address[1]
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        public_origin = getattr(self.server, "public_origin", None)
        allowed_hosts = {f"{HOST}:{port}", f"localhost:{port}"}
        if public_origin is not None:
            allowed_hosts.add(urlsplit(public_origin).netloc)
        if host not in allowed_hosts or (
            origin is not None and origin != f"http://{host}" and origin != public_origin
        ):
            self.send_error(HTTPStatus.FORBIDDEN)
            return False
        return True

    def do_GET(self) -> None:
        if not self._local_request():
            return
        if self.path == "/api/workbench":
            self._send_json({"provider": self.server.provider, "knowledge": self.server.knowledge is not None,
                             "sample": self.server.sample is not None})
            return
        if self.path == "/api/history-example" and self.server.sample is not None:
            self._send_json(self.server.sample)
            return
        asset = ASSETS.get(self.path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path, content_type = asset
        self._send(HTTPStatus.OK, content_type, path.read_bytes())

    def _read_json(self):
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 65536:
                raise ValueError
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except (OSError, ValueError, RecursionError):
            return None, failure_result("INVALID_REQUEST", "请求须为不超过 64 KiB 的 UTF-8 JSON。")

    def _write_event(self, event) -> None:
        data = json.dumps(event, ensure_ascii=False, default=str)
        self.wfile.write(f"data: {data}\n\n".encode("utf-8", errors="backslashreplace"))
        self.wfile.flush()

    def _stream_author(self) -> None:
        """Run one authoring request and stream stage events as server-sent events."""
        payload, error = self._read_json()
        if error is not None:
            self._send_json(error, HTTPStatus.BAD_REQUEST)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        self.end_headers()
        self.close_connection = True

        events: queue.Queue = queue.Queue()

        def emit(event):
            events.put(event)

        def work():
            try:
                result = preview_result(payload, self.server.knowledge, self.server.provider,
                                        progress=emit)
                emit({"type": "result", "result": result})
            except Exception:
                emit({"type": "error", "message": "命题过程出现未预期错误，本次未确认生成。"})
            finally:
                emit({"type": "done"})

        threading.Thread(target=work, daemon=True, name="authoring-workbench").start()
        try:
            while True:
                try:
                    event = events.get(timeout=10)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._write_event(event)
                if event.get("type") == "done":
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_POST(self) -> None:
        if not self._local_request():
            return
        if self.path not in {"/api/generate", "/api/author", "/api/author/stream"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.path == "/api/author/stream":
            self._stream_author()
            return

        payload, error = self._read_json()
        if error is not None:
            self._send_json(error, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/author":
            result = preview_result(payload, self.server.knowledge, self.server.provider)
        else:
            # The old form exercises the deterministic rule path only.
            if isinstance(payload, dict) and isinstance(payload.get("constraints"), dict) and "authoring" in payload["constraints"]:
                result = failure_result("UNSUPPORTED_REQUEST", "请在自主命题页提交模型命题请求。")
            else:
                result = generate_question(payload)

        self._send_json(result)

    def _send_json(self, result, status=HTTPStatus.OK):
        data = json.dumps(result, ensure_ascii=False).encode("utf-8", errors="backslashreplace")
        self._send(status, "application/json", data)


def main() -> None:
    parser = argparse.ArgumentParser(description="打开 408 自主命题本地验证台。")
    parser.add_argument("--port", type=int, default=PORT, help=f"本地端口，默认 {PORT}")
    parser.add_argument("--provider", choices=("local", "deepseek"), default="local")
    parser.add_argument("--kb-root", type=Path, default=os.environ.get("QUESTION_GENERATION_KB_ROOT"))
    parser.add_argument("--kb-catalog", type=Path, default=os.environ.get("QUESTION_GENERATION_KB_CATALOG"))
    parser.add_argument("--history-example", type=Path, help="用于只读展示的历史模型题包 JSON")
    parser.add_argument(
        "--public-origin",
        default=os.environ.get("QUESTION_CONSOLE_PUBLIC_ORIGIN"),
        help="显式放行一个非本机来源（如临时隧道 https://… 域名），不设置时仅限本机访问。",
    )
    args = parser.parse_args()
    try:
        if bool(args.kb_root) != bool(args.kb_catalog):
            raise ValueError("知识库目录和清单须一同提供。")
        knowledge = KnowledgeEvidence(args.kb_root, args.kb_catalog) if args.kb_root else None
        sample = json.loads(args.history_example.read_text(encoding="utf-8")) if args.history_example else None
        if sample is not None and (not isinstance(sample, dict) or sample.get("status") != "GENERATED" or not sample.get("questions")):
            raise ValueError("历史题包须为真实生成成功的结果。")
        public_origin = None
        if args.public_origin:
            parts = urlsplit(args.public_origin)
            if parts.scheme not in {"https", "http"} or not parts.netloc or parts.path not in {"", "/"}:
                raise ValueError("--public-origin 须为不含路径的绝对来源，如 https://example.trycloudflare.com")
            public_origin = f"{parts.scheme}://{parts.netloc}"
        server = ThreadingHTTPServer((HOST, args.port), QuestionConsole)
    except (OSError, OverflowError, ValueError) as error:
        parser.exit(1, f"无法启动验证台：{error}\n")

    server.knowledge, server.provider, server.sample = knowledge, args.provider, sample
    server.public_origin = public_origin
    with server:
        print(f"408 自主命题验证台 http://{HOST}:{server.server_port}/", flush=True)
        if public_origin:
            print(f"已放行外部来源：{public_origin}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
