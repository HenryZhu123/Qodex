from __future__ import annotations

import asyncio

from ..domain.models import QuestionView, StoredQuestionVersion
from .persistence import QuestionVersionNotFoundError


class InMemoryQuestionVersionRepository:
    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], list[StoredQuestionVersion]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self, questions: list[QuestionView]) -> None:
        async with self._lock:
            for question in questions:
                key = (question.task_id, question.question_id)
                if key in self._versions:
                    continue
                self._versions[key] = [
                    StoredQuestionVersion(
                        task_id=question.task_id,
                        question_id=question.question_id,
                        version=1,
                        revision_source="PARSED",
                        question=question,
                    )
                ]

    async def get_latest(
        self, task_id: str, question_id: str
    ) -> StoredQuestionVersion:
        versions = self._versions.get((task_id, question_id))
        if not versions:
            raise QuestionVersionNotFoundError((task_id, question_id))
        return versions[-1]

    async def get(
        self, task_id: str, question_id: str, version: int
    ) -> StoredQuestionVersion:
        versions = self._versions.get((task_id, question_id), [])
        for snapshot in versions:
            if snapshot.version == version:
                return snapshot
        raise QuestionVersionNotFoundError((task_id, question_id, version))

    async def import_generated(
        self, *, task_id: str, question_id: str, version: int, question: QuestionView
    ) -> StoredQuestionVersion:
        async with self._lock:
            key = (task_id, question_id)
            versions = self._versions.setdefault(key, [])
            for snapshot in versions:
                if snapshot.version == version:
                    if snapshot.question != question:
                        raise ValueError(
                            "Generated version content conflicts with the imported snapshot"
                        )
                    return snapshot
            snapshot = StoredQuestionVersion(
                task_id=task_id,
                question_id=question_id,
                version=version,
                revision_source="GENERATED",
                question=question,
            )
            versions.append(snapshot)
            versions.sort(key=lambda item: item.version)
            return snapshot
