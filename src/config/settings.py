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
class Settings:
    pipeline: PipelineSettings
    careers: dict[str, CareerSettings]


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

    try:
        pipeline = PipelineSettings(**pipeline_data)
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

    return Settings(pipeline=pipeline, careers=careers)
