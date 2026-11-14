import pytest

from exam_checker.domain.models import QuestionNode, QuestionView, SectionNode
from exam_checker.services.document_store import (
    DocumentNotFoundError,
    InMemoryExamDocumentStore,
)
from exam_checker.services.question_import_service import (
    DocumentExistsError,
    DocumentImportError,
    QuestionImportService,
)
from exam_checker.services.question_service import QuestionService
from exam_checker.services.question_version_store import (
    InMemoryQuestionVersionRepository,
)


def question(
    question_id: str, *, document_id: str = "pending-req-1", text: str = "题干"
) -> QuestionView:
    return QuestionView(
        document_id=document_id,
        question_id=question_id,
        question_number="1",
        question_type="single_choice",
        question_text=text,
        options=["A. 1", "B. 2", "C. 3", "D. 4"],
        answer_text="2",
        points=2,
        subject="数据结构",
        paper_title="待审题包",
        section_titles=["栈、队列与数组"],
        numbering_path=[],
        numbering_description="Qodex 生成待审题",
        reference="",
    )


def service() -> QuestionImportService:
    return QuestionImportService(
        store=InMemoryExamDocumentStore(),
        version_repository=InMemoryQuestionVersionRepository(),
        question_service=QuestionService(),
    )


async def test_import_creates_document_and_version_per_question() -> None:
    imports = service()
    result = await imports.import_questions(
        document_id="pending-req-1",
        questions=[question("q1"), question("q2")],
        paper_title="待审题包",
        subject="数据结构",
    )

    assert result.document_id == "pending-req-1"
    assert result.imported == 2
    assert [ref.question_id for ref in result.questions] == ["q1", "q2"]
    document = await imports.store.get("pending-req-1")
    assert document.paper.subject == "数据结构"
    assert document.root_node_ids == ["pending-req-1:section"]
    section = document.nodes["pending-req-1:section"]
    assert isinstance(section, SectionNode)
    assert section.children == ["q1", "q2"]
    assert document.source.parser == "qodex-handoff"
    # Every question must be resolvable through the normal version path.
    for ref in result.questions:
        version = await imports.version_repository.get_latest(
            "pending-req-1", ref.question_id
        )
        assert version.version_id == ref.question_version_id
        assert version.revision_source == "PARSED"
    listed = imports.question_service.list_questions(document)
    assert [item.question_id for item in listed] == ["q1", "q2"]


async def test_existing_document_is_refused_instead_of_overwritten() -> None:
    imports = service()
    await imports.import_questions(
        document_id="pending-req-1", questions=[question("q1")]
    )
    with pytest.raises(DocumentExistsError):
        await imports.import_questions(
            document_id="pending-req-1",
            questions=[question("q1", text="改过的题干")],
        )
    document = await imports.store.get("pending-req-1")
    node = document.nodes["q1"]
    assert isinstance(node, QuestionNode)
    assert node.question_text == "题干"


async def test_identity_and_shape_errors_are_rejected_before_any_write() -> None:
    imports = service()
    with pytest.raises(DocumentImportError):
        await imports.import_questions(document_id="pending-req-1", questions=[])
    with pytest.raises(DocumentImportError):
        await imports.import_questions(
            document_id="../escape", questions=[question("q1")]
        )
    with pytest.raises(DocumentImportError):
        await imports.import_questions(
            document_id="pending-req-1", questions=[question("q1"), question("q1")]
        )
    with pytest.raises(DocumentImportError):
        await imports.import_questions(
            document_id="pending-req-1",
            questions=[question("q1", document_id="other-document")],
        )
    with pytest.raises(DocumentImportError):
        await imports.import_questions(
            document_id="pending-req-1", questions=[question("q1", text="   ")]
        )
    with pytest.raises(DocumentNotFoundError):
        await imports.store.get("pending-req-1")


async def test_subject_falls_back_to_the_question_and_refuses_mixed_documents() -> None:
    imports = service()
    await imports.import_questions(
        document_id="pending-subject-1",
        questions=[question("q1", document_id="pending-subject-1")],
    )
    document = await imports.store.get("pending-subject-1")
    # The review service derives every question's subject from the paper.
    assert document.paper.subject == "数据结构"
    assert imports.question_service.get_question(document, "q1").subject == "数据结构"

    other = QuestionView(**{**question("q2", document_id="pending-subject-2").model_dump(),
                            "subject": "操作系统"})
    with pytest.raises(DocumentImportError) as caught:
        await imports.import_questions(
            document_id="pending-subject-2",
            questions=[question("q1", document_id="pending-subject-2"), other],
        )
    assert "学科不一致" in str(caught.value)
