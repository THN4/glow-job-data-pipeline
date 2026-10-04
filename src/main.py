"""Local entry point for extracting or replaying raw job data."""

import argparse
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.config.logging import configure_logging
from src.config.settings import load_settings
from src.extract.extract_jobs import extract_jobs
from src.storage.raw_storage import load_raw_result
from src.storage.company_review_storage import save_company_match_candidates
from src.transform.job_cleaner import clean_jobs
from src.transform.deduplicator import deduplicate_jobs
from src.transform.company_normalizer import normalize_job_companies
from src.transform.career_mapper import map_careers
from src.validation.job_validator import validate_jobs


def main(
    *,
    replay_run_id: str | None = None,
    raw_output_dir: Path = Path("data/raw"),
    company_review_output_dir: Path = Path(
        "data/processed/company_match_candidates"
    ),
) -> list[dict[str, object]]:
    """Load or fetch raw data, then return deduplicated cleaned job records."""
    configure_logging()
    logger = logging.getLogger(__name__)
    settings = load_settings()

    if replay_run_id is not None:
        active_run_id = replay_run_id
        expected_query_count = sum(
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
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        active_run_id = run_id
        logger.info(
            "Starting job extraction: run_id=%s, country=%s, careers=%d",
            run_id,
            settings.search.country,
            len(settings.careers),
        )
        results = extract_jobs(
            settings,
            output_dir=raw_output_dir,
            run_id=run_id,
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

    return career_mapped_jobs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract or replay raw job data.")
    parser.add_argument(
        "--replay-run-id",
        help="Load a previously saved raw run instead of calling JSearch.",
    )
    arguments = parser.parse_args()
    result = main(replay_run_id=arguments.replay_run_id)
