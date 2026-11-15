"""Origin gating and request logging for the shared browser console."""

import json
import pathlib
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from question_generation.ui import QuestionConsole

PUBLIC_ORIGIN = "https://demo.trycloudflare.com"
OPENER = build_opener(ProxyHandler({}))


class ConsoleOriginTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuestionConsole)
        self.server.knowledge = None
        self.server.provider = "local"
        self.server.sample = None
        self.server.public_origin = None
        self.server.log_path = None
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _status(self, path="/", method="GET", *, host=None, origin=None):
        headers = {}
        if host is not None:
            headers["Host"] = host
        if origin is not None:
            headers["Origin"] = origin
        request = Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers)
        try:
            with OPENER.open(request, timeout=5) as response:
                return response.status
        except HTTPError as error:
            error.close()
            return error.code

    def test_loopback_requests_are_served(self):
        self.assertEqual(200, self._status("/"))
        self.assertEqual(200, self._status("/api/workbench"))

    def test_foreign_host_is_rejected(self):
        self.assertEqual(403, self._status("/", host=f"evil.example:{self.port}"))

    def test_foreign_origin_is_rejected_without_public_origin(self):
        self.assertEqual(403, self._status("/api/unknown", "POST", origin=PUBLIC_ORIGIN))

    def test_loopback_origin_is_allowed(self):
        self.assertEqual(404, self._status("/api/unknown", "POST", origin=f"http://127.0.0.1:{self.port}"))

    def test_public_origin_is_allowed_when_configured(self):
        self.server.public_origin = PUBLIC_ORIGIN
        self.assertEqual(404, self._status("/api/unknown", "POST", host="localhost:" + str(self.port),
                                           origin=PUBLIC_ORIGIN))
        self.assertEqual(200, self._status("/", host="demo.trycloudflare.com"))

    def test_other_origins_stay_rejected_after_opt_in(self):
        self.server.public_origin = PUBLIC_ORIGIN
        self.assertEqual(403, self._status("/api/unknown", "POST", host="localhost:" + str(self.port),
                                           origin="https://evil.example"))

    def _post(self, path, payload, *, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        request = Request(f"http://127.0.0.1:{self.port}{path}", method="POST",
                          data=json.dumps(payload).encode(), headers=headers)
        try:
            with OPENER.open(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except HTTPError as error:
            body = error.read().decode("utf-8")
            error.close()
            return error.code, body

    def _records(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_failed_request_is_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            log = pathlib.Path(folder) / "requests.jsonl"
            self.server.log_path = log
            status, body = self._post("/api/author", {}, origin=f"http://127.0.0.1:{self.port}")
            self.assertEqual(200, status)
            self.assertEqual("INVALID_REQUEST", json.loads(body)["status"])
            records = self._records(log)
            self.assertEqual(1, len(records))
            record = records[0]
            self.assertEqual("INVALID_REQUEST", record["status"])
            self.assertEqual({}, record["request"])
            self.assertEqual("local", record["provider"])
            self.assertEqual([], record["events"])
            self.assertIn("elapsed_seconds", record)
            self.assertIn("finished_at", record)

    def test_stream_failure_is_logged_with_events(self):
        with tempfile.TemporaryDirectory() as folder:
            log = pathlib.Path(folder) / "requests.jsonl"
            self.server.log_path = log
            status, body = self._post("/api/author/stream", {}, origin=f"http://127.0.0.1:{self.port}")
            self.assertEqual(200, status)
            self.assertIn("INVALID_REQUEST", body)
            records = self._records(log)
            self.assertEqual(1, len(records))
            self.assertEqual("INVALID_REQUEST", records[0]["status"])
            self.assertEqual({}, records[0]["request"])

    def test_no_log_file_written_when_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            log = pathlib.Path(folder) / "requests.jsonl"
            self._post("/api/author", {}, origin=f"http://127.0.0.1:{self.port}")
            self.assertFalse(log.exists())


if __name__ == "__main__":
    unittest.main()
