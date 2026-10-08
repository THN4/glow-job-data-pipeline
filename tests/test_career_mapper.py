from src.config.settings import load_settings
from src.transform.career_mapper import map_careers
from src.transform.job_title_normalizer import normalize_job_title


def test_normalize_job_title_removes_seniority_and_formatting() -> None:
    assert normalize_job_title("Senior / Staff Data Engineer II") == "Data Engineer"


def test_map_careers_uses_title_alias_and_preserves_original_title() -> None:
    entry = {
        "job": {"job_title": "Senior / Staff Data Engineer (BI)"},
        "metadata": {"career_slug": "backend_engineer"},
    }

    mapped = map_careers([entry], load_settings().careers)[0]

    assert mapped["job"]["job_title"] == "Senior / Staff Data Engineer (BI)"
    assert mapped["job"]["normalized_job_title"] == "Data Engineer"
    assert mapped["job"]["career_slug"] == "data_engineer"
    assert mapped["job"]["career_name"] == "Data Engineer"
    assert mapped["job"]["career_profile_slug"] == "data_engineer_general"
    assert mapped["job"]["career_mapping_status"] == "mapped"
    assert mapped["job"]["career_mapping_method"] == "title_alias"


def test_map_careers_maps_backend_developer_to_backend_engineer() -> None:
    entry = {"job": {"job_title": "Backend Developer"}}

    mapped = map_careers([entry], load_settings().careers)[0]

    assert mapped["job"]["normalized_job_title"] == "Backend Engineer"
    assert mapped["job"]["career_slug"] == "backend_engineer"


def test_new_careers_map_distinct_title_aliases() -> None:
    titles = {
        "Senior GenAI Engineer": "ai_engineer",
        "Junior Data Scientist": "data_scientist",
        "Business Intelligence Analyst": "data_analyst",
        "Senior Analytics Engineer": "analytics_engineer",
    }

    for title, expected_slug in titles.items():
        mapped = map_careers(
            [{"job": {"job_title": title}}], load_settings().careers
        )[0]
        assert mapped["job"]["career_slug"] == expected_slug
        assert mapped["job"]["career_mapping_status"] == "mapped"


def test_map_careers_uses_single_query_career_as_fallback() -> None:
    entry = {
        "job": {"job_title": "Software Engineer"},
        "metadata": {"career_slug": "backend_engineer"},
    }

    mapped = map_careers([entry], load_settings().careers)[0]

    assert mapped["job"]["career_slug"] == "backend_engineer"
    assert mapped["job"]["career_mapping_method"] == "query_context"


def test_map_careers_marks_conflicting_query_context_ambiguous() -> None:
    entry = {
        "job": {"job_title": "Software Engineer"},
        "matches": [
            {"career_slug": "data_engineer"},
            {"career_slug": "backend_engineer"},
        ],
    }

    mapped = map_careers([entry], load_settings().careers)[0]

    assert mapped["job"]["career_slug"] is None
    assert mapped["job"]["career_profile_slug"] is None
    assert mapped["job"]["career_mapping_status"] == "ambiguous"
    assert mapped["job"]["career_candidates"] == [
        "backend_engineer",
        "data_engineer",
    ]


def test_map_careers_keeps_unknown_title_unmapped_and_does_not_mutate_input() -> None:
    entry = {"job": {"job_title": "Regional Operations Coordinator"}}

    mapped = map_careers([entry], load_settings().careers)[0]

    assert mapped["job"]["normalized_job_title"] == "Regional Operations Coordinator"
    assert mapped["job"]["career_slug"] is None
    assert mapped["job"]["career_mapping_status"] == "unmapped"
    assert "career_mapping_status" not in entry["job"]
