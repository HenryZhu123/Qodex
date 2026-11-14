"""Register already-authored questions as one immutable review document.

The review workflow starts from a parsed document, and every parsed document owns a
version per question. Questions produced by the authoring service have no document, so
this service is the missing seam: it builds the same document/version shape from JSON and
leaves review, annotation, ingestion and assembly untouched.

Two deliberate refusals:

* an existing ``document_id`` is rejected instead of overwritten, because the document
  store updates on conflict while the version store inserts on conflict without an update;
  re-importing would silently keep reviewing the old version;
* question identity must be unique inside the payload, so one document cannot hold two
  different questions under the same id.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..domain.models import (
    ExamDocument,
    ImportDocumentResult,
    ImportedQuestionRef,
    PaperMetadata,
    QuestionView,
    SourceMetadata,
)
from ..services.document_store import DocumentNotFoundError

DOCUMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class DocumentImportError(ValueError):
    pass


class DocumentExistsError(ValueError):
    pass


class QuestionImportService:
    def __init__(self, *, store, version_repository, question_service) -> None:
        self.store = store
        self.version_repository = version_repository
        self.question_service = question_service

    async def import_questions(
        self,
        *,
        document_id: str,
        questions: list[QuestionView],
        paper_title: str = "",
        subject: str = "",
        source_name: str = "qodex-pending",
    ) -> ImportDocumentResult:
        if not DOCUMENT_ID_PATTERN.match(document_id or ""):
            raise DocumentImportError("document_id 须为 1–200 位的字母、数字或 . _ : -")
        if not questions:
            raise DocumentImportError("questions 不能为空。")
        identifiers = [question.question_id for question in questions]
        if len(set(identifiers)) != len(identifiers):
            raise DocumentImportError("同一文档内 question_id 必须唯一。")
        subjects = {question.subject.strip() for question in questions if question.subject.strip()}
        if len(subjects) > 1:
            raise DocumentImportError(
                f"同一文档的题目学科不一致：{sorted(subjects)}。"
            )
        # The review service reads subject from the paper, not from each question
        # (question_service.get_question), so an explicit request label wins and the
        # question subject is the fallback.
        resolved_subject = (subject or "").strip() or (next(iter(subjects)) if subjects else "")
        for question in questions:
            if question.document_id != document_id:
                raise DocumentImportError(
                    f"题目 {question.question_id} 的 document_id 与请求不一致。"
                )
            if not question.question_text.strip():
                raise DocumentImportError(f"题目 {question.question_id} 缺少题干。")
        try:
            await self.store.get(document_id)
        except DocumentNotFoundError:
            pass
        else:
            raise DocumentExistsError(
                f"文档 {document_id} 已存在；待审题包请使用包含版本号的新标识。"
            )

        section_id = f"{document_id}:section"
        # Plain payloads keep the section/question union out of the typing layer; the
        # document validator enforces the graph instead.
        nodes: dict[str, Any] = {
            section_id: {
                "type": "section",
                "id": section_id,
                "title": paper_title or "导入题包",
                "numbering_description": "authoring hand-off",
                "children": [question.question_id for question in questions],
            }
        }
        for question in questions:
            nodes[question.question_id] = {
                "type": "question",
                "id": question.question_id,
                "parent_id": section_id,
                "source_id": question.numbering_description,
                "question_number": question.question_number,
                "question_type": question.question_type,
                "question_text": question.question_text,
                "options": list(question.options),
                "answer_text": question.answer_text,
                "points": question.points,
                "reference": question.reference,
                "numbering_path": list(question.numbering_path),
                "numbering_description": question.numbering_description,
            }
        fingerprint = hashlib.sha256(
            json.dumps([question.model_dump(mode="json") for question in questions],
                       ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        document = ExamDocument.model_validate(
            {
                "document_id": document_id,
                "paper": PaperMetadata(title=paper_title or "导入题包", subject=resolved_subject),
                "root_node_ids": [section_id],
                "nodes": nodes,
                "source": SourceMetadata(
                    file_name=f"{source_name}.json",
                    media_type="application/json",
                    parser="qodex-handoff",
                    provider_task_id=source_name,
                    markdown_sha256=fingerprint,
                ),
            }
        )
        # Persist before creating versions: a half-written document would let review
        # resolve a question whose version does not exist yet.
        await self.store.save(document)
        views = self.question_service.list_questions(document)
        await self.version_repository.initialize(views)
        refs = []
        for view in views:
            version = await self.version_repository.get_latest(document_id, view.question_id)
            refs.append(
                ImportedQuestionRef(
                    question_id=view.question_id,
                    question_number=view.question_number,
                    question_version_id=version.version_id,
                )
            )
        return ImportDocumentResult(document_id=document_id, imported=len(refs), questions=refs)
