"""Origin gating for the loopback browser console shared through a tunnel."""

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


if __name__ == "__main__":
    unittest.main()
