import json
from pathlib import Path

import pytest
import yaml

from src.skills.candidate_suggester import suggest_skill_candidates
from src.skills.normalizer import build_skill_catalog


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


def test_suggester_accepts_every_canonical_skill_in_project_config():
    config = yaml.safe_load(Path("config/skills.yaml").read_text(encoding="utf-8"))
    configured_skills = config["skills"]
    skills = [
        (index, value["skill_name"], value["skill_category"])
        for index, value in enumerate(configured_skills.values(), start=1)
    ]
    aliases = [
        (index, alias)
        for index, value in enumerate(configured_skills.values(), start=1)
        for alias in value["aliases"]
    ]
    catalog = build_skill_catalog(skills, aliases)
    rows = [
        {
            "candidate_name": f"{skill_name} platform",
            "observed_names": [f"{skill_name} platform"],
            "occurrence_count": 1,
            "example_job_titles": ["Engineer"],
            "example_evidence": [f"Experience with {skill_name} platform."],
        }
        for _, skill_name, _ in skills
    ]
    response = {
        "suggestions": [
            {
                "candidate_id": index,
                "decision": "existing_skill",
                "canonical_skill_name": skill_name,
                "skill_category": None,
                "confidence": "high",
                "reason": "The evidence identifies this configured skill.",
            }
            for index, (_, skill_name, _) in enumerate(skills)
        ]
    }

    suggestions = suggest_skill_candidates(
        rows,
        catalog,
        generate=lambda _: json.dumps(response),
    )

    assert len(suggestions) == len(configured_skills)
    assert [item["suggested_skill_name"] for item in suggestions] == [
        value["skill_name"] for value in configured_skills.values()
    ]
