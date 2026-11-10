from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from exam_checker.integrations.mineru_agent import ExtractedDocument, MinerULimitError
from exam_checker.parsing.normalizer import ExamDocumentNormalizer
from exam_checker.services.document_parse_service import DocumentParseService
from exam_checker.services.document_store import InMemoryExamDocumentStore
from exam_checker.services.question_service import QuestionService
from exam_checker.services.question_version_store import (
    InMemoryQuestionVersionRepository,
)


def make_pdf(page_count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class FakeMinerU:
    called = False

    async def parse_file(self, file_bytes: bytes, file_name: str) -> ExtractedDocument:
        self.called = True
        assert file_name == "exam.pdf"
        return ExtractedDocument(
            markdown="# 选择题\n1. 测试题",
            provider="mineru-agent",
            provider_task_id="task-1",
            source_file_name=file_name,
        )


class FakeExtractor:
    async def extract(self, markdown: str):
        assert markdown.startswith("# 选择题")
        return {
            "paper": {"title": "测试卷", "subject": "计算机"},
            "questions": [
                {
                    "id": 1,
                    "title": "选择题",
                    "children": [{"id": 1, "content": "测试题"}],
                }
            ],
        }


class UnexpectedWordConverter:
    def convert_to_pdf(self, file_bytes: bytes, original_filename: str) -> bytes:
        raise AssertionError("PDF input must not invoke LibreOffice")


@pytest.mark.asyncio
async def test_parse_service_builds_and_stores_exam_document() -> None:
    mineru = FakeMinerU()
    store = InMemoryExamDocumentStore()
    versions = InMemoryQuestionVersionRepository()
    service = DocumentParseService(
        mineru=mineru,
        structure_extractor=FakeExtractor(),
        normalizer=ExamDocumentNormalizer(),
        store=store,
        word_converter=UnexpectedWordConverter(),
        question_service=QuestionService(),
        version_repository=versions,
    )

    document = await service.parse(make_pdf(), "exam.pdf")

    assert mineru.called
    assert document.paper.subject == "计算机"
    assert document.nodes["question_1"].question_text == "测试题"
    assert await store.get(document.document_id) == document
    version = await versions.get_latest(document.document_id, "question_1")
    assert version.version_number == 1
    assert version.revision_source == "PARSED"
    assert version.question.question_text == "测试题"


@pytest.mark.asyncio
async def test_parse_service_rejects_pdf_over_twenty_pages_before_upload() -> None:
    mineru = FakeMinerU()
    service = DocumentParseService(
        mineru=mineru,
        structure_extractor=FakeExtractor(),
        normalizer=ExamDocumentNormalizer(),
        store=InMemoryExamDocumentStore(),
        word_converter=UnexpectedWordConverter(),
    )

    with pytest.raises(MinerULimitError, match="21 pages"):
        await service.parse(make_pdf(21), "exam.pdf")

    assert not mineru.called


def test_select_structure_source_uses_richer_embedded_text(monkeypatch) -> None:
    embedded = "题目正文" * 60
    monkeypatch.setattr(
        DocumentParseService,
        "_embedded_pdf_text",
        staticmethod(lambda _: embedded),
    )

    selected = DocumentParseService._select_structure_source(
        b"pdf", "题目正文" * 40
    )

    assert selected == embedded


def test_select_structure_source_keeps_mineru_for_sparse_text_layer(
    monkeypatch,
) -> None:
    mineru = "完整题目" * 60
    monkeypatch.setattr(
        DocumentParseService,
        "_embedded_pdf_text",
        staticmethod(lambda _: "页眉" * 20),
    )

    selected = DocumentParseService._select_structure_source(b"pdf", mineru)

    assert selected == mineru


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_embedded_text_route_requires_opt_in_and_records_provenance(
    monkeypatch, enabled: bool,
) -> None:
    text = "# 选择题\n" + "完整的题干与答案" * 40
    monkeypatch.setattr(
        DocumentParseService, "_complete_embedded_pdf_text", staticmethod(lambda _: text)
    )
    mineru = FakeMinerU()
    store = InMemoryExamDocumentStore()
    versions = InMemoryQuestionVersionRepository()
    service = DocumentParseService(
        mineru=mineru, structure_extractor=FakeExtractor(),
        normalizer=ExamDocumentNormalizer(), store=store,
        word_converter=UnexpectedWordConverter(),
        question_service=QuestionService(), version_repository=versions,
        prefer_embedded_pdf_text=enabled,
    )
    document = await service.parse(make_pdf(), "exam.pdf")
    assert mineru.called is (not enabled)
    assert document.source.parser == ("embedded-pdf-text" if enabled else "mineru-agent")
    assert document.source.provider_task_id.startswith("local-sha256:" if enabled else "task-")
    assert await store.get(document.document_id) == document
    version = await versions.get_latest(document.document_id, "question_1")
    assert version.revision_source == "PARSED"


@pytest.mark.asyncio
async def test_opt_in_sparse_pdf_still_uses_mineru() -> None:
    mineru = FakeMinerU()
    service = DocumentParseService(
        mineru=mineru, structure_extractor=FakeExtractor(),
        normalizer=ExamDocumentNormalizer(), store=InMemoryExamDocumentStore(),
        word_converter=UnexpectedWordConverter(), prefer_embedded_pdf_text=True,
    )
    document = await service.parse(make_pdf(), "exam.pdf")
    assert mineru.called
    assert document.source.parser == "mineru-agent"


@pytest.mark.parametrize("sparse_page,has_image", [(False, False), (True, False), (False, True)])
def test_complete_embedded_text_checks_every_page_and_images(
    monkeypatch, sparse_page: bool, has_image: bool,
) -> None:
    from exam_checker.services import document_parse_service

    complete = "完整的题目文字" * 40
    pages = [
        SimpleNamespace(extract_text=lambda: complete, images=[]),
        SimpleNamespace(
            extract_text=lambda: "页眉" if sparse_page else complete,
            images=[object()] if has_image else [],
        ),
    ]
    monkeypatch.setattr(document_parse_service, "PdfReader", lambda _: SimpleNamespace(pages=pages))
    result = DocumentParseService._complete_embedded_pdf_text(b"pdf")
    assert bool(result) is (not sparse_page and not has_image)


@pytest.mark.parametrize("raw,expected", [("true", True), ("false", False), ("1", True), ("0", False)])
def test_embedded_text_setting(monkeypatch, raw: str, expected: bool) -> None:
    from exam_checker.config import Settings

    monkeypatch.setenv("EXAM_CHECKER_PREFER_EMBEDDED_PDF_TEXT", raw)
    assert Settings.from_env().prefer_embedded_pdf_text is expected


def test_embedded_text_setting_rejects_typo(monkeypatch) -> None:
    from exam_checker.config import Settings

    monkeypatch.setenv("EXAM_CHECKER_PREFER_EMBEDDED_PDF_TEXT", "treu")
    with pytest.raises(ValueError, match="PREFER_EMBEDDED_PDF_TEXT"):
        Settings.from_env()
