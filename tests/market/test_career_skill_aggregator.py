from decimal import Decimal

from src.market.aggregation.skill_aggregator import aggregate_career_skills


def test_counts_completed_jobs_without_skills_in_each_career_denominator():
    postings = [(10, 1), (11, 1), (12, 1), (20, 2)]
    skills = [
        (10, 1, "required", "intermediate", Decimal("0.91")),
        (11, 1, "preferred", "advanced", Decimal("0.60")),
        (10, 2, "required", "unknown", Decimal("0.88")),
        (20, 1, "optional", "beginner", Decimal("0.30")),
    ]

    result = aggregate_career_skills(postings, skills)
    by_key = {(row.career_profile_id, row.skill_id): row for row in result}

    sql = by_key[(1, 1)]
    assert (sql.demand_count, sql.total_jobs, sql.demand_percentage) == (
        2, 3, Decimal("66.67")
    )
    assert (sql.required_count, sql.preferred_count, sql.optional_count) == (1, 1, 0)
    assert sql.weighted_demand_score == Decimal("0.5033")
    assert (sql.target_level, sql.target_level_confidence, sql.level_observation_count) == (
        "unknown", None, 2
    )

    python = by_key[(1, 2)]
    assert python.demand_percentage == Decimal("33.33")
    assert python.weighted_demand_score == Decimal("0.2933")
    assert python.level_observation_count == 0
    assert by_key[(2, 1)].demand_percentage == Decimal("100.00")


def test_target_level_confidence_is_share_of_known_levels():
    postings = [(1, 1), (2, 1), (3, 1)]
    skills = [
        (1, 7, "required", "intermediate", Decimal("0.85")),
        (2, 7, "required", "intermediate", Decimal("0.85")),
        (3, 7, "required", "advanced", Decimal("0.90")),
    ]

    stat = aggregate_career_skills(postings, skills)[0]

    assert stat.target_level == "intermediate"
    assert stat.target_level_confidence == Decimal("0.667")
    assert stat.level_observation_count == 3
