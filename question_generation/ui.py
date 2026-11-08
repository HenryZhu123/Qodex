"""Loopback-only browser console for the local question generator."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from .generation import failure_result, generate_question

HOST = "127.0.0.1"
PORT = 8765
PACKAGE = Path(__file__).resolve().parent
ASSETS = {
    "/": (PACKAGE / "web" / "index.html", "text/html"),
    "/ui.css": (PACKAGE / "web" / "ui.css", "text/css"),
    "/ui.js": (PACKAGE / "web" / "ui.js", "text/javascript"),
    "/api/example": (PACKAGE / "examples" / "paging.json", "application/json"),
    "/api/example/stack": (PACKAGE / "examples" / "stack.json", "application/json"),
}


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
        asset = ASSETS.get(self.path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path, content_type = asset
        self._send(HTTPStatus.OK, content_type, path.read_bytes())

    def do_POST(self) -> None:
        if not self._local_request():
            return
        if self.path != "/api/generate":
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
            result = generate_question(payload)
            status = HTTPStatus.OK

        data = json.dumps(result, ensure_ascii=False).encode("utf-8", errors="backslashreplace")
        self._send(status, "application/json", data)


def main() -> None:
    parser = argparse.ArgumentParser(description="打开 408 自主命题本地验证台。")
    parser.add_argument("--port", type=int, default=PORT, help=f"本地端口，默认 {PORT}")
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer((HOST, args.port), QuestionConsole)
    except (OSError, OverflowError) as error:
        parser.exit(1, f"无法启动验证台：{error}\n")

    with server:
        print(f"408 自主命题验证台 http://{HOST}:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
