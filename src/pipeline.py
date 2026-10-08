"""Run the existing local market pipeline stages in order."""

import logging
from datetime import date, datetime, timezone

from src.load.career_skill_aggregator import refresh_career_skill_stats
from src.load.job_skill_loader import load_job_skills_from_run
from src.main import main as process_jobs


logger = logging.getLogger(__name__)


def run_pipeline(
    *,
    replay_run_id: str | None = None,
    replay_query_count: int | None = None,
    live: bool = False,
    start_date: date,
    end_date: date,
    skill_limit: int | None = None,
    skill_request_interval: float = 10.0,
) -> dict[str, object]:
    """Process jobs, load completed skills, then refresh a market window.

    A failed stage stops the run. The existing skill checkpoint allows replay
    to resume without repeating completed Gemini requests.
    """
    if live == (replay_run_id is not None):
        raise ValueError("Choose exactly one of live or replay_run_id")
    if replay_query_count is not None and (
        replay_run_id is None
        or isinstance(replay_query_count, bool)
        or replay_query_count < 1
    ):
        raise ValueError("replay_query_count must be positive and requires replay_run_id")
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if skill_limit is not None and (
        isinstance(skill_limit, bool) or skill_limit < 1
    ):
        raise ValueError("skill_limit must be positive")
    if skill_request_interval < 0:
        raise ValueError("skill_request_interval must be non-negative")

    run_id = replay_run_id or datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    logger.info("Pipeline starting: run_id=%s", run_id)
    jobs = process_jobs(
        replay_run_id=replay_run_id,
        replay_query_count=replay_query_count,
        new_run_id=run_id if live else None,
        extract_skills=True,
        skill_limit=skill_limit,
        skill_request_interval=skill_request_interval,
    )
    failed = sum(job.get("extraction_status") != "completed" for job in jobs)
    if failed:
        raise RuntimeError(
            f"Skill extraction incomplete for {failed} jobs in run {run_id}; "
            "resume the same run before loading"
        )
    logger.info("Skill extraction ready: run_id=%s, jobs=%d", run_id, len(jobs))

    loaded = load_job_skills_from_run(run_id)
    logger.info("Job skills loaded: run_id=%s, result=%s", run_id, loaded)
    aggregated = refresh_career_skill_stats(start_date, end_date)
    logger.info("Career skill stats refreshed: result=%s", aggregated)
    return {
        "run_id": run_id,
        "processed_jobs": len(jobs),
        "loaded": loaded,
        "aggregation": aggregated,
    }
