"""Shared logging setup for pipeline entry points."""

import logging
import os

 
def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
        "FATAL": logging.CRITICAL,
        "NOTSET": logging.NOTSET,
    }
    level = levels.get(level_name)
    if level is None:
        raise ValueError(f"Invalid LOG_LEVEL: {level_name}")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
