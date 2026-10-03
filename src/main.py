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
from src.transform.job_cleaner import clean_jobs
from src.validation.job_validator import validate_jobs


def main(
    *,
    replay_run_id: str | None = None,
    raw_output_dir: Path = Path("data/raw"),
) -> list[dict[str, object]]:
    """Load or fetch raw data, then return validated and cleaned job records."""
    configure_logging()
    logger = logging.getLogger(__name__)
    settings = load_settings()

    if replay_run_id is not None:
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

    return cleaned_jobs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract or replay raw job data.")
    parser.add_argument(
        "--replay-run-id",
        help="Load a previously saved raw run instead of calling JSearch.",
    )
    arguments = parser.parse_args()
    result = main(replay_run_id=arguments.replay_run_id)
