"""Bounded document retrieval and cited learning-context preview contracts."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, model_validator

from src.documents.schemas.skill_dependency import StrictRecord

Intent = Literal["fundamentals", "level_improvement", "practice"]
Level = Literal["beginner", "intermediate", "advanced", "expert", "unknown"]


class RetrievalPolicy(StrictRecord):
    version: Literal["document-context-preview-1"] = "document-context-preview-1"
    candidate_limit: int = Field(default=12, ge=1, le=20)
    selected_limit: int = Field(default=5, ge=1, le=5)
    per_skill_chars: int = Field(default=16000, ge=1000, le=40000)
    total_chars: int = Field(default=48000, ge=1000, le=120000)
    min_similarity: float | None = Field(default=None, ge=-1, le=1)


class ContextRequest(StrictRecord):
    skill_ids: list[int] = Field(min_length=1, max_length=8)
    intent: Intent = "fundamentals"
    current_level: Level = "unknown"
    target_level: Level = "unknown"
    policy: RetrievalPolicy = Field(default_factory=RetrievalPolicy)

    @model_validator(mode="after")
    def canonical_ids(self):
        if any(skill_id < 1 for skill_id in self.skill_ids) or len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("Selected skill IDs must be unique positive canonical IDs")
        return self


class RetrievedChunk(StrictRecord):
    chunk_id: int = Field(gt=0)
    source_id: int = Field(gt=0)
    title: str
    source_url: str | None
    heading_path: list[str] = Field(default_factory=list)
    content: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_score: float = Field(ge=-1.000001, le=1.000001)


class Citation(StrictRecord):
    chunk_id: int = Field(gt=0)
    quote: str = Field(min_length=20, max_length=1800)


class LearningClaim(StrictRecord):
    text: str = Field(min_length=5, max_length=1200)
    support_kind: Literal["instructional", "topic_outline"]
    citations: list[Citation] = Field(min_length=1, max_length=3)


class TextReview(StrictRecord):
    status: Literal["supported", "partial", "insufficient_evidence"]
    selected_chunk_ids: list[int] = Field(max_length=5)
    claims: list[LearningClaim] = Field(max_length=8)
    warnings: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def usable_support(self):
        if len(self.selected_chunk_ids) != len(set(self.selected_chunk_ids)):
            raise ValueError("Repeated selected chunk IDs")
        cited = {citation.chunk_id for claim in self.claims for citation in claim.citations}
        if cited != set(self.selected_chunk_ids):
            raise ValueError("Selected chunks must be exactly the chunks supporting the claims")
        if self.status == "insufficient_evidence" and (self.claims or self.selected_chunk_ids):
            raise ValueError("Insufficient evidence must not generate learning claims")
        if self.status != "insufficient_evidence" and not self.claims:
            raise ValueError("Supported/partial context requires cited claims")
        if self.status == "supported" and any(claim.support_kind == "topic_outline" for claim in self.claims):
            raise ValueError("Topic outlines support only partial context, not ready teaching content")
        return self


class SkillDocumentContext(StrictRecord):
    skill_id: int = Field(gt=0)
    skill_name: str
    selection_role: Literal["main"] = "main"
    query: str
    current_level: Level
    target_level: Level
    status: Literal["supported", "partial", "insufficient_evidence", "not_reviewed", "error"]
    coverage_reason: str | None = None
    mapped_chunks: int = Field(ge=0)
    embedded_chunks: int = Field(ge=0)
    retrieved_candidates: int = Field(default=0, ge=0)
    chunks_sent_for_review: int = Field(default=0, ge=0)
    review_content_chars: int = Field(default=0, ge=0)
    teaching_content_status: Literal["available", "outline_only", "unavailable", "not_reviewed"] = "unavailable"
    skipped_for_budget: int = Field(default=0, ge=0)
    retrieved_context: list[RetrievedChunk] = Field(default_factory=list)
    claims: list[LearningClaim] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)
    dependency_coverage: Literal["unknown"] = "unknown"
    warnings: list[str] = Field(default_factory=list)


class KnowledgeContextPreview(StrictRecord):
    schema_version: Literal["knowledge-context-preview-1"] = "knowledge-context-preview-1"
    status: Literal["knowledge_preview"] = "knowledge_preview"
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    embedding_model: str
    embedding_dimensions: int
    text_model: str | None
    policy: RetrievalPolicy
    content_chars_sent_for_review: int = Field(ge=0)
    selected_content_chars: int = Field(ge=0)
    skills: list[SkillDocumentContext]
    warnings: list[str]
