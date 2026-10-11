"""PostgreSQL connection helper for pipeline runtime code and maintenance scripts."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def get_database_connection() -> psycopg.Connection:
    """Connect using DB_HOST, DB_PORT, DB_NAME, DB_USER, and DB_PASSWORD."""
    load_dotenv(PROJECT_ROOT / ".env")

    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError("Missing database settings in .env: " + ", ".join(missing))

    try:
        port = int(os.environ["DB_PORT"])
    except ValueError as exc:
        raise ValueError("DB_PORT must be an integer") from exc

    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=port,
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
