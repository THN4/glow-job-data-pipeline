"""Conservative, repeatable confidence scores for extracted job skills."""

import re
from decimal import Decimal, ROUND_HALF_UP


_REQUIREMENT_CUES = (
    ("minimum requirement", "required", "1.00"),
    ("required", "required", "1.00"),
    ("must have", "required", "1.00"),
    ("mandatory", "required", "1.00"),
    ("need to have", "required", "0.95"),
    ("essential", "required", "0.95"),
    ("preferred qualification", "preferred", "1.00"),
    ("preferred", "preferred", "1.00"),
    ("desirable", "preferred", "0.95"),
    ("advantageous", "preferred", "0.90"),
    ("nice to have", "preferred", "0.90"),
    ("a plus", "preferred", "0.90"),
    ("plus", "preferred", "0.90"),
    ("bonus", "preferred", "0.90"),
    ("would be beneficial", "preferred", "0.85"),
    ("good to have", "preferred", "0.85"),
    ("optional", "optional", "1.00"),
)
_PROFICIENCY_CUES = (
    ("beginner", "beginner", "0.95"),
    ("basic", "beginner", "0.90"),
    ("fundamental", "beginner", "0.90"),
    ("intermediate", "intermediate", "0.95"),
    ("working knowledge", "intermediate", "0.85"),
    ("practical experience", "intermediate", "0.85"),
    ("advanced", "advanced", "0.95"),
    ("strong", "advanced", "0.80"),
    ("solid", "advanced", "0.80"),
    ("expert", "expert", "0.98"),
    ("deep expertise", "expert", "0.90"),
    ("specialist", "expert", "0.90"),
)
_SECTION_CUES = {
    "required skills": ("required", Decimal("0.90")),
    "required qualifications": ("required", Decimal("0.90")),
    "minimum qualifications": ("required", Decimal("0.90")),
    "preferred skills": ("preferred", Decimal("0.90")),
    "preferred qualifications": ("preferred", Decimal("0.90")),
}
_NEGATION = re.compile(
    r"\bnot\s+(?:required|preferred|mandatory)\b|"
    r"\bno\s+prior\b.{0,60}\brequired\b|"
    r"\bdo\s+not\s+use\b|\bnot\s+necessary\b",
    re.IGNORECASE,
)
_PROFICIENCY_NEGATION = re.compile(
    r"\bnot\s+(?:basic|beginner|intermediate|advanced|expert|strong)\b",
    re.IGNORECASE,
)


def _phrase_pattern(phrase: str) -> str:
    return (
        r"(?<!\w)"
        + r"[\s\-\u2010-\u2015]+".join(map(re.escape, phrase.split()))
        + r"(?!\w)"
    )


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(_phrase_pattern(phrase), text, re.IGNORECASE) is not None


def _cue_scores(
    evidence: str, cues: tuple[tuple[str, str, str], ...]
) -> list[tuple[str, Decimal]]:
    return [
        (classification, Decimal(score))
        for phrase, classification, score in cues
        if _has_phrase(evidence, phrase)
    ]


def _section_requirement(job_description: str, evidence: str) -> tuple[str, Decimal] | None:
    """Use only a recognizable preceding header with no intervening header."""
    position = job_description.find(evidence)
    if position < 0:
        return None
    lines = job_description[:position].splitlines()
    for line in reversed(lines[-30:]):
        heading = line.strip().strip("# ").rstrip(":").casefold()
        if heading in _SECTION_CUES:
            return _SECTION_CUES[heading]
        if line.strip().endswith(":") and len(line.strip()) < 90:
            return None
    return None


def score_job_skill(
    skill: dict[str, object], job_description: str
) -> dict[str, Decimal | None]:
    """Score clear evidence; return NULL-equivalent values when context is unclear."""
    evidence = skill["evidence_text"]
    raw_name = skill["raw_skill_name"]
    if not isinstance(evidence, str) or not isinstance(raw_name, str):
        raise ValueError("Skill evidence and raw name must be strings")
    if evidence not in job_description or not _has_phrase(evidence, raw_name):
        return {
            "skill_confidence": None,
            "requirement_confidence": None,
            "proficiency_confidence": None,
            "overall_confidence": None,
        }

    match_method = skill["match_method"]
    skill_confidence = {
        "exact_canonical": Decimal("1.00"),
        "exact_alias": Decimal("0.95"),
    }[match_method]
    repeated_name = len(re.findall(_phrase_pattern(raw_name), job_description, re.IGNORECASE)) > 1

    requirement_type = skill["requirement_type"]
    requirement_cues = _cue_scores(evidence, _REQUIREMENT_CUES)
    if repeated_name or _NEGATION.search(evidence) or "required for" in evidence.casefold():
        requirement_confidence = None
    elif requirement_cues:
        types = {kind for kind, _ in requirement_cues}
        requirement_confidence = (
            max(score for _, score in requirement_cues)
            if types == {requirement_type}
            else None
        )
    else:
        section = _section_requirement(job_description, evidence)
        if section is not None:
            requirement_confidence = section[1] if section[0] == requirement_type else None
        else:
            requirement_confidence = (
                Decimal("0.95") if requirement_type == "unknown" else None
            )

    proficiency_level = skill["proficiency_level"]
    proficiency_cues = _cue_scores(evidence, _PROFICIENCY_CUES)
    if repeated_name or _PROFICIENCY_NEGATION.search(evidence):
        proficiency_confidence = None
    elif proficiency_cues:
        levels = {level for level, _ in proficiency_cues}
        proficiency_confidence = (
            max(score for _, score in proficiency_cues)
            if levels == {proficiency_level}
            else None
        )
    else:
        proficiency_confidence = (
            Decimal("0.95") if proficiency_level == "unknown" else None
        )

    overall_confidence = None
    if requirement_confidence is not None and proficiency_confidence is not None:
        overall_confidence = (
            Decimal("0.40") * skill_confidence
            + Decimal("0.35") * requirement_confidence
            + Decimal("0.25") * proficiency_confidence
        ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return {
        "skill_confidence": skill_confidence,
        "requirement_confidence": requirement_confidence,
        "proficiency_confidence": proficiency_confidence,
        "overall_confidence": overall_confidence,
    }
