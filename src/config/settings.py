"""Load the local search, validation, and provider configuration."""

from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_DATE_POSTED = {"all", "today", "3days", "week", "month"}


@dataclass(frozen=True)
class SearchSettings:
    country: str
    max_pages: int
    date_posted: str


@dataclass(frozen=True)
class ValidationSettings:
    time_window_days: int
    minimum_description_length: int


@dataclass(frozen=True)
class CareerSettings:
    career_name: str
    queries: tuple[str, ...]


@dataclass(frozen=True)
class JSearchSettings:
    method: str
    url: str
    host: str
    content_type: str
    api_key_env: str


@dataclass(frozen=True)
class Settings:
    search: SearchSettings
    validation: ValidationSettings
    careers: dict[str, CareerSettings]
    jsearch: JSearchSettings


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return data


def load_settings(config_dir: Path | None = None) -> Settings:
    """Read YAML settings and load local secrets for later pipeline stages."""
    load_dotenv(PROJECT_ROOT / ".env")
    directory = config_dir if config_dir is not None else PROJECT_ROOT / "config"
    pipeline_data = _read_yaml(directory / "pipeline.yaml")
    careers_data = _read_yaml(directory / "careers.yaml")
    jsearch_data = pipeline_data.get(
        "jsearch",
        {
            "method": "GET",
            "url": "https://jsearch.p.rapidapi.com/search-v2",
            "host": "jsearch.p.rapidapi.com",
            "content_type": "application/json",
            "api_key_env": "JSEARCH_API_KEY",
        },
    )

    try:
        search = SearchSettings(**pipeline_data["search"])
        validation = ValidationSettings(**pipeline_data["validation"])
        jsearch = JSearchSettings(**jsearch_data)
        career_entries = careers_data["careers"]
        if not isinstance(career_entries, dict) or not career_entries:
            raise ValueError("careers must be a non-empty mapping")
        for slug, entry in career_entries.items():
            if not isinstance(slug, str) or not isinstance(entry, dict):
                raise ValueError("Each career must have a slug and a mapping of settings")
            if not isinstance(entry.get("queries"), list):
                raise ValueError(f"Career {slug} must have a list of search queries")
        careers = {
            slug: CareerSettings(
                career_name=entry["career_name"],
                queries=tuple(entry["queries"]),
            )
            for slug, entry in career_entries.items()
        }
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Invalid configuration in {directory}: {exc}") from exc

    if not isinstance(search.country, str) or not search.country.strip():
        raise ValueError("Search settings require a country")
    if (
        not isinstance(search.max_pages, int)
        or isinstance(search.max_pages, bool)
        or search.max_pages <= 0
    ):
        raise ValueError("Search max_pages must be a positive integer")
    if (
        not isinstance(search.date_posted, str)
        or search.date_posted not in SUPPORTED_DATE_POSTED
    ):
        raise ValueError(
            "Search date_posted must be one of: "
            + ", ".join(sorted(SUPPORTED_DATE_POSTED))
        )
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (
            jsearch.method,
            jsearch.url,
            jsearch.host,
            jsearch.content_type,
            jsearch.api_key_env,
        )
    ):
        raise ValueError("JSearch settings require non-empty text values")
    if jsearch.method.upper() != "GET":
        raise ValueError("JSearch method must be GET")
    for value in (
        validation.time_window_days,
        validation.minimum_description_length,
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("Validation limits must be positive integers")
    for career in careers.values():
        if (
            not isinstance(career.career_name, str)
            or not career.career_name.strip()
            or not career.queries
            or any(not isinstance(query, str) or not query.strip() for query in career.queries)
        ):
            raise ValueError("Every career requires a name and at least one search query")

    return Settings(
        search=search,
        validation=validation,
        careers=careers,
        jsearch=jsearch,
    )
