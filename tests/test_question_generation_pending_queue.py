"""Read-only review-queue listing for the local teacher workspace.

The browser needs to show what is waiting for review without importing a version,
reviewing it or spending a model call. These tests pin the projection, the input
validation and the two failure shapes that must not look like an empty queue.
No PostgreSQL and no model API are required.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest import TestCase, skipUnless

try:  # FastAPI/asyncpg are optional for the default test environment.
    from question_generation import service as question_service
    SERVICE_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - exercised only without service deps
    question_service = None
    SERVICE_IMPORT_ERROR = error


PACKAGE = {
    "question_id": "authored-abc",
    "version": 2,
    "review_status": "PENDING",
    "student_view": {
        "stem": "一棵二叉树的先序序列为 A B D E C F G。",
        "options": [{"id": "A", "text": "E D B G F C A"}, {"id": "B", "text": "D E B F G C A"}],
    },
    "metadata": {
        "subject": "data_structures",
        "topic": "二叉树的遍历",
        "question_type": "single_choice",
        "syllabus_areas": ["ds.trees"],
    },
    "instructor_view": {"correct_option_id": "A", "explanation": "先序首元素是根。"},
}


class _Row(dict):
    """asyncpg returns Records; dict already supports the key access used here."""


class _FakePool:
    def __init__(self, rows=None, total=None, error: BaseException | None = None):
        self.rows = rows or []
        self.total = len(self.rows) if total is None else total
        self.error = error
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, query: str, *args):
        self.calls.append((query, args))
        if self.error is not None:
            raise self.error
        return self.rows

    async def fetchval(self, query: str, *args):
        self.calls.append((query, args))
        if self.error is not None:
            raise self.error
        return self.total


def request_for(pool) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(queue_pool=pool)))


def queued_row(**overrides) -> _Row:
    row = _Row({
        "task_id": "cfe4a758-f990-4fdf-8ea7-7d484456deeb",
        "question_id": "authored-abc",
        "version": 2,
        "request_id": "paging-demo",
        "queued_at": datetime(2026, 11, 16, 7, 51, 2, tzinfo=timezone.utc),
        "question_json": json.dumps(PACKAGE, ensure_ascii=False),
    })
    row.update(overrides)
    return row


@skipUnless(question_service is not None, f"service deps missing: {SERVICE_IMPORT_ERROR}")
class PendingQueueTests(TestCase):
    def call(self, request, **kwargs):
        response = asyncio.run(question_service.pending(request, **kwargs))
        return response, json.loads(response.body)

    def test_lists_current_versions_with_the_student_facing_fields(self):
        pool = _FakePool(rows=[queued_row()], total=37)
        response, body = self.call(request_for(pool))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], "OK")
        self.assertEqual(body["total"], 37)
        self.assertEqual(body["count"], 1)
        question = body["questions"][0]
        self.assertEqual(question["task_id"], "cfe4a758-f990-4fdf-8ea7-7d484456deeb")
        self.assertEqual(question["question_id"], "authored-abc")
        self.assertEqual(question["version"], 2)
        self.assertEqual(question["subject"], "data_structures")
        self.assertEqual(question["topic"], "二叉树的遍历")
        self.assertEqual(question["syllabus_areas"], ["ds.trees"])
        self.assertEqual(question["options"][0], {"id": "A", "text": "E D B G F C A"})
        self.assertTrue(question["stem"].startswith("一棵二叉树"))
        self.assertEqual(question["queued_at"], "2026-11-16T07:51:02+00:00")

    def test_the_list_never_carries_the_answer_or_the_author_artifacts(self):
        _, body = self.call(request_for(_FakePool(rows=[queued_row()])))
        question = body["questions"][0]
        self.assertNotIn("instructor_view", question)
        self.assertNotIn("self_check", question)
        self.assertNotIn("generator", question)
        self.assertNotIn("E D B G F C A", json.dumps(question, ensure_ascii=False).replace(
            json.dumps(question["options"], ensure_ascii=False), "",
        ))
        self.assertNotIn("先序首元素是根", json.dumps(body, ensure_ascii=False))

    def test_superseded_versions_are_excluded_by_the_query(self):
        pool = _FakePool(rows=[queued_row()])
        self.call(request_for(pool))
        self.assertIn("superseded_at IS NULL", pool.calls[0][0])

    def test_filters_by_task_and_subject(self):
        pool = _FakePool(rows=[queued_row()])
        self.call(request_for(pool), task_id="cfe4a758-f990-4fdf-8ea7-7d484456deeb", subject="data_structures")
        query, args = pool.calls[0]
        self.assertIn("p.task_id = $1::uuid", query)
        self.assertIn("p.question_json->'metadata'->>'subject' = $2", query)
        self.assertEqual(args[0], question_service.UUID("cfe4a758-f990-4fdf-8ea7-7d484456deeb"))
        self.assertEqual(args[1], "data_structures")

    def test_rejects_a_limit_outside_the_page_range(self):
        for limit in (0, -1, question_service.PENDING_LIMIT_MAX + 1):
            response, body = self.call(request_for(_FakePool()), limit=limit)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(body["status"], "INVALID_REQUEST")

    def test_rejects_a_task_id_that_is_not_a_uuid(self):
        response, body = self.call(request_for(_FakePool()), task_id="not-a-uuid")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(body["status"], "INVALID_REQUEST")

    def test_a_missing_pool_is_reported_as_unavailable_not_as_an_empty_queue(self):
        response, body = self.call(request_for(None))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["status"], "QUEUE_UNAVAILABLE")

    def test_a_read_failure_is_reported_as_unavailable_not_as_an_empty_queue(self):
        response, body = self.call(request_for(_FakePool(error=RuntimeError("connection reset"))))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["status"], "QUEUE_UNAVAILABLE")
        self.assertNotIn("questions", body)

    def test_a_package_that_does_not_parse_still_lists_its_identity(self):
        pool = _FakePool(rows=[queued_row(question_json="{not json")])
        response, body = self.call(request_for(pool))
        self.assertEqual(response.status_code, 200)
        question = body["questions"][0]
        self.assertEqual(question["question_id"], "authored-abc")
        self.assertEqual(question["stem"], "")
        self.assertEqual(question["options"], [])
