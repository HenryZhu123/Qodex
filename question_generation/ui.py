"""Loopback-only browser console for the local question generator."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path

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


def preview_result(payload, knowledge, provider):
    if not isinstance(payload, dict) or set(payload) - {"request", "cloud_confirmed"}:
        return failure_result("INVALID_REQUEST", "试题台请求格式不正确。")
    if provider == "deepseek" and payload.get("cloud_confirmed") is not True:
        return failure_result("CLOUD_CONFIRMATION_REQUIRED", "请确认本次云端试题请求。")
    request = payload.get("request")
    try:
        trace = PreviewTrace(JsonModel.from_env() if provider == "deepseek" else LocalPreviewModel())
    except ModelError as error:
        return failure_result("MODEL_UNAVAILABLE", str(error))
    result = generate_from_brief(request, knowledge=knowledge, client=trace,
                                 cache_path=".local/question-generation/workbench/cache.sqlite")
    preview = {"model": trace.model, "last_stage": trace.stage, "calls": trace.calls}
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
        if host not in {f"{HOST}:{port}", f"localhost:{port}"} or (
            origin is not None and origin != f"http://{host}"
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

    def do_POST(self) -> None:
        if not self._local_request():
            return
        if self.path not in {"/api/generate", "/api/author"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 65536:
                raise ValueError
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (OSError, ValueError, RecursionError):
            result = failure_result("INVALID_REQUEST", "请求须为不超过 64 KiB 的 UTF-8 JSON。")
            status = HTTPStatus.BAD_REQUEST
        else:
            if self.path == "/api/author":
                result = preview_result(payload, self.server.knowledge, self.server.provider)
            else:
                # The old form exercises the deterministic rule path only.
                if isinstance(payload, dict) and isinstance(payload.get("constraints"), dict) and "authoring" in payload["constraints"]:
                    result = failure_result("UNSUPPORTED_REQUEST", "请在自主命题页提交模型命题请求。")
                else:
                    result = generate_question(payload)
            status = HTTPStatus.OK

        self._send_json(result, status)

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
    args = parser.parse_args()
    try:
        if bool(args.kb_root) != bool(args.kb_catalog):
            raise ValueError("知识库目录和清单须一同提供。")
        knowledge = KnowledgeEvidence(args.kb_root, args.kb_catalog) if args.kb_root else None
        sample = json.loads(args.history_example.read_text(encoding="utf-8")) if args.history_example else None
        if sample is not None and (not isinstance(sample, dict) or sample.get("status") != "GENERATED" or not sample.get("questions")):
            raise ValueError("历史题包须为真实生成成功的结果。")
        server = ThreadingHTTPServer((HOST, args.port), QuestionConsole)
    except (OSError, OverflowError, ValueError) as error:
        parser.exit(1, f"无法启动验证台：{error}\n")

    server.knowledge, server.provider, server.sample = knowledge, args.provider, sample
    with server:
        print(f"408 自主命题验证台 http://{HOST}:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
