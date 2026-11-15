from exam_checker.services.generated_question_service import GeneratedQuestionImportService


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
