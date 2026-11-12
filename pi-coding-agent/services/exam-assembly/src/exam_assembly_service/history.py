"""Append-only assembly snapshots, separate from the accepted question bank."""
import json
from pathlib import Path
from uuid import uuid4

import asyncpg


class HistoryError(Exception):
    pass


def snapshots(result):
    if result["status"] != "STRUCTURAL_PASS":
        return []
    students, answers, sources = (result[key] for key in ("student_exam", "answer_key", "selected_sources"))
    if not (len(students) == len(answers) == len(sources)):
        raise ValueError("History snapshot lengths differ")
    items = []
    for position, (student, answer, source) in enumerate(zip(students, answers, sources, strict=True), 1):
        if student["question_id"] != answer["question_id"] or student["question_id"] != source["record_id"]:
            raise ValueError("History snapshot identities differ")
        items.append((position, source, student, answer))
    return items


class PostgresHistory:
    def __init__(self, dsn):
        self.dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        self.pool = None

    async def open(self):
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=4, command_timeout=15)
        try:
            async with self.pool.acquire() as conn:
                ready = await conn.fetchval("SELECT to_regclass('assembled_exams') IS NOT NULL AND to_regclass('assembled_exam_items') IS NOT NULL")
                if not ready:
                    raise HistoryError("Apply exam-checker Alembic migrations before starting history")
        except Exception:
            await self.close()
            raise

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def save(self, request, result):
        try:
            items = snapshots(result)
            html = {}
            if items:
                for name in ("student_exam_html", "answer_key_html"):
                    html[name] = Path(result["artifacts"][name]).read_text(encoding="utf-8")
            exam_id = uuid4()
            async with self.pool.acquire() as conn, conn.transaction():
                created = await conn.fetchval(
                    """INSERT INTO assembled_exams
                    (exam_id, request_id, subject, status, request_json, report_json, student_html, answer_html)
                    VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8) RETURNING created_at""",
                    exam_id, request["request_id"], request["subject"], result["status"],
                    json.dumps(request, ensure_ascii=False), json.dumps(result, ensure_ascii=False),
                    html.get("student_exam_html"), html.get("answer_key_html"),
                )
                for position, source, student, answer in items:
                    await conn.execute("""INSERT INTO assembled_exam_items
                        (exam_id,position,source_json,student_json,answer_json)
                        VALUES ($1,$2,$3::jsonb,$4::jsonb,$5::jsonb)""", exam_id, position,
                        json.dumps(source), json.dumps(student, ensure_ascii=False), json.dumps(answer, ensure_ascii=False))
            return {"status": "STORED", "exam_id": str(exam_id), "created_at": created.isoformat()}
        except Exception as exc:
            # Never send raw connection errors/DSNs to the client.
            raise HistoryError("Assembly history could not be saved") from exc

    async def list(self, limit, offset):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""SELECT exam_id,created_at,request_id,subject,status,
                (request_json->>'question_count')::int AS requested_question_count,
                (request_json->>'total_score')::int AS requested_total_score
                FROM assembled_exams ORDER BY created_at DESC,exam_id DESC LIMIT $1 OFFSET $2""", limit, offset)
        return [dict(row) for row in rows]

    async def get(self, exam_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM assembled_exams WHERE exam_id=$1", exam_id)
            if row is None:
                return None
            items = await conn.fetch("SELECT position,source_json,student_json,answer_json FROM assembled_exam_items WHERE exam_id=$1 ORDER BY position", exam_id)
        result = dict(row)
        for key in ("request_json", "report_json"):
            result[key] = json.loads(result[key])
        result["items"] = [{key: json.loads(value) if key.endswith("_json") else value for key, value in dict(item).items()} for item in items]
        return result
