"""Local entry point for checking project configuration."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config.logging import configure_logging
from src.config.settings import load_settings

from src.extract.extract_jobs import extract_jobs


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)

    settings = load_settings()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    raw_output_dir = Path("data/raw")

    # Configure
    logger.info(
        "Starting job extraction: country=%s, careers=%d",
        settings.pipeline.country,
        len(settings.careers),
    )

    # Extraction
    extracted_results = extract_jobs(
        settings,
        output_dir=raw_output_dir,
        run_id=run_id,
    )

    logger.info(
        "Extraction completed: %d query responses received",
        len(extracted_results),
    )


if __name__ == "__main__":
    main()
