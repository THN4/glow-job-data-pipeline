"""CV data contract (Pydantic). Single source of truth for the API and the model's output.

JSON is camelCase on the wire; Python fields are snake_case.

Two layers:
  * ``CvExtraction``: what the AI model returns (no ids / review flags).
  * ``CvProfile``:    what the API returns and the frontend edits
                      (AI fields + id, needsReview, source).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Confidence = Literal["high", "medium", "low"]
Source = Literal["cv", "user"]
SkillCategory = Literal["language", "framework", "database", "cloud", "devops", "data", "other"]
EmploymentType = Literal["full-time", "part-time", "internship", "freelance", "contract", "volunteer"]
CertificationKind = Literal["certification", "award", "competition", "workshop", "activity"]
DetectedLanguage = Literal["en", "th", "mixed"]
InputKind = Literal["text", "images"]
# Same scale as market.career_skill_stats.target_level / user_skills.proficiency_level in the database design.
Proficiency = Literal["unknown", "beginner", "intermediate", "advanced", "expert"]
# "explicit" = the CV states the level; "inferred" = estimated from how long the skill was used; "unknown" = no signal.
ProficiencyBasis = Literal["explicit", "inferred", "unknown"]
EducationLevel = Literal["high_school", "diploma", "associate", "bachelor", "master", "doctorate", "other"]
SuggestedStatus = Literal["student", "employed", "career_switcher"]

_CONF = Field(
    description='"high" = clearly printed; "medium" = structure was inferred; "low" = hard to read or ambiguous'
)
_DATE = Field(description='"YYYY" or "YYYY-MM"; null if not stated')


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AiModel(Camel):
    """Strict base for what the model returns: unknown keys are an error."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- AI-facing items
# Kept flat and small so local models follow them. Every field is required (nullable, not optional).


class LinkItem(AiModel):
    label: str
    url: str


class PersonalAi(AiModel):
    full_name: str | None
    headline: str | None = Field(description="Professional title or tagline, as written")
    email: str | None
    phone: str | None
    location: str | None
    links: list[LinkItem]
    confidence: Confidence = _CONF


class EducationAi(AiModel):
    degree: str | None = Field(description='e.g. "B.Sc.", "Master of Engineering"')
    field_of_study: str | None = Field(description='e.g. "Computer Science"')
    institution: str | None
    start_date: str | None = _DATE
    end_date: str | None = _DATE
    is_current: bool
    gpa: str | None
    description: str | None = Field(description="Honors, thesis topic or notable coursework, only if written in the CV")
    confidence: Confidence = _CONF


class TechnicalSkillAi(AiModel):
    name: str
    category: SkillCategory
    proficiency: Proficiency = Field(
        description='Only if the CV states the level next to this skill (e.g. "Python (advanced)", "basic SQL", '
        '"expert in Docker", "familiar with Git"); otherwise "unknown". Never estimate it.'
    )
    confidence: Confidence = _CONF


class NamedItemAi(AiModel):
    name: str
    confidence: Confidence = _CONF


class ExperienceAi(AiModel):
    title: str | None
    organization: str | None
    employment_type: EmploymentType | None
    location: str | None
    start_date: str | None = _DATE
    end_date: str | None = _DATE
    is_current: bool = Field(description='true if the role is ongoing ("Present")')
    description: str | None
    highlights: list[str]
    technologies: list[str]
    confidence: Confidence = _CONF


class ProjectAi(AiModel):
    name: str | None
    description: str | None
    role: str | None
    url: str | None
    start_date: str | None = _DATE
    end_date: str | None = _DATE
    technologies: list[str]
    confidence: Confidence = _CONF


class CertificationAi(AiModel):
    kind: CertificationKind
    name: str | None
    issuer: str | None
    date: str | None = _DATE
    detail: str | None = Field(description='e.g. "Finalist", "Top 10"')
    confidence: Confidence = _CONF


class LanguageAi(AiModel):
    name: str
    proficiency: str | None
    confidence: Confidence = _CONF


class CvExtraction(AiModel):
    is_document_a_cv: bool = Field(description="false if the document is not a CV/resume")
    detected_language: DetectedLanguage
    warnings: list[str] = Field(description="Problems that affect quality, e.g. blurry image")
    personal: PersonalAi
    summary: str | None
    education: list[EducationAi]
    technical_skills: list[TechnicalSkillAi]
    soft_skills: list[NamedItemAi]
    experience: list[ExperienceAi]
    projects: list[ProjectAi]
    certifications: list[CertificationAi]
    tools: list[NamedItemAi]
    languages: list[LanguageAi]


# --------------------------------------------------------------------------- profile (API + frontend)


class _Meta(BaseModel):
    """Fields the backend adds to each item."""

    id: str = Field(min_length=1, max_length=64)
    needs_review: bool
    source: Source


class Personal(PersonalAi):
    model_config = ConfigDict(extra="ignore")
    needs_review: bool
    source: Source


class Education(EducationAi, _Meta):
    model_config = ConfigDict(extra="ignore")


class SkillEvidence(Camel):
    """Where the CV shows the skill in use (-> app.user_skill_evidence)."""

    evidence_type: Literal["experience", "project", "resume_text"]
    item_id: str | None = None  # id of the experience / project, when the evidence is an item
    text: str | None = None  # short quote / description


class TechnicalSkill(TechnicalSkillAi, _Meta):
    model_config = ConfigDict(extra="ignore")
    # Added by the backend (optional, so older clients / saved profiles stay valid).
    proficiency_basis: ProficiencyBasis = "unknown"
    evidence: list[SkillEvidence] = Field(default_factory=list)


class NamedItem(NamedItemAi, _Meta):
    model_config = ConfigDict(extra="ignore")


class Experience(ExperienceAi, _Meta):
    model_config = ConfigDict(extra="ignore")


class Project(ProjectAi, _Meta):
    model_config = ConfigDict(extra="ignore")


class Certification(CertificationAi, _Meta):
    model_config = ConfigDict(extra="ignore")


class Language(LanguageAi, _Meta):
    model_config = ConfigDict(extra="ignore")


class Derived(Camel):
    """Profile-level facts computed from the confirmed data (-> app.user_profiles). Not asked from the model."""

    years_experience: float | None = None
    current_job_title: str | None = None
    education_level: EducationLevel | None = None
    field_of_study: str | None = None
    #: A suggestion only. The user chooses their status in onboarding step 4.
    suggested_status: SuggestedStatus | None = None


class CvProfile(Camel):
    schema_version: Literal[1] = 1
    personal: Personal
    summary: str | None
    education: list[Education]
    technical_skills: list[TechnicalSkill]
    soft_skills: list[NamedItem]
    experience: list[Experience]
    projects: list[Project]
    certifications: list[Certification]
    tools: list[NamedItem]
    languages: list[Language]
    derived: Derived | None = None


class CvExtractionMeta(Camel):
    extraction_id: str
    model: str
    duration_ms: int
    input_kind: InputKind
    cached: bool
    detected_language: DetectedLanguage
    page_count: int | None
    warnings: list[str]
    review_count: int


class CvExtractionResult(Camel):
    profile: CvProfile
    meta: CvExtractionMeta


def empty_profile() -> CvProfile:
    """Empty profile for "Continue without CV"."""
    return CvProfile(
        personal=Personal(
            full_name=None,
            headline=None,
            email=None,
            phone=None,
            location=None,
            links=[],
            confidence="high",
            needs_review=False,
            source="user",
        ),
        summary=None,
        education=[],
        technical_skills=[],
        soft_skills=[],
        experience=[],
        projects=[],
        certifications=[],
        tools=[],
        languages=[],
    )


# --------------------------------------------------------------------------- JSON schema for the model


def _inline_refs(node, defs: dict):
    """Resolve local $ref pointers so servers with partial $ref support (llama.cpp grammars) accept the schema.

    Also drops Pydantic's auto-generated "title" annotations, but NOT a field that is itself named "title".
    """
    if isinstance(node, dict):
        if "$ref" in node:
            target = _inline_refs(dict(defs[node["$ref"].rsplit("/", 1)[-1]]), defs)
            extras = {k: _inline_refs(v, defs) for k, v in node.items() if k != "$ref"}
            return {**target, **extras}
        out = {}
        for k, v in node.items():
            if k == "title" and isinstance(v, str):
                continue  # annotation keyword (a schema keyword's value is a string)
            if k == "properties" and isinstance(v, dict):
                out[k] = {name: _inline_refs(sub, defs) for name, sub in v.items()}  # keep field names as-is
            else:
                out[k] = _inline_refs(v, defs)
        return out
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def cv_extraction_json_schema() -> dict:
    schema = CvExtraction.model_json_schema(by_alias=True)
    defs = schema.pop("$defs", {})
    return _inline_refs(schema, defs)
