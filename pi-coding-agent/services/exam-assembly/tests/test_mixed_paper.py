"""Offline integration fixtures only: never represent these as real reviewed questions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
import httpx
import pytest

from exam_assembly_service.app import create_app
from exam_assembly_service.contracts import PaperRequest
from exam_assembly_service.history import snapshots
from exam_assembly_service.paper import allocate, assemble_paper, convert_paper
from exam_assembly_service.repository import BankError, HttpQuestionBankRepository
from exam_assembly_service.service import assemble
from exam_checker.services.generated_question_service import GeneratedQuestionImportService


def item(index, subject="数据结构", score=2, part_scores=None):
    identity = f"TEST_ONLY_{index}"
    token = hashlib.sha256(identity.encode()).hexdigest()
    question = dict(task_id="TEST_ONLY_task", question_id=identity, subject=subject,
                    question_type="comprehensive" if part_scores else "single_choice",
                    points=score, question_text=token, reference="", options=[token+c for c in "ABC"],
                    answer_text="A")
    if part_scores:
        question.update(options=[], answer_text="TEST_ONLY_solution",
            parts=[dict(id=f"p{i}", prompt=hashlib.sha256(f"{identity}part{i}".encode()).hexdigest(), score=s)
                   for i, s in enumerate(part_scores)],
            grading=dict(grading_policy="TEST_ONLY_policy", parts=[dict(part_id=f"p{i}", solution=f"SECRET_{identity}_{i}",
                scoring_points=[dict(id="s1", points=s, criterion="TEST_ONLY_criterion", expected="TEST_ONLY_expected")],
                equivalent_methods=[], depends_on=[]) for i, s in enumerate(part_scores)]))
    entry = dict(record_id=identity, task_id="TEST_ONLY_task", question_id=identity, version=1,
                 question_json=dict(task_id="TEST_ONLY_task", question_id=identity, version=1,
                    review_status="PASS", question=question, metadata=dict(difficulty="medium", knowledge_points=["TEST_ONLY_topic"])))
    return entry


class Repository:
    def __init__(self, entries, *, complete=True, fail=None, stale=False):
        self.entries, self.complete, self.fail, self.stale = entries, complete, fail, stale
        self.reads = {}

    async def search_candidates(self, request):
        return self.entries, self.complete

    async def state(self, entry):
        identifier = entry["record_id"]
        self.reads[identifier] = self.reads.get(identifier, 0) + 1
        if identifier == self.fail:
            raise BankError("QUESTION_BANK_UNAVAILABLE", status=503)
        return dict(task_id=entry["task_id"], question_id=entry["question_id"],
                    version=2 if self.stale and self.reads[identifier] > 1 else 1,
                    question=deepcopy(entry["question_json"]["question"]),
                    review=dict(status="PASS", review_id="TEST_ONLY_review", errors=[], unresolved_checks=[]),
                    question_bank=dict(status="STORED", record_id=identifier))


def plan(entries):
    slots = [dict(subject=e["question_json"]["question"]["subject"],
                  question_type=e["question_json"]["question"]["question_type"],
                  score=e["question_json"]["question"]["points"],
                  part_scores=[p["score"] for p in e["question_json"]["question"].get("parts", [])]) for e in entries]
    return dict(schema_version="2.0", request_id="TEST_ONLY_paper", subject="408", question_count=len(slots),
                total_score=sum(s["score"] for s in slots), slots=slots, export_pdf=False)


@pytest.mark.asyncio
async def test_408_40_plus_7_four_subjects_and_heterogeneous_scores(tmp_path):
    subjects = ["数据结构", "计算机组成原理", "操作系统", "计算机网络"]
    entries = [item(i, subjects[i // 10]) for i in range(40)]
    for i, score in enumerate([8, 10, 10, 10, 10, 10, 12]):
        entries.append(item(40+i, subjects[i % 4], score, [3, score-3]))
    request = PaperRequest.model_validate(plan(entries)).model_dump()
    result = await assemble_paper(request, Repository(entries), tmp_path)
    assert result["status"] == "STRUCTURAL_PASS"
    assert "answer_key" not in result
    report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))
    assert len(snapshots(report)) == 47
    assert sum(q["score"] for q in report["student_exam"]) == 150
    assert all(q["question_type"] == "single_choice" for q in report["student_exam"][:40])
    assert all(q["question_type"] == "comprehensive" for q in report["student_exam"][40:])
    student = Path(result["artifacts"]["student_exam_html"]).read_text(encoding="utf-8")
    answer = Path(result["artifacts"]["answer_key_html"]).read_text(encoding="utf-8")
    assert "SECRET_" not in student and "SECRET_" in answer
    assert "综合应用题" in student and "（3分）" in student


@pytest.mark.asyncio
async def test_dirty_record_and_network_failure_do_not_poison_valid_paper(tmp_path):
    good = item(1)
    bad = item(2, score=10, part_scores=[3, 7])
    bad["question_json"]["question"]["grading"]["parts"][0]["scoring_points"][0]["points"] = 2
    repo = Repository([good, bad, {"record_id": "bad-id"}, None, item(3)], fail="TEST_ONLY_3")
    result = await assemble_paper(plan([good]), repo, tmp_path)
    assert result["status"] == "STRUCTURAL_PASS"
    assert len(result["rejected_records"]) == 4
    assert result["pool_complete"] is False


@pytest.mark.asyncio
async def test_uncertain_pool_stale_sources_and_no_partial_export(tmp_path):
    entry = item(1)
    for repo, expected in [(Repository([], complete=False), "UNRESOLVED"),
                           (Repository([]), "NEEDS_QUESTIONS"),
                           (Repository([entry], fail=entry["record_id"]), "UNRESOLVED"),
                           (Repository([entry], stale=True), "UNRESOLVED")]:
        with tempfile.TemporaryDirectory() as folder:
            result = await assemble_paper(plan([entry]), repo, Path(folder))
            assert result["status"] == expected
            assert not list(Path(folder).rglob("*.html"))


@pytest.mark.asyncio
async def test_reference_escaped_and_three_options_supported(tmp_path):
    entry = item(1)
    entry["question_json"]["question"]["reference"] = "共同材料 <script>alert(1)</script>"
    result = await assemble_paper(plan([entry]), Repository([entry]), tmp_path)
    assert result["status"] == "STRUCTURAL_PASS"
    html = Path(result["artifacts"]["student_exam_html"]).read_text(encoding="utf-8")
    assert "&lt;script&gt;" in html and "<script>" not in html


def test_assignment_revisits_flexible_candidate_without_reuse():
    q1 = dict(subject="数据结构", question_type="single_choice", score=2, knowledge_points=["a", "b"], difficulty="easy", parts=[])
    q2 = {**q1, "knowledge_points": ["a"]}
    slots = [dict(subject="数据结构", question_type="single_choice", score=2, knowledge_point=k) for k in ("a", "b")]
    allocated = allocate(slots, [q1, q2])
    assert allocated[0] is q2 and allocated[1] is q1


def test_api_accepts_v2_and_rejects_inconsistent_scores_before_query(tmp_path):
    entry = item(1, score=10, part_scores=[3, 7])
    with TestClient(create_app(Repository([entry]), tmp_path, database_url="")) as client:
        request = plan([entry])
        assert client.post("/v1/exam-assembly/assemble", json=request).json()["status"] == "STRUCTURAL_PASS"
        request["slots"][0]["part_scores"] = [3, 8]
        assert client.post("/v1/exam-assembly/assemble", json=request).status_code == 422


def test_generated_comprehensive_preserves_parts_answers_and_old_defaults():
    parts = [dict(id="p1", prompt="TEST_ONLY_prompt", score=3), dict(id="p2", prompt="TEST_ONLY_other", score=7)]
    teacher = dict(grading_policy="TEST_ONLY", parts=[dict(part_id=p["id"], solution="SECRET", scoring_points=[], depends_on=[]) for p in parts])
    package = dict(metadata=dict(subject="data_structures", question_type="comprehensive", score=10),
                   student_view=dict(stem="TEST_ONLY_stem", parts=parts), instructor_view=teacher)
    view = GeneratedQuestionImportService._to_question_view("t", "q", 1, package)
    assert view.parts == parts and view.grading == teacher
    assert view.student_stem == "TEST_ONLY_stem" and "3分" in view.question_text
    assert "SECRET" in view.answer_text and "SECRET" not in view.question_text
    package = dict(metadata=dict(subject="data_structures", question_type="single_choice"),
                   student_view=dict(stem="TEST_ONLY", options=[dict(id="A", text="a")]), instructor_view=dict(correct_option_id="A"))
    old = GeneratedQuestionImportService._to_question_view("t", "q", 1, package).model_dump()
    assert "parts" not in old and "grading" not in old and "student_stem" not in old


@pytest.mark.asyncio
async def test_http_adapter_isolates_malformed_conflicting_records():
    entry = item(1)
    conflict = deepcopy(entry)
    conflict["version"] = 2
    def handler(request):
        return httpx.Response(200, json={"questions": [entry, None, conflict]})
    async with httpx.AsyncClient(base_url="http://bank", transport=httpx.MockTransport(handler)) as client:
        rows, complete = await HttpQuestionBankRepository(client).search_candidates(dict(
            subject="数据结构", question_type="single_choice", topic_counts={"": 1}, difficulty_counts={"": 1}))
    assert complete and len(rows) == 2
    assert rows[0]["rejection_reason"] == "Conflicting record snapshots"


@pytest.mark.asyncio
async def test_legacy_service_skips_broken_identity(tmp_path):
    from test_service import fixtures, FakeRepository
    request, entry, state = fixtures()
    repo = FakeRepository(entry, state)
    repo.entries.extend([None, {"record_id": "invalid"}])
    # Real adapter raises when it tries to read a missing source identity.
    async def current(e):
        e["task_id"]
        return state
    repo.state = current
    result = await assemble(request, repo, tmp_path)
    assert result["status"] == "STRUCTURAL_PASS" and len(result["rejected_records"]) == 2


@pytest.mark.asyncio
async def test_similarity_decisions_are_content_and_version_bound(tmp_path):
    first, second = item(10), item(11)
    first["question_json"]["question"]["question_text"] = "共同情境：分析该系统中的页面映射关系，给出本题所要求的唯一结论甲。"
    second["question_json"]["question"]["question_text"] = "共同情境：分析该系统中的页面映射关系，给出本题所要求的唯一结论乙。"
    request = plan([first, second])
    pending = await assemble_paper(request, Repository([first, second]), tmp_path)
    assert pending["status"] == "UNRESOLVED"
    template = json.loads(Path(pending["artifacts"]["similarity_decisions_template"]).read_text(encoding="utf-8"))
    assert len(template) == 1
    request["similarity_decisions"] = [{**template[0], "reviewer": "TEST_ONLY_human", "verdict": "DISTINCT", "reason": "TEST_ONLY_explicit_decision"}]
    accepted = await assemble_paper(request, Repository([first, second]), tmp_path)
    assert accepted["status"] == "STRUCTURAL_PASS"
    second["question_json"]["question"]["reference"] = "已改变的共同材料"
    stale = await assemble_paper(request, Repository([first, second]), tmp_path)
    assert stale["status"] == "UNRESOLVED"
    assert stale["similarity_review"]["status"] == "INVALID_OR_STALE_DECISIONS"


@pytest.mark.asyncio
async def test_old_comprehensive_and_unsupported_images_are_isolated(tmp_path):
    good, old, image = item(1), item(2, score=8, part_scores=[3, 5]), item(3)
    del old["question_json"]["question"]["parts"]
    image["question_json"]["question"]["reference"] = "![图](private.png)"
    result = await assemble_paper(plan([good]), Repository([good, old, image]), tmp_path)
    assert result["status"] == "STRUCTURAL_PASS"
    assert len(result["rejected_records"]) == 2


class FilteringRepository(Repository):
    async def search_candidates(self, request):
        wanted = request["question_type"]
        return [e for e in self.entries
                if e["question_json"]["question"]["question_type"] == wanted], True


@pytest.mark.asyncio
async def test_deterministic_comprehensive_application_fills_a_v2_slot(tmp_path):
    entry = item(2, score=10, part_scores=[2, 3, 5])
    entry["question_json"]["question"]["question_type"] = "comprehensive_application"
    # Deterministic comprehensive answers are numeric, not prose strings.
    entry["question_json"]["question"]["grading"]["parts"][0]["scoring_points"][0]["expected"] = 11
    entry["question_json"]["question"]["grading"]["parts"][1]["scoring_points"][0]["expected"] = {"offset": 0}
    entry["question_json"]["question"]["grading"]["parts"][2]["scoring_points"][0]["expected"] = False
    request = dict(schema_version="2.0", request_id="TEST_ONLY_deterministic",
                   subject="408", question_count=1, total_score=10,
                   slots=[dict(subject="数据结构", question_type="comprehensive",
                               score=10, part_scores=[2, 3, 5])], export_pdf=False)
    result = await assemble_paper(PaperRequest.model_validate(request).model_dump(),
                                  FilteringRepository([entry]), tmp_path)
    assert result["status"] == "STRUCTURAL_PASS", result
    report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))
    assert report["student_exam"][0]["question_type"] == "comprehensive"
    assert [p["score"] for p in report["student_exam"][0]["parts"]] == [2, 3, 5]
