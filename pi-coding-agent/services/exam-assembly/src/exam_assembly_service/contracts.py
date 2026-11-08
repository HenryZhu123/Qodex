"""Versioned public request; legacy core fields stay private to the selection engine."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SimilarityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pair_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    question_ids: list[str] = Field(min_length=2, max_length=2)
    content_hashes: list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]] = Field(min_length=2, max_length=2)
    source: Literal["human"]
    reviewer: str = Field(min_length=1)
    verdict: Literal["DISTINCT", "DUPLICATE", "UNRESOLVED"]
    reason: str = Field(min_length=1)


class AssemblyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1)
    question_count: int = Field(ge=1, le=100)
    total_score: int = Field(ge=1)
    question_type_counts: dict[str, int]
    question_type_scores: dict[str, int]
    knowledge_point_counts: dict[str, int]
    difficulty_counts: dict[str, int]
    max_repair_rounds: int = Field(default=3, ge=0, le=10)
    export_pdf: bool = False
    similarity_decisions: list[SimilarityDecision] = Field(default_factory=list, max_length=5000)

    def selection_request(self):
        """Return explicit business errors before accessing the bank; never rebalance quotas."""
        errors = []
        if not self.request_id.strip() or not self.subject.strip():
            errors.append("request_id 和 subject 不能为空白")
        for field in ("question_type_counts", "knowledge_point_counts", "difficulty_counts"):
            counts = getattr(self, field)
            if not counts or any(not key.strip() or value < 0 for key, value in counts.items()):
                errors.append(f"{field} 名称必须非空，数量必须非负")
            elif sum(counts.values()) != self.question_count:
                errors.append(f"{field} 之和必须等于 question_count")
        if set(self.difficulty_counts) != {"easy", "medium", "hard"}:
            errors.append("difficulty_counts 必须包含 easy、medium、hard 三个键，不需要的难度填 0")
        if (set(self.question_type_scores) != set(self.question_type_counts)
                or any(value <= 0 for value in self.question_type_scores.values())):
            errors.append("question_type_scores 必须为每个题型提供正整数单题分值，键与 question_type_counts 一致")
        elif sum(count * self.question_type_scores[key] for key, count in self.question_type_counts.items()) != self.total_score:
            errors.append("题型题数乘以对应单题分值之和必须等于 total_score")
        active = [key for key, count in self.question_type_counts.items() if count > 0]
        if active != ["single_choice"]:
            errors.append("目前仅支持 single_choice；混合题型和 calculation 尚未实现")
        if errors:
            return None, errors
        return dict(request_id=self.request_id, subject=self.subject, question_type="single_choice",
                    question_count=self.question_count, total_score=self.total_score,
                    score_per_question=self.question_type_scores["single_choice"],
                    topic_counts=self.knowledge_point_counts.copy(), difficulty_counts=self.difficulty_counts.copy(),
                    max_repair_rounds=self.max_repair_rounds), []
