import pytest

from exam_checker.domain.models import QuestionView
from exam_checker.services.generated_question_service import GeneratedQuestionImportService
from exam_checker.services.question_version_store import InMemoryQuestionVersionRepository


def test_generated_package_becomes_task_scoped_question_snapshot() -> None:
    question = GeneratedQuestionImportService._to_question_view(
        "11111111-1111-4111-8111-111111111111",
        "paging-1",
        2,
        {
            "metadata": {
                "subject": "operating_systems",
                "topic": "single_level_paging",
                "question_type": "single_choice",
                "score": 2,
            },
            "student_view": {
                "stem": "虚拟地址对应哪个物理地址？",
                "options": [
                    {"id": "option-1", "text": "0x1000"},
                    {"id": "option-2", "text": "0x2000"},
                ],
            },
            "instructor_view": {
                "correct_option_id": "option-2",
                "explanation": "按页表转换。",
            },
            "evidence_refs": [
                {"source": "OSTEP", "anchor": "Paging"},
            ],
        },
    )

    assert question.task_id == "11111111-1111-4111-8111-111111111111"
    assert question.question_id == "paging-1"
    assert question.question_number == "paging-1"
    assert question.points == 2
    assert question.options == ["0x1000", "0x2000"]
    assert question.section_titles == ["single_level_paging"]
    assert question.reference == "OSTEP Paging"


@pytest.mark.asyncio
async def test_same_generated_version_cannot_be_replaced_with_different_content() -> None:
    repository = InMemoryQuestionVersionRepository()
    original = QuestionView(
        task_id="11111111-1111-4111-8111-111111111111",
        question_id="paging-1",
        question_number="1",
        question_type="single_choice",
        question_text="原题",
        options=["A", "B"],
        answer_text="A",
        points=2,
        subject="operating_systems",
        paper_title="AI generation task",
        section_titles=["paging"],
        numbering_path=[],
        numbering_description="Generated version 1",
        reference="test evidence",
    )
    await repository.import_generated(
        task_id=original.task_id,
        question_id=original.question_id,
        version=1,
        question=original,
    )

    with pytest.raises(ValueError, match="conflicts"):
        await repository.import_generated(
            task_id=original.task_id,
            question_id=original.question_id,
            version=1,
            question=original.model_copy(update={"question_text": "越权覆盖"}),
        )
