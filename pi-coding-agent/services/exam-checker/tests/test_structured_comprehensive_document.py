from copy import deepcopy

import pytest

from exam_checker.domain.models import ExamDocument
from exam_checker.parsing.normalizer import ExamDocumentNormalizer, NormalizationError
from exam_checker.services.question_service import QuestionService


def source():
    return dict(paper=dict(subject="数据结构",title="TEST_ONLY"),questions=[dict(id="42",question_type="comprehensive",content="共同题干",points=10,
        parts=[dict(id="p1",prompt="先回答此问",score=3),dict(id="p2",prompt="再回答此问",score=7)],
        grading=dict(grading_policy="TEST_ONLY",parts=[dict(part_id="p1",solution="SECRET_ONE"),dict(part_id="p2",solution="SECRET_TWO")]),
        answer="SECRET_ONE; SECRET_TWO")])


def normalize(tree):
    return ExamDocumentNormalizer().normalize(tree,source_file_name="TEST_ONLY.json",provider_task_id="TEST_ONLY",markdown="共同题干",parser="structured-source")


def test_comprehensive_document_is_one_question_and_preserves_teacher_fields():
    tree=source()
    document=normalize(tree)
    assert len(document.nodes)==1
    restored=ExamDocument.model_validate(document.model_dump(mode="json"))
    service=QuestionService()
    questions=service.list_questions(restored)
    assert len(questions)==1
    view=questions[0]
    assert view.question_number=="42" and view.points==10
    assert [p["score"] for p in view.parts]==[3,7]
    assert view.student_stem=="共同题干" and view.grading==tree["questions"][0]["grading"]
    payload=service.to_checker_payload_from_view(view).model_dump_json()
    assert "先回答此问" in payload and "再回答此问" in payload and "7分" in payload
    assert "SECRET" not in payload
    assert tree==source(),"Normalization must not mutate source input"


@pytest.mark.parametrize("mutation",["score","identity","missing_answer","duplicate","type"])
def test_invalid_subquestion_structure_fails_before_snapshot_storage(mutation):
    tree=deepcopy(source())
    question=tree["questions"][0]
    if mutation=="score":question["parts"][1]["score"]=8
    elif mutation=="identity":question["grading"]["parts"][1]["part_id"]="unknown"
    elif mutation=="missing_answer":question["grading"]["parts"][0]["solution"]=""
    elif mutation=="duplicate":question["parts"][1]["id"]="p1"
    else:question["question_type"]="single_choice"
    with pytest.raises(NormalizationError):normalize(tree)


def test_legacy_single_choice_document_has_no_new_empty_fields():
    tree=dict(paper=dict(subject="数据结构"),questions=[dict(id="1",content="旧题",points=2,options=["A. 甲","B. 乙"],answer="A",question_type="single_choice")])
    doc=normalize(tree)
    node=next(iter(doc.model_dump()["nodes"].values()))
    view=QuestionService().list_questions(doc)[0].model_dump()
    assert "parts" not in node and "grading" not in node
    assert "parts" not in view and "grading" not in view and view["question_text"]=="旧题"
