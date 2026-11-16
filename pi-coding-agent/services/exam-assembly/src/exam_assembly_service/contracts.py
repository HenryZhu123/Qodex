"""Versioned public request; legacy core fields stay private to the selection engine."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class PaperSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    subject: str = Field(min_length=1)
    question_type: Literal["single_choice", "comprehensive"]
    score: int = Field(ge=1, le=150)
    knowledge_point: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    part_scores: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_parts(self):
        if not self.subject.strip() or self.knowledge_point is not None and not self.knowledge_point.strip():
            raise ValueError("学科和指定知识点不能为空白")
        if self.part_scores and (self.question_type != "comprehensive" or sum(self.part_scores) != self.score):
            raise ValueError("小问分值之和必须等于综合题总分，单选不能指定小问")
        return self


class PaperRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["2.0"]
    request_id: str = Field(min_length=1, max_length=200)
    subject: str = Field(default="408计算机学科专业基础", min_length=1)
    question_count: int = Field(ge=1, le=100)
    total_score: int = Field(ge=1)
    slots: list[PaperSlot] = Field(min_length=1, max_length=100)
    export_pdf: Literal[False] = False
    semantic_review: bool = False
    semantic_max_calls: int = Field(default=8, ge=0, le=100)
    similarity_search_limit: int = Field(default=32, ge=1, le=128)
    similarity_decisions: list[SimilarityDecision] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def validate_plan(self):
        if not self.request_id.strip() or len(self.slots) != self.question_count:
            raise ValueError("请求标识不能为空白，slots 数量须等于 question_count")
        if sum(slot.score for slot in self.slots) != self.total_score:
            raise ValueError("slots 分值之和须等于 total_score")
        return self
