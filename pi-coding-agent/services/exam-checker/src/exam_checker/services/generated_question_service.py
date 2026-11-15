from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.models import QuestionView, StoredQuestionVersion
from .persistence import QuestionVersionNotFoundError, QuestionVersionRepository


class GeneratedQuestionImportService:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        version_repository: QuestionVersionRepository,
    ) -> None:
        self.sessions = sessions
        self.version_repository = version_repository

    async def import_version(
        self, task_id: str, question_id: str, version: int | None
    ) -> StoredQuestionVersion:
        try:
            if version is None:
                return await self.version_repository.get_latest(task_id, question_id)
            return await self.version_repository.get(task_id, question_id, version)
        except QuestionVersionNotFoundError:
            pass

        generation_task_id = UUID(task_id)
        task_id = str(generation_task_id)
        if version is None:
            async with self.sessions() as session:
                version = await session.scalar(
                    text(
                        """
                        SELECT version
                        FROM question_generation.current_pending_questions
                        WHERE task_id = CAST(:task_id AS uuid) AND question_id = :question_id
                        """
                    ),
                    {"task_id": task_id, "question_id": question_id},
                )
            if version is None:
                raise QuestionVersionNotFoundError((task_id, question_id))
        async with self.sessions() as session:
            package = await session.scalar(
                text(
                    """
                    SELECT question_json
                    FROM question_generation.pending_questions
                    WHERE task_id = CAST(:task_id AS uuid)
                      AND question_id = :question_id
                      AND version = :version
                    """
                ),
                {"task_id": task_id, "question_id": question_id, "version": version},
            )
        if package is None:
            raise QuestionVersionNotFoundError((task_id, question_id, version))
        question = self._to_question_view(task_id, question_id, version, package)
        return await self.version_repository.import_generated(
            task_id=task_id,
            question_id=question_id,
            version=version,
            question=question,
        )

    @staticmethod
    def _to_question_view(
        task_id: str, question_id: str, version: int, package: dict[str, object]
    ) -> QuestionView:
        metadata = package.get("metadata")
        student = package.get("student_view")
        instructor = package.get("instructor_view")
        if not isinstance(metadata, dict) or not isinstance(student, dict) or not isinstance(instructor, dict):
            raise ValueError("Generated question package is missing metadata or views")

        stem = student.get("stem")
        if not isinstance(stem, str) or not stem.strip():
            raise ValueError("Generated question package has no student stem")
        options: list[str] = []
        option_rows = student.get("options", [])
        if isinstance(option_rows, list):
            for option in option_rows:
                if isinstance(option, dict) and isinstance(option.get("text"), str):
                    options.append(option["text"])
        parts = student.get("parts", [])
        if isinstance(parts, list) and parts:
            part_text = [
                f"{part.get('id', index + 1)}. {part.get('prompt', '')}"
                for index, part in enumerate(parts)
                if isinstance(part, dict)
            ]
            stem = "\n".join([stem, *part_text])

        evidence = package.get("evidence_refs", [])
        reference = "\n".join(
            f"{item.get('source', '')} {item.get('anchor', '')}".strip()
            for item in evidence
            if isinstance(item, dict)
        )
        score = metadata.get("score")
        return QuestionView(
            task_id=task_id,
            question_id=question_id,
            question_number=str(package.get("slot_id") or question_id),
            question_type=str(metadata.get("question_type") or ""),
            question_text=stem,
            options=options,
            answer_text=json.dumps(instructor, ensure_ascii=False, sort_keys=True),
            points=float(score) if isinstance(score, (int, float)) else None,
            subject=str(metadata.get("subject") or ""),
            paper_title=f"AI generation task {task_id}",
            section_titles=[str(metadata["topic"])] if metadata.get("topic") else [],
            numbering_path=[],
            numbering_description=f"Generated version {version}",
            reference=reference,
        )
