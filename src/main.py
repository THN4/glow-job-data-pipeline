"""Local entry point for checking project configuration."""

import logging

from src.config.logging import configure_logging
from src.config.settings import load_settings


def main() -> None:
    settings = load_settings()
    configure_logging()
    logging.getLogger(__name__).info(
        "Pipeline configuration loaded: country=%s, careers=%d",
        settings.pipeline.country,
        len(settings.careers),
    )


if __name__ == "__main__":
    main()
