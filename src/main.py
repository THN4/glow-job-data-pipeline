"""Local entry point for extracting or replaying raw job data."""

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config.logging import configure_logging
from src.config.settings import load_settings
from src.extract.extract_jobs import extract_jobs
from src.storage.raw_storage import load_raw_result


def main(
    *,
    replay_run_id: str | None = None,
    raw_output_dir: Path = Path("data/raw"),
) -> list[dict[str, object]]:
    """Load a previous raw run or fetch and save a new one."""
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

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract or replay raw job data.")
    parser.add_argument(
        "--replay-run-id",
        help="Load a previously saved raw run instead of calling JSearch.",
    )
    arguments = parser.parse_args()
    result = main(replay_run_id=arguments.replay_run_id)
