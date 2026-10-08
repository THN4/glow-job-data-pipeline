"""Refresh career skill statistics for a UTC posting-date window."""

from datetime import date, datetime, time, timedelta, timezone

from src.load.database import get_database_connection
from src.skills.aggregator import aggregate_career_skills


def refresh_career_skill_stats(start_date: date, end_date: date) -> dict[str, int]:
    """Replace one window's stats using all eligible postings currently in DB."""
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_exclusive = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)

    with get_database_connection() as connection:
        with connection.transaction():
            postings = connection.execute(
                """
                SELECT job_id, career_profile_id
                FROM market.job_postings
                WHERE skill_extraction_completed = true
                  AND NULLIF(BTRIM(job_description), '') IS NOT NULL
                  AND posted_at >= %s AND posted_at < %s
                ORDER BY job_id
                """,
                (start, end_exclusive),
            ).fetchall()
            job_ids = [job_id for job_id, _ in postings]
            skill_rows = (
                connection.execute(
                    """
                    SELECT job_id, skill_id, requirement_type, proficiency_level,
                           importance_weight
                    FROM market.job_skills
                    WHERE job_id = ANY(%s)
                    ORDER BY job_id, skill_id
                    """,
                    (job_ids,),
                ).fetchall()
                if job_ids
                else []
            )
            stats = aggregate_career_skills(postings, skill_rows)
            connection.execute(
                """
                DELETE FROM market.career_skill_stats
                WHERE analysis_start_date = %s AND analysis_end_date = %s
                """,
                (start_date, end_date),
            )
            if stats:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO market.career_skill_stats (
                            career_profile_id, skill_id, analysis_start_date,
                            analysis_end_date, demand_count, total_jobs,
                            demand_percentage, required_count, preferred_count,
                            optional_count, weighted_demand_score, target_level,
                            target_level_confidence, level_observation_count,
                            importance_tier
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, 'unknown'
                        )
                        """,
                        [
                            (
                                stat.career_profile_id,
                                stat.skill_id,
                                start_date,
                                end_date,
                                stat.demand_count,
                                stat.total_jobs,
                                stat.demand_percentage,
                                stat.required_count,
                                stat.preferred_count,
                                stat.optional_count,
                                stat.weighted_demand_score,
                                stat.target_level,
                                stat.target_level_confidence,
                                stat.level_observation_count,
                            )
                            for stat in stats
                        ],
                    )
    return {
        "eligible_jobs": len(postings),
        "career_profiles": len({profile_id for _, profile_id in postings}),
        "skill_stats": len(stats),
    }
