from decimal import Decimal

from src.skills.confidence import score_job_skill


def _skill(name, evidence, requirement, level, method="exact_canonical"):
    return {
        "raw_skill_name": name,
        "evidence_text": evidence,
        "requirement_type": requirement,
        "proficiency_level": level,
        "match_method": method,
    }


def test_explicit_cues_produce_reproducible_overall_confidence():
    evidence = "Experience using Postgres in production is required."
    scores = score_job_skill(
        _skill("Postgres", evidence, "required", "unknown", "exact_alias"),
        evidence,
    )

    assert scores == {
        "skill_confidence": Decimal("0.95"),
        "requirement_confidence": Decimal("1.00"),
        "proficiency_confidence": Decimal("0.95"),
        "overall_confidence": Decimal("0.968"),
    }


def test_strong_and_basic_keep_importance_separate_from_confidence():
    python = "Strong Python skills are required."
    sql = "Basic SQL knowledge is preferred."

    assert score_job_skill(
        _skill("Python", python, "required", "advanced"), python
    )["overall_confidence"] == Decimal("0.950")
    assert score_job_skill(
        _skill("SQL", sql, "preferred", "beginner"), sql
    )["overall_confidence"] == Decimal("0.975")


def test_conflicting_or_negated_cue_is_not_given_a_high_confidence():
    negated = "Kafka is not required."
    conflicting = "Kafka is required but preferred for some teams."

    assert score_job_skill(
        _skill("Kafka", negated, "required", "unknown"), negated
    )["requirement_confidence"] is None
    assert score_job_skill(
        _skill("Kafka", conflicting, "required", "unknown"), conflicting
    )["overall_confidence"] is None


def test_indirect_inference_does_not_gain_confidence_from_catalog_match():
    evidence = "Experience with relational database systems is required."

    assert score_job_skill(
        _skill("SQL", evidence, "required", "unknown"), evidence
    )["skill_confidence"] is None


def test_requirement_header_can_support_a_bullet_without_sentence_cue():
    evidence = "Strong Python skills."
    description = "Required Qualifications:\n\n• " + evidence

    scores = score_job_skill(
        _skill("Python", evidence, "required", "advanced"), description
    )

    assert scores["requirement_confidence"] == Decimal("0.90")
    assert scores["proficiency_confidence"] == Decimal("0.80")
    assert scores["overall_confidence"] == Decimal("0.915")


def test_repeated_skill_mentions_need_context_review():
    evidence = "Python is required."
    description = evidence + "\nPython is optional for another team."

    scores = score_job_skill(
        _skill("Python", evidence, "required", "unknown"), description
    )

    assert scores["skill_confidence"] == Decimal("1.00")
    assert scores["requirement_confidence"] is None
    assert scores["proficiency_confidence"] is None
    assert scores["overall_confidence"] is None
