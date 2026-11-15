"""Reliability regressions for caching, deadlines, health and structured logs.

These tests use temporary SQLite files and scripted callables; no model API and
no PostgreSQL are required.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch

from question_generation import observability
from question_generation.authoring import cached_authoring
from question_generation.knowledge import KnowledgeEvidence
from question_generation.model_client import (
    PIPELINE_DEADLINE,
    JsonModel,
    ModelError,
    complete_stage,
    pipeline_timeout_seconds,
)

ROOT = Path(__file__).resolve().parents[1]

try:  # FastAPI/asyncpg are optional for the default test environment.
    from question_generation import service as question_service
    SERVICE_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - exercised only without service deps
    question_service = None
    SERVICE_IMPORT_ERROR = error


def success(request_id: str) -> dict:
    return {
        "schema_version": "0.1",
        "request_id": request_id,
        "status": "GENERATED",
        "questions": [{"question_id": "q-" + request_id, "version": 1}],
    }


class FakeModel:
    base_url = "https://fixture.invalid"
    model = "fake-model"
    reasoning_effort = "high"
    max_output_tokens = 16384
    stage_reasoning_effort: dict[str, str] = {}
    stage_output_tokens: dict[str, int] = {}
    stage_timeout_seconds: dict[str, int] = {}

    def __init__(self):
        self.usage: list[dict] = []
        self.calls = 0

    def complete(self, system: str, payload: dict) -> dict:
        self.calls += 1
        return {}


class Run:
    """Scripted stand-in for an authoring pipeline."""

    def __init__(self, *, delay: float = 0.0, result: dict | None = None, error: BaseException | None = None):
        self.delay = delay
        self.result = result
        self.error = error
        self.calls = 0
        self.lock = threading.Lock()
        self.deadlines: list[float | None] = []

    def __call__(self, payload: dict, model: FakeModel) -> dict:
        with self.lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        self.deadlines.append(PIPELINE_DEADLINE.get())
        if self.error is not None:
            raise self.error
        return self.result if self.result is not None else success(payload["request_id"])


class CacheTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "cache.sqlite"
        self.payload = {"schema_version": "0.1", "request_id": "r-1", "seed": 7}
        self.model = FakeModel()

    def call(self, run, payload: dict | None = None, **kwargs) -> dict:
        return cached_authoring(
            payload if payload is not None else self.payload,
            "test-version",
            run,
            client=self.model,
            cache_path=self.path,
            **kwargs,
        )

    def test_different_digests_run_concurrently(self):
        run = Run(delay=0.8)
        payloads = [
            {**self.payload, "request_id": "r-a"},
            {**self.payload, "request_id": "r-b"},
        ]
        started = time.monotonic()
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(lambda item: self.call(run, item), payloads))
        elapsed = time.monotonic() - started
        self.assertEqual([result["request_id"] for result in results], ["r-a", "r-b"])
        self.assertEqual(run.calls, 2)
        # Serialized model work would need about 1.6s; concurrent work about 0.8s.
        self.assertLess(elapsed, 1.5)

    def test_same_digest_three_way_concurrency_runs_once(self):
        run = Run(delay=0.25)
        with ThreadPoolExecutor(3) as executor:
            results = list(executor.map(lambda _: self.call(run), range(3)))
        self.assertEqual(run.calls, 1)
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(results[0]["status"], "GENERATED")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM results").fetchone()[0], 1)

    def test_cache_hit_does_not_wait_for_a_writer_lock(self):
        first = self.call(Run())
        self.assertEqual(first["status"], "GENERATED")
        blocker = sqlite3.connect(self.path)
        try:
            blocker.execute("BEGIN IMMEDIATE")
            blocker.execute("INSERT INTO results VALUES ('held', '{}')")
            started = time.monotonic()
            hit = self.call(Run(error=AssertionError("cached run must not execute")))
            elapsed = time.monotonic() - started
        finally:
            blocker.rollback()
            blocker.close()
        self.assertEqual(hit, first)
        self.assertLess(elapsed, 0.2)

    def test_cache_salt_changes_the_digest(self):
        run = Run()
        self.assertEqual(self.call(run)["status"], "GENERATED")
        self.assertEqual(run.calls, 1)
        self.call(run)
        self.assertEqual(run.calls, 1)
        self.call(run, cache_salt="salt-one")
        self.assertEqual(run.calls, 2)
        self.call(run, cache_salt="salt-two")
        self.assertEqual(run.calls, 3)
        self.call(run, cache_salt="salt-one")
        self.assertEqual(run.calls, 3)

    def test_failure_results_are_not_cached(self):
        failure = {
            "schema_version": "0.1", "request_id": "r-1", "status": "SELF_CHECK_FAILED",
            "questions": [], "message": "scripted failure",
        }
        run = Run(result=failure)
        for _ in range(2):
            self.assertEqual(self.call(run)["status"], "SELF_CHECK_FAILED")
        self.assertEqual(run.calls, 2)
        if self.path.exists():
            with sqlite3.connect(self.path) as db:
                table = db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'results'",
                ).fetchone()
                count = db.execute("SELECT COUNT(*) FROM results").fetchone()[0] if table else 0
        else:
            count = 0
        self.assertEqual(count, 0)

    def test_cache_io_error_is_classified(self):
        blocker = self.path.parent / "not-a-directory"
        blocker.write_text("x", encoding="utf-8")
        run = Run()
        result = cached_authoring(
            self.payload, "test-version", run, client=self.model,
            cache_path=blocker / "cache.sqlite",
        )
        self.assertEqual(result["status"], "AUTHORING_CACHE_UNAVAILABLE")
        self.assertEqual(result["authoring_report"]["cache_error"], "CACHE_IO")
        self.assertEqual(run.calls, 0)

    def test_waiter_times_out_with_authoring_in_progress(self):
        started = threading.Event()
        release = threading.Event()

        def blocking_run(payload, model):
            started.set()
            release.wait(timeout=2)
            return success(payload["request_id"])

        with patch.dict(os.environ, {"QUESTION_GENERATION_CACHE_WAIT_SECONDS": "0.05"}):
            with ThreadPoolExecutor(1) as executor:
                owner = executor.submit(self.call, blocking_run)
                self.assertTrue(started.wait(timeout=1))
                began = time.monotonic()
                waited = self.call(blocking_run)
                elapsed = time.monotonic() - began
                release.set()
                owned = owner.result(timeout=2)
        self.assertEqual(waited["status"], "AUTHORING_IN_PROGRESS")
        self.assertEqual(waited["questions"], [])
        self.assertLess(elapsed, 0.5)
        self.assertEqual(owned["status"], "GENERATED")


    def test_waiter_is_bounded_by_the_pipeline_deadline(self):
        started = threading.Event()
        release = threading.Event()

        def blocking_run(payload, model):
            started.set()
            release.wait(timeout=2)
            return success(payload["request_id"])

        with patch.dict(os.environ, {"QUESTION_GENERATION_PIPELINE_TIMEOUT_SECONDS": "0.05"}):
            with ThreadPoolExecutor(1) as executor:
                owner = executor.submit(self.call, blocking_run)
                self.assertTrue(started.wait(timeout=1))
                began = time.monotonic()
                waited = self.call(blocking_run)
                elapsed = time.monotonic() - began
                release.set()
                owned = owner.result(timeout=2)
        self.assertEqual(waited["status"], "AUTHORING_IN_PROGRESS")
        self.assertLess(elapsed, 0.5)
        self.assertEqual(owned["status"], "GENERATED")


class DeadlineTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "cache.sqlite"
        self.model = FakeModel()
        self.payload = {"schema_version": "0.1", "request_id": "deadline-1", "seed": 1}

    def test_expired_pipeline_deadline_fails_before_the_model_call(self):
        token = PIPELINE_DEADLINE.set(time.monotonic() - 1)
        try:
            with self.assertRaises(ModelError) as caught:
                complete_stage(self.model, "author", "system", {})
        finally:
            PIPELINE_DEADLINE.reset(token)
        error = caught.exception
        self.assertEqual(error.diagnostics["code"], "response_timeout")
        self.assertEqual(error.diagnostics["response_issue"], "pipeline_deadline")
        self.assertEqual(error.diagnostics["stage"], "author")
        self.assertEqual(self.model.calls, 0)

    def test_cached_authoring_sets_and_resets_the_pipeline_deadline(self):
        observed = []

        def run(payload, model):
            observed.append(PIPELINE_DEADLINE.get())
            return success(payload["request_id"])

        with patch.dict(os.environ, {"QUESTION_GENERATION_PIPELINE_TIMEOUT_SECONDS": "30"}):
            result = cached_authoring(
                self.payload, "test-version", run, client=self.model, cache_path=self.path,
            )
        self.assertEqual(result["status"], "GENERATED")
        self.assertIsNotNone(observed[0])
        self.assertGreater(observed[0], time.monotonic() - 1)
        self.assertLessEqual(observed[0], time.monotonic() + 30.5)
        self.assertIsNone(PIPELINE_DEADLINE.get())

    def test_default_pipeline_timeout_and_invalid_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QUESTION_GENERATION_PIPELINE_TIMEOUT_SECONDS", None)
            self.assertEqual(pipeline_timeout_seconds(), 900.0)
        with patch.dict(os.environ, {"QUESTION_GENERATION_PIPELINE_TIMEOUT_SECONDS": "not-a-number"}):
            self.assertEqual(pipeline_timeout_seconds(), 900.0)
        with patch.dict(os.environ, {"QUESTION_GENERATION_PIPELINE_TIMEOUT_SECONDS": "0"}):
            self.assertEqual(pipeline_timeout_seconds(), 900.0)

    def test_deadline_that_expires_mid_pipeline_returns_model_unavailable(self):
        def slow_run(payload, model):
            time.sleep(0.05)
            complete_stage(model, "author", "system", {})
            return success(payload["request_id"])

        with patch.dict(os.environ, {"QUESTION_GENERATION_PIPELINE_TIMEOUT_SECONDS": "0.01"}):
            result = cached_authoring(
                self.payload, "test-version", slow_run, client=self.model, cache_path=self.path,
            )
        self.assertEqual(result["status"], "MODEL_UNAVAILABLE")
        self.assertEqual(result["questions"], [])
        failure = result["authoring_report"]["model_failure"]
        self.assertEqual(failure["response_issue"], "pipeline_deadline")
        self.assertEqual(failure["stage"], "author")
        self.assertEqual(self.model.calls, 0)


class KnowledgeSampleTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        subject = self.root / "operating_system"
        subject.mkdir()
        self.index = subject / "kb.sqlite"
        self.text = "Synthetic fixture for the knowledge health probe."
        self.source_hash = sha256(b"synthetic source").hexdigest()
        with sqlite3.connect(self.index) as connection:
            connection.executescript("""
                CREATE TABLE documents (doc_id TEXT PRIMARY KEY, source_hash TEXT);
                CREATE TABLE chunks (
                    chunk_id TEXT PRIMARY KEY, doc_id TEXT, content TEXT, heading_path TEXT,
                    page_start INTEGER, page_end INTEGER, metadata_json TEXT
                );
            """)
            connection.execute("INSERT INTO documents VALUES (?, ?)", ("os-demo", self.source_hash))
            connection.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                               ("section-1", "os-demo", self.text, "Paging", 3, 4, "{}"))
        self.entry = {
            "subject": "operating_systems", "topic": "single_level_paging",
            "database": "kb.sqlite", "doc_id": "os-demo", "chunk_id": "section-1",
            "source": "https://example.invalid/synthetic-paging",
            "edition": "synthetic edition",
            "source_sha256": self.source_hash,
            "content_sha256": sha256(self.text.encode()).hexdigest(),
            "summary": "Synthetic fixture only.",
            "rules": ["split_address", "map_virtual_page", "preserve_offset"],
        }
        self.catalog = self.root / "catalog.json"

    def provider(self, **changes) -> KnowledgeEvidence:
        entry = {**self.entry, **changes}
        self.catalog.write_text(
            json.dumps({"schema_version": "0.1", "entries": [entry]}), encoding="utf-8",
        )
        return KnowledgeEvidence(self.root, self.catalog)

    def test_sample_reads_a_catalogued_chunk(self):
        component = self.provider().sample()
        self.assertTrue(component["ok"])
        self.assertTrue(component["id"].startswith("kb:"))

    def test_sample_reports_a_missing_database_without_raising(self):
        component = self.provider(database="kb_missing.sqlite").sample()
        self.assertFalse(component["ok"])
        self.assertIn("reason", component)
        self.assertFalse((self.index.parent / "kb_missing.sqlite").exists())

    def test_sample_reports_a_deleted_database_without_raising(self):
        provider = self.provider()
        self.index.unlink()
        component = provider.sample()
        self.assertFalse(component["ok"])
        self.assertIn("reason", component)


class ObservabilityTests(TestCase):
    def setUp(self):
        import logging

        self.logger = logging.getLogger(observability.LOGGER_NAME)
        self.addCleanup(setattr, self.logger, "handlers", list(self.logger.handlers))
        self.addCleanup(setattr, self.logger, "level", self.logger.level)
        self.addCleanup(setattr, self.logger, "propagate", self.logger.propagate)

    def test_event_updates_snapshot_and_trace_id(self):
        before = observability.snapshot().get("resilience.test.event", 0)
        trace = observability.new_trace_id()
        observability.event("resilience.test.event", status="ok")
        self.assertEqual(observability.snapshot().get("resilience.test.event"), before + 1)
        self.assertEqual(observability.trace_id.get(), trace)
        observability.trace_id.set(None)

    def test_event_reaches_an_existing_handler(self):
        with self.assertLogs(observability.LOGGER_NAME, level="INFO") as captured:
            observability.new_trace_id()
            observability.event("resilience.test.log", value=1)
        self.assertTrue(any("resilience.test.log" in line for line in captured.output))
        observability.trace_id.set(None)

    def test_configure_installs_one_json_handler(self):
        logger = observability.configure("CRITICAL")
        handlers = [handler for handler in logger.handlers
                    if getattr(handler, "_question_generation_json_handler", False)]
        self.assertEqual(len(handlers), 1)
        observability.configure("CRITICAL")
        handlers = [handler for handler in logger.handlers
                    if getattr(handler, "_question_generation_json_handler", False)]
        self.assertEqual(len(handlers), 1)


class _FakePool:
    def __init__(self, value=1, error: BaseException | None = None):
        self.value = value
        self.error = error

    async def fetchval(self, query: str):
        if self.error is not None:
            raise self.error
        return self.value


class _FakeKnowledge:
    def sample(self) -> dict:
        return {"ok": True, "id": "kb:test"}


class _BrokenKnowledge:
    def sample(self) -> dict:
        return {"ok": False, "reason": "fixture chunk unreadable"}


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, status: str = "QUEUED"):
        self.status = status

    def transaction(self):
        return _FakeTransaction()

    async def fetchval(self, query: str, *args):
        return self.status


class _FakeAcquire:
    def __init__(self, connection: _FakeConnection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeQueuePool:
    def __init__(self, status: str = "QUEUED"):
        self.connection = _FakeConnection(status)

    def acquire(self, timeout=None):
        return _FakeAcquire(self.connection)


class ModelTransportTests(TestCase):
    def client(self):
        return JsonModel(base_url="https://api.deepseek.com", model="fixture", api_key="fixture")

    def test_stream_body_requests_stream_usage(self):
        body = json.loads(self.client()._request_body("sys", {"x": 1}, True))
        self.assertIs(body["stream"], True)
        self.assertEqual(body["stream_options"], {"include_usage": True})

    def test_nonstream_body_omits_stream_options(self):
        body = json.loads(self.client()._request_body("sys", {"x": 1}, False))
        self.assertIs(body["stream"], False)
        self.assertNotIn("stream_options", body)

    def test_stream_can_be_disabled_from_env(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_MODEL": "fixture", "DEEPSEEK_API_KEY": "fixture",
            "QUESTION_GENERATION_STREAM": "0",
        }, clear=False):
            self.assertFalse(JsonModel.from_env().stream)

    def test_official_deepseek_defaults_to_non_streaming(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_MODEL": "deepseek-flash", "DEEPSEEK_API_KEY": "fixture",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        }, clear=False):
            os.environ.pop("QUESTION_GENERATION_STREAM", None)
            self.assertFalse(JsonModel.from_env().stream)

    def test_other_gateway_keeps_streaming_by_default(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_MODEL": "fixture", "DEEPSEEK_API_KEY": "fixture",
            "DEEPSEEK_BASE_URL": "https://gateway.example/v1",
        }, clear=False):
            os.environ.pop("QUESTION_GENERATION_STREAM", None)
            self.assertTrue(JsonModel.from_env().stream)


class StreamFallbackTests(TestCase):
    def test_stalled_stream_falls_back_to_non_streaming_once(self):
        from io import BytesIO
        from unittest.mock import patch

        class Stalled(BytesIO):
            def read1(self, size=None):
                raise TimeoutError("stream stalled")

        valid = b'{"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}'
        model = JsonModel(base_url="https://fixture.invalid", model="test", api_key="fixture",
                          max_retries=0)
        with patch("question_generation.model_client.build_opener") as opener:
            opener.return_value.open.side_effect = [Stalled(b""), BytesIO(valid)]
            self.assertEqual(model.complete("json", {}), {})
            self.assertEqual(opener.return_value.open.call_count, 2)


@skipUnless(question_service is not None, f"service dependencies unavailable: {SERVICE_IMPORT_ERROR}")
class ServiceTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def test_health_reports_ok_and_degraded_components(self):
        state = SimpleNamespace(queue_pool=_FakePool(1), knowledge=_FakeKnowledge())
        app = SimpleNamespace(state=state)
        cache = str(Path(self.directory.name) / "authoring-cache.sqlite")
        env = {
            "DEEPSEEK_MODEL": "fixture-model",
            "DEEPSEEK_API_KEY": "fixture-key",
            "QUESTION_GENERATION_AUTHORING_CACHE": cache,
        }
        with patch.dict(os.environ, env):
            healthy = asyncio.run(question_service._health_report(app))
        self.assertEqual(healthy["status"], "ok")
        self.assertEqual(set(healthy), {"status", "database", "knowledge", "cache", "model"})
        self.assertTrue(all(component["ok"] for component in healthy.values() if isinstance(component, dict)))

        state.queue_pool = _FakePool(error=RuntimeError("database down"))
        with patch.dict(os.environ, env):
            degraded = asyncio.run(question_service._health_report(app))
        self.assertEqual(degraded["status"], "degraded")
        self.assertFalse(degraded["database"]["ok"])

    def test_health_reports_degraded_when_knowledge_probe_fails(self):
        state = SimpleNamespace(queue_pool=_FakePool(1), knowledge=_BrokenKnowledge())
        app = SimpleNamespace(state=state)
        env = {
            "DEEPSEEK_MODEL": "fixture-model",
            "DEEPSEEK_API_KEY": "fixture-key",
            "QUESTION_GENERATION_AUTHORING_CACHE": str(Path(self.directory.name) / "authoring-cache.sqlite"),
        }
        with patch.dict(os.environ, env):
            report = asyncio.run(question_service._health_report(app))
        self.assertEqual(report["status"], "degraded")
        self.assertFalse(report["knowledge"]["ok"])

    def test_health_without_cache_directory_is_degraded_not_raising(self):
        state = SimpleNamespace(queue_pool=_FakePool(1), knowledge=None)
        app = SimpleNamespace(state=state)
        blocker = Path(self.directory.name) / "not-a-directory"
        blocker.write_text("x", encoding="utf-8")
        env = {
            "DEEPSEEK_MODEL": "fixture-model",
            "DEEPSEEK_API_KEY": "fixture-key",
            "QUESTION_GENERATION_AUTHORING_CACHE": str(blocker / "cache.sqlite"),
        }
        with patch.dict(os.environ, env):
            report = asyncio.run(question_service._health_report(app))
        self.assertEqual(report["status"], "degraded")
        self.assertFalse(report["cache"]["ok"])

    def test_submit_returns_503_when_admission_is_saturated(self):
        from starlette.requests import Request

        class BusyAdmission:
            def __init__(self):
                self.released = 0

            async def acquire(self):
                await asyncio.sleep(5)
                return True

            def release(self):
                self.released += 1

        app = question_service.app
        app.state.admission = BusyAdmission()
        previous_knowledge = getattr(app.state, "knowledge", None)
        app.state.knowledge = None
        self.addCleanup(setattr, app.state, "admission", None)
        self.addCleanup(setattr, app.state, "knowledge", previous_knowledge)
        scope = {
            "type": "http", "http_version": "1.1", "method": "POST",
            "scheme": "http", "path": "/v1/question-generation/single",
            "root_path": "", "query_string": b"", "headers": [],
            "server": ("test", 80), "client": ("test", 1),
            "app": app, "state": {},
        }
        request = Request(scope)
        with patch.object(question_service, "ADMISSION_TIMEOUT_SECONDS", 0.01):
            response = asyncio.run(question_service.submit(
                "single", request, {"request_id": "busy-request"},
            ))
        self.assertEqual(response.status_code, 503)
        body = json.loads(response.body)
        self.assertEqual(body["status"], "SERVER_BUSY")
        self.assertEqual(body["questions"], [])
        self.assertEqual(app.state.admission.released, 0)

    def test_generate_routes_a_deterministic_request(self):
        request = json.loads((ROOT / "question_generation" / "examples" / "paging.json").read_text(encoding="utf-8"))
        result = question_service._generate("single", request, None)
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(len(result["questions"]), 1)

    def test_submit_queues_a_successful_question_and_returns_receipts(self):
        from starlette.requests import Request

        app = question_service.app
        previous_pool = getattr(app.state, "queue_pool", None)
        previous_knowledge = getattr(app.state, "knowledge", None)
        previous_admission = getattr(app.state, "admission", None)
        self.addCleanup(setattr, app.state, "queue_pool", previous_pool)
        self.addCleanup(setattr, app.state, "knowledge", previous_knowledge)
        self.addCleanup(setattr, app.state, "admission", previous_admission)
        app.state.admission = None
        app.state.knowledge = None
        app.state.queue_pool = _FakeQueuePool()
        payload = json.loads((ROOT / "question_generation" / "examples" / "paging.json").read_text(encoding="utf-8"))
        scope = {
            "type": "http", "http_version": "1.1", "method": "POST",
            "scheme": "http", "path": "/v1/question-generation/single",
            "root_path": "", "query_string": b"", "headers": [],
            "server": ("test", 80), "client": ("test", 1),
            "app": app, "state": {},
        }
        response = asyncio.run(question_service.submit("single", Request(scope), payload))
        self.assertEqual(response["status"], "GENERATED")
        self.assertEqual(len(response["questions"]), 1)
        self.assertEqual(response["queue_receipts"][0]["status"], "QUEUED")

    @skipUnless(importlib.util.find_spec("httpx") is not None, "httpx is not installed")
    def test_health_route_stays_http_200_when_degraded(self):
        from fastapi.testclient import TestClient

        app = question_service.app
        previous_pool = getattr(app.state, "queue_pool", None)
        previous_knowledge = getattr(app.state, "knowledge", None)
        self.addCleanup(setattr, app.state, "queue_pool", previous_pool)
        self.addCleanup(setattr, app.state, "knowledge", previous_knowledge)
        app.state.queue_pool = _FakePool(error=RuntimeError("database down"))
        app.state.knowledge = None
        env = {
            "DEEPSEEK_MODEL": "fixture-model",
            "DEEPSEEK_API_KEY": "fixture-key",
            "QUESTION_GENERATION_AUTHORING_CACHE": str(Path(self.directory.name) / "authoring-cache.sqlite"),
        }
        with patch.dict(os.environ, env):
            # Without the context manager TestClient does not run lifespan, so
            # no PostgreSQL connection is attempted.
            response = TestClient(app).get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
