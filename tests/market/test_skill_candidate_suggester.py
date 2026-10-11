import json

import pytest

from src.market.skill_extraction.candidate_suggester import suggest_skill_candidates
from src.shared.skill_normalization.normalizer import build_skill_catalog


def _catalog():
    return build_skill_catalog(
        [
            (1, "Python", "programming_language"),
            (2, "PostgreSQL", "database"),
            (3, "Apache Airflow", "orchestration_tool"),
        ],
        [(2, "Postgres"), (3, "Airflow")],
    )


def _rows():
    return [
        {
            "candidate_name": "Postgres DB",
            "observed_names": ["Postgres DB"],
            "occurrence_count": 4,
            "example_job_titles": ["Data Engineer"],
            "example_evidence": ["Postgres DB is used in production."],
        },
        {
            "candidate_name": "Tableau",
            "observed_names": ["Tableau"],
            "occurrence_count": 3,
            "example_job_titles": ["Data Analyst"],
            "example_evidence": ["Experience with Tableau is required."],
        },
        {
            "candidate_name": "modern data stack",
            "observed_names": ["modern data stack"],
            "occurrence_count": 1,
            "example_job_titles": ["Data Engineer"],
            "example_evidence": ["Work across the modern data stack."],
        },
    ]


def test_suggester_returns_catalog_match_new_skill_and_non_skill_decisions():
    rows = _rows()
    response = {
        "suggestions": [
            {
                "candidate_id": 0,
                "decision": "existing_skill",
                "canonical_skill_name": "PostgreSQL",
                "skill_category": None,
                "confidence": "high",
                "reason": "The evidence names the PostgreSQL database.",
            },
            {
                "candidate_id": 1,
                "decision": "new_skill",
                "canonical_skill_name": "Tableau",
                "skill_category": "other",
                "confidence": "high",
                "reason": "Tableau is a distinct analytics product absent from the catalog.",
            },
            {
                "candidate_id": 2,
                "decision": "not_skill",
                "canonical_skill_name": None,
                "skill_category": None,
                "confidence": "medium",
                "reason": "This is a broad industry phrase, not one concrete skill.",
            },
        ]
    }
    captured_prompt = []

    results = suggest_skill_candidates(
        rows,
        _catalog(),
        generate=lambda prompt: captured_prompt.append(prompt) or json.dumps(response),
    )

    assert results == [
        {
            "suggestion_decision": "existing_skill",
            "suggested_skill_name": "PostgreSQL",
            "suggested_skill_category": "",
            "confidence_level": "high",
            "suggestion_reason": "The evidence names the PostgreSQL database.",
        },
        {
            "suggestion_decision": "new_skill",
            "suggested_skill_name": "Tableau",
            "suggested_skill_category": "other",
            "confidence_level": "high",
            "suggestion_reason": "Tableau is a distinct analytics product absent from the catalog.",
        },
        {
            "suggestion_decision": "not_skill",
            "suggested_skill_name": "",
            "suggested_skill_category": "",
            "confidence_level": "medium",
            "suggestion_reason": "This is a broad industry phrase, not one concrete skill.",
        },
    ]
    assert len(captured_prompt) == 1
    assert "PostgreSQL" in captured_prompt[0]
    assert "Do not map a broader category" in captured_prompt[0]


@pytest.mark.parametrize(
    "suggestion",
    [
        {
            "candidate_id": 0,
            "decision": "new_skill",
            "canonical_skill_name": "Python",
            "skill_category": None,
            "confidence": "high",
            "reason": "Contradictory output.",
        },
        {
            "candidate_id": 0,
            "decision": "uncertain",
            "canonical_skill_name": None,
            "skill_category": None,
            "confidence": "low",
            "reason": "",
        },
    ],
)
def test_suggester_rejects_unverified_or_incomplete_output(suggestion):
    with pytest.raises(ValueError):
        suggest_skill_candidates(
            _rows()[:1],
            _catalog(),
            generate=lambda _: json.dumps({"suggestions": [suggestion]}),
        )


def test_suggester_routes_unverified_existing_name_to_manual_review():
    suggestion = {
        "candidate_id": 0,
        "decision": "existing_skill",
        "canonical_skill_name": "Postgres",
        "skill_category": None,
        "confidence": "high",
        "reason": "Alias rather than canonical name.",
    }

    [result] = suggest_skill_candidates(
        _rows()[:1],
        _catalog(),
        generate=lambda _: json.dumps({"suggestions": [suggestion]}),
    )

    assert result["suggestion_decision"] == "uncertain"
    assert result["suggested_skill_name"] == ""
    assert "exact catalog name" in result["suggestion_reason"]


def test_suggester_requires_exactly_one_result_per_candidate():
    with pytest.raises(ValueError, match="exactly one"):
        suggest_skill_candidates(
            _rows()[:2],
            _catalog(),
            generate=lambda _: json.dumps(
                {
                    "suggestions": [
                        {
                            "candidate_id": 0,
                            "decision": "uncertain",
                            "canonical_skill_name": None,
                            "skill_category": None,
                            "confidence": "low",
                            "reason": "Not enough context.",
                        }
                    ]
                }
            ),
        )


def test_suggester_does_not_call_model_when_no_rows():
    def unexpected_call(_):
        raise AssertionError("no model request should be made")

    assert suggest_skill_candidates([], _catalog(), generate=unexpected_call) == []


def test_clean_catalog_prompt_uses_categories_without_old_catalog():
    rows = _rows()[:1]
    response = {
        "suggestions": [
            {
                "candidate_id": 0,
                "decision": "new_skill",
                "canonical_skill_name": "Postgres DB",
                "skill_category": "database",
                "confidence": "high",
                "reason": "The evidence names a database technology.",
            }
        ]
    }
    captured_prompt = []

    suggestions = suggest_skill_candidates(
        rows,
        {},
        generate=lambda prompt: captured_prompt.append(prompt) or json.dumps(response),
    )

    assert suggestions[0]["suggested_skill_category"] == "database"
    assert "prior database is intentionally excluded" in captured_prompt[0]
    assert '"database"' in captured_prompt[0]
