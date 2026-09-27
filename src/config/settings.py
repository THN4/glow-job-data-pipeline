"""Load the local pipeline and career configuration."""

from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PipelineSettings:
    country: str
    time_window_days: int
    results_per_query: int
    max_pages: int
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
    num_pages: int
    date_posted: str


@dataclass(frozen=True)
class Settings:
    pipeline: PipelineSettings
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
    jsearch_data = pipeline_data.pop(
        "jsearch",
        {
            "method": "GET",
            "url": "https://jsearch.p.rapidapi.com/search-v2",
            "host": "jsearch.p.rapidapi.com",
            "content_type": "application/json",
            "api_key_env": "JSEARCH_API_KEY",
            "num_pages": 1,
            "date_posted": "all",
        },
    )

    try:
        pipeline = PipelineSettings(**pipeline_data)
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

    if not isinstance(pipeline.country, str) or not pipeline.country.strip():
        raise ValueError("Pipeline settings require a country")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (
            jsearch.method,
            jsearch.url,
            jsearch.host,
            jsearch.content_type,
            jsearch.api_key_env,
            jsearch.date_posted,
        )
    ):
        raise ValueError("JSearch settings require non-empty text values")
    if jsearch.method.upper() != "GET":
        raise ValueError("JSearch method must be GET")
    if (
        not isinstance(jsearch.num_pages, int)
        or isinstance(jsearch.num_pages, bool)
        or jsearch.num_pages <= 0
    ):
        raise ValueError("JSearch num_pages must be a positive integer")
    for value in (
        pipeline.time_window_days,
        pipeline.results_per_query,
        pipeline.max_pages,
        pipeline.minimum_description_length,
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("Pipeline limits must be positive integers")
    for career in careers.values():
        if (
            not isinstance(career.career_name, str)
            or not career.career_name.strip()
            or not career.queries
            or any(not isinstance(query, str) or not query.strip() for query in career.queries)
        ):
            raise ValueError("Every career requires a name and at least one search query")

    return Settings(pipeline=pipeline, careers=careers, jsearch=jsearch)
