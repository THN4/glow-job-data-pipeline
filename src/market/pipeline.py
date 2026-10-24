"""Run the existing local market pipeline stages in order."""

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from src.market.aggregation.career_skill_aggregator import refresh_career_skill_stats
from src.market.skill_extraction.job_skill_loader import load_job_skills_from_run
from src.market.main import main as process_jobs
from src.market.ingestion.raw_storage import validate_run_id


logger = logging.getLogger(__name__)


def run_pipeline(
    *,
    replay_run_id: str | None = None,
    replay_query_count: int | None = None,
    live: bool = False,
    start_date: date,
    end_date: date,
    date_basis: str = "posted_at",
    skill_limit: int | None = None,
    skill_request_interval: float = 10.0,
    new_run_id: str | None = None,
    resume_raw: bool = False,
    raw_output_dir: Path | None = None,
    skill_output_dir: Path | None = None,
    company_review_output_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
    artifact_saved: Callable[[str, Path], None] | None = None,
) -> dict[str, object]:
    """Process jobs, load completed skills, then refresh a market window.

    A failed stage stops the run. The existing skill checkpoint allows replay
    to resume without repeating completed Nova 2 Lite requests.
    """
    if live == (replay_run_id is not None):
        raise ValueError("Choose exactly one of live or replay_run_id")
    if new_run_id is not None and not live:
        raise ValueError("new_run_id requires live mode")
    if resume_raw and (not live or new_run_id is None):
        raise ValueError("resume_raw requires live mode with the original run ID")
    if replay_query_count is not None and (
        replay_run_id is None
        or isinstance(replay_query_count, bool)
        or replay_query_count < 1
    ):
        raise ValueError("replay_query_count must be positive and requires replay_run_id")
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if date_basis not in {"posted_at", "first_seen_at"}:
        raise ValueError("date_basis must be 'posted_at' or 'first_seen_at'")
    if skill_limit is not None and (
        isinstance(skill_limit, bool) or skill_limit < 1
    ):
        raise ValueError("skill_limit must be positive")
    if skill_request_interval < 0:
        raise ValueError("skill_request_interval must be non-negative")

    run_id = replay_run_id or new_run_id or datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    validate_run_id(run_id)
    extra = {}
    for name, value in (("raw_output_dir", raw_output_dir), ("skill_output_dir", skill_output_dir),
                        ("company_review_output_dir", company_review_output_dir)):
        if value is not None:
            extra[name] = value
    if resume_raw:
        extra["resume_raw"] = True
    if artifact_saved is not None:
        extra["artifact_saved"] = artifact_saved
    logger.info("Pipeline starting: run_id=%s", run_id)
    if progress:
        progress("ingestion_and_skill_extraction")
    jobs = process_jobs(
        replay_run_id=replay_run_id,
        replay_query_count=replay_query_count,
        new_run_id=run_id if live else None,
        extract_skills=True,
        skill_limit=skill_limit,
        skill_request_interval=skill_request_interval,
        **extra,
    )
    failed = sum(job.get("extraction_status") != "completed" for job in jobs)
    if failed:
        raise RuntimeError(
            f"Skill extraction incomplete for {failed} jobs in run {run_id}; "
            "resume the same run before loading"
        )
    logger.info("Skill extraction ready: run_id=%s, jobs=%d", run_id, len(jobs))

    if progress:
        progress("database_load")
    if jobs:
        load_options = {"output_dir": skill_output_dir} if skill_output_dir is not None else {}
        loaded = load_job_skills_from_run(run_id, **load_options)
    else:
        loaded = {"postings_loaded": 0, "skills_loaded": 0}
    logger.info("Job skills loaded: run_id=%s, result=%s", run_id, loaded)
    if progress:
        progress("aggregation")
    aggregated = refresh_career_skill_stats(
        start_date, end_date, date_basis=date_basis
    )
    logger.info(
        "Career skill stats refreshed: date_basis=%s, result=%s",
        date_basis,
        aggregated,
    )
    return {
        "run_id": run_id,
        "processed_jobs": len(jobs),
        "loaded": loaded,
        "aggregation": aggregated,
    }
