from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.models import QuestionView, StoredQuestionVersion
from .persistence import QuestionVersionNotFoundError, QuestionVersionRepository

# The bank and the assembly requests use Chinese subject labels, while the authoring
# request carries the syllabus slug. Normalising at the hand-off keeps one vocabulary
# in the bank instead of teaching every consumer about both spellings.
SUBJECT_LABELS = {
    "data_structures": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_systems": "操作系统",
    "computer_networks": "计算机网络",
}
# 408 single choice is always worth 2 marks, and the authoring package carries no score
# for it; a null score would make assembly reject every generated question.
SINGLE_CHOICE_POINTS = 2.0


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
            generation_task_id = UUID(task_id)
        except (TypeError, ValueError, AttributeError):
            if version is None:
                return await self.version_repository.get_latest(task_id, question_id)
            return await self.version_repository.get(task_id, question_id, version)
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
            for index, option in enumerate(option_rows):
                if isinstance(option, dict) and isinstance(option.get("text"), str):
                    # The review surface is an A-D question, and a bare list of texts is
                    # reported as "missing option identifiers" on every item. Positional
                    # labels keep that independent of the author's internal option ids.
                    label = "ABCD"[index] if index < 4 else str(index + 1)
                    options.append(f"{label}. {option['text']}")
        parts = student.get("parts", [])
        if isinstance(parts, list) and parts:
            part_text = [
                f"{part.get('id', index + 1)}. {part.get('prompt', '')}"
                for index, part in enumerate(parts)
                if isinstance(part, dict)
            ]
            stem = "\n".join([stem, *part_text])

        correct = instructor.get("correct_option_id")
        answer_text = ""
        for option in option_rows if isinstance(option_rows, list) else []:
            if isinstance(option, dict) and option.get("id") == correct and isinstance(option.get("text"), str):
                answer_text = option["text"]
                break
        score = metadata.get("score")
        question_type = str(metadata.get("question_type") or "")
        if score is None and question_type == "single_choice":
            score = SINGLE_CHOICE_POINTS
        subject = str(metadata.get("subject") or "")
        return QuestionView(
            task_id=task_id,
            question_id=question_id,
            question_number=str(package.get("slot_id") or question_id),
            question_type=question_type,
            question_text=stem,
            options=options,
            # Assembly accepts a single label or the exact option text; the instructor
            # view stays out of this field because review never sees it anyway.
            answer_text=answer_text,
            points=float(score) if isinstance(score, (int, float)) else None,
            subject=SUBJECT_LABELS.get(subject, subject),
            paper_title=f"AI generation task {task_id}",
            section_titles=[str(metadata["topic"])] if metadata.get("topic") else [],
            numbering_path=[],
            numbering_description=f"Generated version {version}",
            # `reference` means a shared parent passage the exporter would have to
            # render; authoring evidence is provenance, not shared material, and a
            # non-empty value makes assembly reject the question outright.
            reference="",
        )
