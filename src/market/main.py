"""Local entry point for extracting or replaying raw job data."""

import argparse
import logging
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.market.config.logging import configure_logging
from src.market.config.settings import load_settings
from src.market.ingestion.extract_jobs import extract_jobs
from src.market.skill_extraction.extractor import EXTRACTION_PROMPT_VERSION, extract_skills_for_jobs
from src.shared.skill_normalization.normalizer import load_skill_catalog, normalize_skills_for_jobs
from src.market.ingestion.raw_storage import load_raw_result
from src.market.normalization.company_review_storage import save_company_match_candidates
from src.market.skill_extraction.skill_result_storage import load_skill_results, save_skill_results
from src.market.cleaning.job_cleaner import clean_jobs
from src.market.normalization.deduplicator import deduplicate_jobs
from src.market.normalization.company_normalizer import normalize_job_companies
from src.market.normalization.career_mapper import map_careers
from src.market.ingestion.validation.job_validator import validate_jobs


def main(
    *,
    replay_run_id: str | None = None,
    replay_query_count: int | None = None,
    new_run_id: str | None = None,
    extract_skills: bool = False,
    skill_limit: int | None = None,
    skill_request_interval: float = 10.0,
    skill_output_dir: Path = Path("data/processed/skill_extraction"),
    raw_output_dir: Path = Path("data/raw"),
    raw_s3_bucket: str | None = None,
    raw_s3_prefix: str = "raw/jsearch",
    resume_raw: bool = False,
    company_review_output_dir: Path = Path(
        "data/processed/company_match_candidates"
    ),
    artifact_saved: Callable[[str, Path], None] | None = None,
) -> list[dict[str, object]]:
    """Prepare job records and optionally extract their skills with Nova 2 Lite."""
    if replay_run_id is not None and new_run_id is not None:
        raise ValueError("Choose either replay_run_id or new_run_id")
    if resume_raw and (replay_run_id is not None or new_run_id is None):
        raise ValueError("resume_raw requires a new_run_id and cannot use strict replay")
    if replay_query_count is not None and (
        replay_run_id is None
        or isinstance(replay_query_count, bool)
        or replay_query_count < 1
    ):
        raise ValueError("replay_query_count must be positive and requires replay_run_id")
    if skill_limit is not None:
        if not extract_skills or isinstance(skill_limit, bool) or skill_limit < 1:
            raise ValueError("skill_limit must be positive and requires extract_skills")
    if skill_request_interval < 0:
        raise ValueError("skill_request_interval must be non-negative")
    configure_logging()
    logger = logging.getLogger(__name__)
    settings = load_settings()

    if replay_run_id is not None:
        active_run_id = replay_run_id
        expected_query_count = replay_query_count or sum(
            len(career.queries) for career in settings.careers.values()
        )
        logger.info("Replaying raw data: run_id=%s", replay_run_id)
        results = load_raw_result(
            output_dir=raw_output_dir,
            run_id=replay_run_id,
            expected_query_count=expected_query_count,
        )
        logger.info("Replay completed: %d query responses loaded", len(results))
    else:
        run_id = new_run_id or datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        active_run_id = run_id
        logger.info(
            "Starting job extraction: run_id=%s, country=%s, careers=%d",
            run_id,
            settings.search.country,
            len(settings.careers),
        )
        s3_bucket = (raw_s3_bucket or os.getenv("RAW_S3_BUCKET", "")).strip()
        if s3_bucket:
            s3_prefix = (
                os.getenv("RAW_S3_PREFIX", raw_s3_prefix).strip("/")
                or "raw/jsearch"
            )
            results = extract_jobs(
                settings,
                output_dir=raw_output_dir,
                run_id=run_id,
                s3_bucket=s3_bucket,
                s3_prefix=s3_prefix,
                **({"resume_raw": True} if resume_raw else {}),
            )
        else:
            results = extract_jobs(
                settings,
                output_dir=raw_output_dir,
                run_id=run_id,
                **({"resume_raw": True} if resume_raw else {}),
            )
        logger.info("Extraction completed: %d query responses received", len(results))

    valid_jobs, invalid_jobs = validate_jobs(results, settings)
    logger.info(
        "Validation completed: valid_jobs=%d, invalid_jobs=%d",
        len(valid_jobs),
        len(invalid_jobs),
    )
    if invalid_jobs:
        reason_counts = Counter(
            error
            for invalid_job in invalid_jobs
            for error in invalid_job["errors"]
        )
        logger.warning("Rejected job reasons: %s", dict(reason_counts))

    cleaned_jobs, cleaning_rejections = clean_jobs(valid_jobs, settings)
    logger.info(
        "Cleaning completed: cleaned_jobs=%d, rejected_after_cleaning=%d",
        len(cleaned_jobs),
        len(cleaning_rejections),
    )
    if cleaning_rejections:
        reason_counts = Counter(
            error
            for rejected_job in cleaning_rejections
            for error in rejected_job["errors"]
        )
        logger.warning("Cleaning rejection reasons: %s", dict(reason_counts))

    unique_jobs, duplicates = deduplicate_jobs(cleaned_jobs)
    logger.info(
        "Deduplication completed: unique_jobs=%d, duplicates_removed=%d",
        len(unique_jobs),
        len(duplicates),
    )

    normalized_jobs = normalize_job_companies(unique_jobs)
    confirmed_companies = sum(
        1
        for entry in normalized_jobs
        if isinstance(entry.get("job"), dict)
        and isinstance(entry["job"].get("company_normalization"), dict)
        and entry["job"]["company_normalization"].get("match_method")
        == "confirmed_alias"
    )
    company_candidates = sum(
        1
        for entry in normalized_jobs
        if isinstance(entry.get("job"), dict)
        and isinstance(entry["job"].get("company_normalization"), dict)
        and entry["job"]["company_normalization"].get("match_method")
        == "candidate_review"
    )
    logger.info(
        "Company normalization completed: jobs=%d, confirmed=%d, candidates_for_review=%d",
        len(normalized_jobs),
        confirmed_companies,
        company_candidates,
    )
    review_report = save_company_match_candidates(
        normalized_jobs,
        run_id=active_run_id,
        output_dir=company_review_output_dir,
    )
    if review_report is not None:
        logger.info("Company match review report saved: %s", review_report)
        if artifact_saved:
            artifact_saved("company_candidates.csv", review_report)

    career_mapped_jobs = map_careers(normalized_jobs, settings.careers)
    career_status_counts = Counter(
        entry["job"]["career_mapping_status"]
        for entry in career_mapped_jobs
        if isinstance(entry.get("job"), dict)
        and isinstance(entry["job"].get("career_mapping_status"), str)
    )
    logger.info(
        "Career mapping completed: mapped=%d, ambiguous=%d, unmapped=%d",
        career_status_counts.get("mapped", 0),
        career_status_counts.get("ambiguous", 0),
        career_status_counts.get("unmapped", 0),
    )

    if extract_skills:
        target_jobs = career_mapped_jobs[:skill_limit]
        saved_jobs = load_skill_results(
            run_id=active_run_id, output_dir=skill_output_dir
        )
        if len(saved_jobs) > len(career_mapped_jobs):
            raise ValueError("Skill checkpoint contains more jobs than the raw run")
        if skill_limit is not None and len(saved_jobs) > skill_limit:
            raise ValueError("skill_limit is smaller than the saved skill checkpoint")

        identity_fields = ("job_id", "job_url", "job_title", "job_description")
        for index, saved_entry in enumerate(saved_jobs):
            saved_job = saved_entry.get("job")
            current_job = career_mapped_jobs[index].get("job")
            if not isinstance(saved_job, dict) or not isinstance(current_job, dict) or any(
                saved_job.get(field) != current_job.get(field)
                for field in identity_fields
            ):
                raise ValueError(
                    "Skill checkpoint does not match the raw run at job "
                    f"{index + 1}"
                )
            if saved_entry.get("extraction_status") not in {"completed", "failed"} or not isinstance(
                saved_entry.get("skills"), list
            ):
                raise ValueError(f"Invalid skill checkpoint at job {index + 1}")

        skill_jobs = []
        last_request_started: float | None = None
        for index, entry in enumerate(target_jobs):
            if index < len(saved_jobs) and saved_jobs[index].get(
                "extraction_status"
            ) == "completed" and saved_jobs[index].get(
                "skill_extraction_prompt_version"
            ) == EXTRACTION_PROMPT_VERSION:
                completed_entry = dict(entry)
                completed_entry["skills"] = saved_jobs[index]["skills"]
                completed_entry["extraction_status"] = "completed"
                completed_entry[
                    "skill_extraction_prompt_version"
                ] = EXTRACTION_PROMPT_VERSION
                skill_jobs.append(completed_entry)
                continue

            if last_request_started is not None:
                wait_seconds = skill_request_interval - (
                    time.monotonic() - last_request_started
                )
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
            last_request_started = time.monotonic()
            result = extract_skills_for_jobs([entry])[0]
            if index < len(saved_jobs):
                saved_jobs[index] = result
            else:
                saved_jobs.append(result)
            checkpoint_path = save_skill_results(
                saved_jobs, run_id=active_run_id, output_dir=skill_output_dir
            )
            if artifact_saved:
                artifact_saved("skill_checkpoint.json", checkpoint_path)
            skill_jobs.append(result)

        if not saved_jobs:
            checkpoint_path = save_skill_results([], run_id=active_run_id, output_dir=skill_output_dir)
            if artifact_saved:
                artifact_saved("skill_checkpoint.json", checkpoint_path)
        skill_status_counts = Counter(
            entry.get("extraction_status") for entry in skill_jobs
        )
        logger.info(
            "Skill extraction completed: jobs=%d, completed=%d, failed=%d",
            len(skill_jobs),
            skill_status_counts.get("completed", 0),
            skill_status_counts.get("failed", 0),
        )
        if skill_jobs:
            catalog = load_skill_catalog()
            skill_jobs = normalize_skills_for_jobs(skill_jobs, catalog)
            checkpoint_path = save_skill_results(
                skill_jobs, run_id=active_run_id, output_dir=skill_output_dir
            )
            if artifact_saved:
                artifact_saved("skill_checkpoint.json", checkpoint_path)
            logger.info(
                "Skill normalization completed: matched=%d, unmatched=%d",
                sum(len(entry["normalized_skills"]) for entry in skill_jobs),
                sum(len(entry["unmatched_skills"]) for entry in skill_jobs),
            )
        logger.info(
            "Skill results saved: %s", skill_output_dir / f"{active_run_id}.json"
        )
        return skill_jobs

    return career_mapped_jobs


def cli() -> None:
    parser = argparse.ArgumentParser(description="Extract or replay raw job data.")
    parser.add_argument(
        "--replay-run-id",
        help="Load a previously saved raw run instead of calling JSearch.",
    )
    parser.add_argument(
        "--replay-query-count",
        type=int,
        help="Expected query count for a raw run saved under an older careers config.",
    )
    parser.add_argument(
        "--extract-skills",
        action="store_true",
        help="Call Nova 2 Lite once for each unique job after career mapping.",
    )
    parser.add_argument(
        "--skill-limit",
        type=int,
        help="Process only the first N unique jobs (requires --extract-skills).",
    )
    parser.add_argument(
        "--skill-request-interval",
        type=float,
        default=10.0,
        help="Minimum seconds between starts of new Nova 2 Lite requests (default: 10).",
    )
    arguments = parser.parse_args()
    result = main(
        replay_run_id=arguments.replay_run_id,
        replay_query_count=arguments.replay_query_count,
        extract_skills=arguments.extract_skills,
        skill_limit=arguments.skill_limit,
        skill_request_interval=arguments.skill_request_interval,
    )


if __name__ == "__main__":
    cli()
