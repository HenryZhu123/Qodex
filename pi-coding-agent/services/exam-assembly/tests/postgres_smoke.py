"""Opt-in, isolated PostgreSQL fixture test. PASS fixtures are synthetic, not real reviews.

EXAM_ASSEMBLY_TEST_DATABASE_URL must name a dedicated assembly_test database.
Never points at the team's qodex database and never invokes a model or parsing API.
"""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import text

from exam_checker.api.app import create_app as create_bank_app
from exam_checker.config import Settings
from exam_checker.database.connection import Database
from exam_checker.database.models import Base, ExamDocumentRow, QuestionBankRow, QuestionReviewRow, QuestionVersionRow
from exam_assembly_service.app import create_app
from exam_assembly_service.repository import HttpQuestionBankRepository


async def main():
    url = os.environ["EXAM_ASSEMBLY_TEST_DATABASE_URL"]
    if not url.endswith("/assembly_test"):
        raise ValueError("Only the isolated /assembly_test database is permitted")
    database = Database(url)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    doc_id = "assembly_fixture_" + uuid4().hex
    subject = doc_id
    document = dict(document_id=doc_id, paper=dict(subject=subject), root_node_ids=["q1"],
                    nodes={"q1": dict(id="q1", type="question", question_number="1", question_text="fixture")},
                    source=dict(file_name="synthetic-test-only", provider_task_id="fixture", markdown_sha256="fixture"))
    ids = []
    async with database.sessions.begin() as session:
        session.add(ExamDocumentRow(document_id=doc_id, document_json=document))
    for index in range(2):
        record_id, version_id, review_id = uuid4(), uuid4(), uuid4()
        ids.append(str(record_id))
        question_id = f"q{index + 1}"
        stems = ["栈中依次压入甲和乙后，首先弹出的是哪个元素？", "对一个空栈执行出栈操作，通常会发生什么情况？"]
        choices = [["乙", "甲", "无法确定", "栈为空"], ["下溢", "上溢", "队列扩容", "图遍历"]]
        q = dict(document_id=doc_id, question_id=question_id, question_number=str(index+1),
                 question_type="single_choice", question_text=stems[index], options=choices[index],
                 answer_text="A", points=2, subject=subject, paper_title="合成联调测试", section_titles=[],
                 numbering_path=[], numbering_description="", reference="")
        review = dict(document_id=doc_id, question_id=question_id, question_number=str(index+1),
                      question_version_id=str(version_id), review_id=str(review_id),
                      question=dict(reference="", detection_content=q["question_text"]),
                      review=dict(status="PASS", checks=[], summary=dict(has_error=False, total_errors=0, errors=[]),
                                  timing_ms=dict(routing=0, specialist_checks=0, total=0)))
        async with database.sessions.begin() as session:
            session.add(QuestionVersionRow(version_id=version_id, document_id=doc_id, question_id=question_id,
                        version_number=1, revision_source="PARSED", question_json=q))
        async with database.sessions.begin() as session:
            session.add(QuestionReviewRow(review_id=review_id, document_id=doc_id, question_id=question_id,
                                         question_version_id=version_id, review_json=review))
        async with database.sessions.begin() as session:
            session.add(QuestionBankRow(record_id=record_id, document_id=doc_id, question_id=question_id,
                        source_review_id=review_id, source_version_id=version_id,
                        question_json=dict(document_id=doc_id, question_id=question_id, review_status="PASS", question=q,
                                           metadata=dict(difficulty="easy", knowledge_points=["栈"]))))

    async def snapshot():
        result = {}
        async with database.sessions() as session:
            for table in ("exam_documents", "question_versions", "question_reviews", "question_bank"):
                # Fixed test-only table names; no user-supplied SQL.
                result[table] = await session.scalar(text(
                    f"SELECT md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY row_to_json(t)::text), '')) FROM {table} t"))
        return result

    before = await snapshot()
    bank_app = create_bank_app(replace(Settings.from_env(), database_url=url))
    output = Path(os.environ.get("EXAM_ASSEMBLY_TEST_OUTPUT_DIR", "outputs/postgres_smoke"))
    async with bank_app.router.lifespan_context(bank_app):
        async with httpx.AsyncClient(base_url="http://bank", transport=httpx.ASGITransport(app=bank_app)) as bank_client:
            repository = HttpQuestionBankRepository(bank_client)
            app = create_app(repository, output)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(base_url="http://assembly", transport=httpx.ASGITransport(app=app)) as client:
                    req = dict(request_id="postgres_smoke", subject=subject, question_count=2,
                               question_type_counts={"single_choice": 2}, question_type_scores={"single_choice": 2},
                               total_score=4, knowledge_point_counts={"栈": 2},
                               difficulty_counts={"easy": 2, "medium": 0, "hard": 0})
                    response = await client.post("/v1/exam-assembly/assemble", json=req)
                    assert response.status_code == 200, response.text
                    result = response.json()
                    assert result["status"] == "STRUCTURAL_PASS", result
                    assert {s["record_id"] for s in result["selected_sources"]} == set(ids)
                    assert Path(result["artifacts"]["student_exam_html"]).is_file()
                    req.update(question_count=3, total_score=6, knowledge_point_counts={"栈": 3},
                               question_type_counts={"single_choice": 3},
                               difficulty_counts={"easy": 3, "medium": 0, "hard": 0})
                    shortage = (await client.post("/v1/exam-assembly/assemble", json=req)).json()
                    assert shortage["status"] == "NEEDS_QUESTIONS", shortage
                    assert shortage["topic_deficits"] == {"栈": 1}
                    assert shortage["deficits"] == [dict(subject=subject, question_type="single_choice",
                        knowledge_point="栈", difficulty="easy", score_per_question=2, missing_count=1)]
                    assert Path(shortage["artifacts"]["replenishment_request"]).is_file()
                    assert "student_exam_html" not in shortage["artifacts"]
    assert before == await snapshot(), "Assembly modified the database"
    summary = dict(status="PASS", fixture_kind="SYNTHETIC_REVIEW_IN_ISOLATED_POSTGRES", real_quality_acceptance=False,
                   question_bank_api="actual exam-checker FastAPI routes + PostgreSQL repositories",
                   selected_record_ids=ids, success_artifacts=result["artifacts"], shortage=shortage["status"],
                   all_source_tables_unchanged=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    await database.close()


if __name__ == "__main__":
    asyncio.run(main())
