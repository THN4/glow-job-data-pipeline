"""Reviewable dependency proposals; model output never grants verification."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Relationship = Literal["prerequisite", "recommended_before", "related"]
Strength = Literal["required", "strong", "recommended", "weak"]
# "uncertain" remains readable for old checkpoints, and maps to DB "unknown".
Scope = Literal["general", "document_specific", "conditional", "unknown", "uncertain"]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Proposal(StrictRecord):
    prerequisite_skill_id: int = Field(gt=0)
    target_skill_id: int = Field(gt=0)
    dependency_type: Relationship
    strength: Strength
    confidence: float = Field(ge=0, le=1)
    source_id: int = Field(gt=0)
    chunk_id: int = Field(gt=0)
    evidence_text: str = Field(min_length=20, max_length=1800)
    reason: str = Field(min_length=5, max_length=1600)
    scope: Scope
    scope_note: str | None = Field(default=None, min_length=3, max_length=500)
    basis: Literal["explicit", "inferred"] | None = None

    @model_validator(mode="after")
    def no_self_link(self):
        if self.prerequisite_skill_id == self.target_skill_id:
            raise ValueError("A skill cannot depend on itself")
        return self

    def fingerprint(self) -> str:
        data = self.model_dump()
        # Adding optional metadata must not invalidate earlier reviewed files.
        if self.scope_note is None:
            data.pop("scope_note")
        if self.basis is None:
            data.pop("basis")
        return hashlib.sha256(json.dumps(
            data, sort_keys=True, ensure_ascii=False,
        ).encode("utf-8")).hexdigest()


class Review(StrictRecord):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=3, max_length=1600)
    reviewed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    proposal_fingerprint: str
    dependency_type: Relationship
    strength: Strength
    scope: Scope
    scope_note: str | None = Field(default=None, min_length=3, max_length=500)

    @model_validator(mode="after")
    def valid_timestamp(self):
        stamp = datetime.fromisoformat(self.reviewed_at)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Review timestamp requires an explicit timezone")
        return self


class ReviewItem(StrictRecord):
    proposal: Proposal
    proposal_fingerprint: str
    prerequisite_name: str
    target_name: str
    source_title: str
    source_url: str | None
    chunk_content_hash: str
    scope_flags: list[str] = Field(default_factory=list)
    review: Review | None = None

    @model_validator(mode="after")
    def review_matches_proposal(self):
        if self.proposal.fingerprint() != self.proposal_fingerprint:
            raise ValueError("Proposal changed; create a new review item instead of reusing a decision")
        if self.review and self.review.proposal_fingerprint != self.proposal_fingerprint:
            raise ValueError("Review belongs to another proposal")
        if self.review and self.review.decision == "approve":
            if self.review.scope in {"unknown", "uncertain"}:
                raise ValueError("Resolve scope before approval")
            if self.review.scope != "general" and not self.review.scope_note:
                raise ValueError("A scoped approval requires its document/learner condition")
            if self.review.scope == "general" and self.scope_flags:
                raise ValueError("Ordering evidence has scope flags and cannot be approved as a general rule")
        return self


class TargetEvidence(StrictRecord):
    skill_id: int = Field(gt=0)
    skill_name: str
    mapped_chunks: int = Field(ge=0)
    inspected_chunks: int = Field(ge=0)
    inspected_sources: int = Field(ge=0)

    @model_validator(mode="after")
    def bounded_counts(self):
        if self.inspected_sources > self.inspected_chunks or self.inspected_chunks > self.mapped_chunks:
            raise ValueError("Evidence counts exceed the available target chunks")
        return self


class ReviewManifest(StrictRecord):
    schema_version: Literal["1"] = "1"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model: str
    target_skills: list[dict]
    inspected_chunk_count: int = Field(ge=0)
    omitted_chunk_count: int = Field(ge=0)
    duplicate_proposals: int = Field(default=0, ge=0)
    target_evidence: list[TargetEvidence] = Field(default_factory=list)
    origin: Literal["document_evidence"] = "document_evidence"
    corpus_chunk_count: int | None = Field(default=None, ge=0)
    processed_chunk_ids: list[int] = Field(default_factory=list)
    source_count: int | None = Field(default=None, ge=0)
    invalid_proposals: int = Field(default=0, ge=0)
    items: list[ReviewItem]

    @model_validator(mode="after")
    def unique_items(self):
        keys = [item.proposal_fingerprint for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate review item")
        return self
