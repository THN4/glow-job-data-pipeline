import pytest

from src.shared.skill_normalization.normalizer import build_skill_catalog, normalize_skills_for_jobs


def _skill(name, requirement="required", level="unknown"):
    return {
        "raw_skill_name": name,
        "requirement_type": requirement,
        "proficiency_level": level,
        "evidence_text": f"Evidence for {name}",
    }


def test_matches_canonical_and_alias_and_keeps_unmatched_for_review():
    catalog = build_skill_catalog(
        [(12, "PostgreSQL", "database"), (13, "Apache Airflow", "orchestration_tool")],
        [(12, "Postgres"), (13, "Airflow")],
    )
    entry = {
        "job": {"job_id": "job-1"},
        "metadata": {"run_id": "run-1"},
        "extraction_status": "completed",
        "skills": [_skill("  POSTGRES  "), _skill("Apache Airflow"), _skill("ETL Pipeline")],
    }

    [result] = normalize_skills_for_jobs([entry], catalog)

    assert [skill["skill_id"] for skill in result["normalized_skills"]] == [12, 13]
    assert [skill["skill_category"] for skill in result["normalized_skills"]] == [
        "database", "orchestration_tool"
    ]
    assert [skill["match_method"] for skill in result["normalized_skills"]] == [
        "exact_alias", "exact_canonical"
    ]
    assert result["unmatched_skills"] == [_skill("ETL Pipeline")]
    assert result["skills"] == entry["skills"]
    assert result["metadata"] == entry["metadata"]
    assert "normalized_skills" not in entry


def test_splits_evidenced_comma_list_into_individual_catalog_skills():
    catalog = build_skill_catalog(
        [(1, "Python", "programming_language"), (2, "SQL", "query_language")],
        [(1, "Python, SQL")],
    )
    entry = {
        "extraction_status": "completed",
        "skills": [
            {
                **_skill("Python, SQL"),
                "evidence_text": "Experience with Python, SQL, and data analysis.",
            }
        ],
    }

    [result] = normalize_skills_for_jobs([entry], catalog)

    assert [(skill["skill_id"], skill["raw_skill_name"]) for skill in result["normalized_skills"]] == [
        (1, "Python"),
        (2, "SQL"),
    ]
    assert all(
        skill["source_raw_skill_name"] == "Python, SQL"
        for skill in result["normalized_skills"]
    )
    assert result["unmatched_skills"] == []


def test_does_not_split_composite_without_evidence_for_each_component():
    catalog = build_skill_catalog(
        [(1, "Python", "programming_language"), (2, "SQL", "query_language")],
        [(1, "Python, SQL")],
    )
    raw = {
        **_skill("Python, SQL"),
        "evidence_text": "Experience with Python and data analysis.",
    }

    [result] = normalize_skills_for_jobs(
        [{"extraction_status": "completed", "skills": [raw]}], catalog
    )

    assert result["normalized_skills"] == []
    assert result["unmatched_skills"] == [raw]


def test_verified_parenthetical_acronym_maps_to_base_canonical():
    catalog = build_skill_catalog(
        [(1, "Machine Learning", "machine_learning")], []
    )
    raw = {
        **_skill("Machine Learning (ML)"),
        "evidence_text": "Experience with Machine Learning (ML).",
    }

    [result] = normalize_skills_for_jobs(
        [{"extraction_status": "completed", "skills": [raw]}], catalog
    )

    [skill] = result["normalized_skills"]
    assert skill["skill_id"] == 1
    assert skill["skill_name"] == "Machine Learning"
    assert skill["match_method"] == "exact_alias"


def test_unverified_parenthetical_text_is_not_treated_as_acronym():
    catalog = build_skill_catalog(
        [(1, "Machine Learning", "machine_learning")], []
    )
    raw = {
        **_skill("Machine Learning (MLOps)"),
        "evidence_text": "Experience with Machine Learning (MLOps).",
    }

    [result] = normalize_skills_for_jobs(
        [{"extraction_status": "completed", "skills": [raw]}], catalog
    )

    assert result["normalized_skills"] == []
    assert result["unmatched_skills"] == [raw]


def test_merges_duplicate_aliases_with_strongest_requirement_and_flags_level_conflict():
    catalog = build_skill_catalog([(12, "PostgreSQL", "database")], [(12, "Postgres")])
    entry = {
        "extraction_status": "completed",
        "skills": [
            _skill("Postgres", "preferred", "beginner"),
            _skill("PostgreSQL", "required", "advanced"),
        ],
    }

    [result] = normalize_skills_for_jobs([entry], catalog)

    assert len(result["normalized_skills"]) == 1
    skill = result["normalized_skills"][0]
    assert skill["skill_id"] == 12
    assert skill["raw_skill_name"] == "PostgreSQL"
    assert skill["requirement_type"] == "required"
    assert skill["evidence_text"] == "Evidence for PostgreSQL"
    assert skill["proficiency_level"] == "unknown"
    assert len(entry["skills"]) == 2


def test_failed_extraction_is_not_treated_as_an_empty_success():
    [result] = normalize_skills_for_jobs(
        [{"extraction_status": "failed", "skills": [], "extraction_error": "429"}],
        {},
    )

    assert result["extraction_status"] == "failed"
    assert result["extraction_error"] == "429"
    assert result["normalized_skills"] == []
    assert result["unmatched_skills"] == []


def test_catalog_rejects_ambiguous_alias():
    with pytest.raises(ValueError, match="conflicting skill alias"):
        build_skill_catalog(
            [(1, "SQL", "query_language"), (2, "PostgreSQL", "database")],
            [(2, " sql ")],
        )
