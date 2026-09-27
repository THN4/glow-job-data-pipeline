"""Local entry point for checking project configuration."""

import logging

from src.config.logging import configure_logging
from src.config.settings import load_settings

from src.extract.extract_jobs import extract_jobs

def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    
    settings = load_settings()

    # Configure
    logger.info(
        "Starting job extraction: country=%s, careers=%d",
        settings.pipeline.country,
        len(settings.careers),
    )

    # Extraction
    extracted_results = extract_jobs(settings) 
    
    logger.info(
        "Extraction completed: %d query responses received",
        len(extracted_results),
    )
    
    
if __name__ == "__main__":
    main()
