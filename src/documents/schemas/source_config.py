"""Validated configuration models for bounded document crawling."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml


@dataclass(frozen=True)
class SourceConfig:
    id: str
    career_tracks: tuple[str, ...]
    skills: tuple[str, ...]
    seed_urls: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    max_depth: int
    max_pages: int
    title: str | None = None
    publisher: str | None = None
    source_type: str = "web-documentation"
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    allowed_content_types: tuple[str, ...] = ("text/html",)
    review_required: bool = True


@dataclass(frozen=True)
class DocumentSourcesConfig:
    schema_version: int
    sources: tuple[SourceConfig, ...]


def _string(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(
    value: Any, field: str, *, required: bool = True
) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings")
    items = tuple(_string(item, f"{field}[]") for item in value)
    if required and not items:
        raise ValueError(f"{field} must not be empty")
    return items  # type: ignore[return-value]


def _seed_host_and_directory(url: str, field: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field} must be an absolute HTTP(S) URL")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError(f"{field} contains an invalid port") from error
    if parsed.username or parsed.password:
        raise ValueError(f"{field} must not contain URL credentials")
    path = parsed.path or "/"
    if path.endswith("/"):
        directory = path
    else:
        last_segment = path.rsplit("/", 1)[-1]
        directory = path[: path.rfind("/") + 1] if "." in last_segment else f"{path}/"
    return parsed.hostname.lower().rstrip("."), directory or "/"


def _path_is_within(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/") or "/"
    if normalized == "/":
        return path.startswith("/")
    return path == normalized or path.startswith(f"{normalized}/")


def _parse_source(raw: Any, index: int) -> SourceConfig:
    label = f"sources[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a mapping")

    source_id = _string(raw.get("id"), f"{label}.id")
    careers = _string_list(raw.get("career_tracks"), f"{label}.career_tracks")
    skills = _string_list(raw.get("skills"), f"{label}.skills")
    seeds = _string_list(raw.get("seed_urls"), f"{label}.seed_urls")

    seed_scopes = tuple(
        _seed_host_and_directory(url, f"{label}.seed_urls") for url in seeds
    )
    derived_hosts = tuple(dict.fromkeys(host for host, _ in seed_scopes))
    derived_paths = tuple(dict.fromkeys(path for _, path in seed_scopes))
    hosts = tuple(
        dict.fromkeys(
            host.lower().rstrip(".")
            for host in _string_list(
                raw.get("allowed_hosts", list(derived_hosts)),
                f"{label}.allowed_hosts",
            )
        )
    )
    if len(hosts) != 1:
        raise ValueError(
            f"{label} must target one host per source config; split different hosts"
        )
    paths = _string_list(
        raw.get("allowed_path_prefixes", list(derived_paths)),
        f"{label}.allowed_path_prefixes",
    )
    for prefix in paths:
        parsed_prefix = urlsplit(prefix)
        if not prefix.startswith("/") or parsed_prefix.query or parsed_prefix.fragment:
            raise ValueError(f"{label}.allowed_path_prefixes must be URL path prefixes")

    for seed in seeds:
        parsed = urlsplit(seed)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host not in hosts:
            raise ValueError(f"{label} seed host {host!r} is outside allowed_hosts")
        if not any(_path_is_within(parsed.path or "/", prefix) for prefix in paths):
            raise ValueError(f"{label} seed path {parsed.path!r} is outside allowed_path_prefixes")

    max_depth = raw.get("max_depth")
    max_pages = raw.get("max_pages")
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
        raise ValueError(f"{label}.max_depth must be an integer greater than or equal to 0")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError(f"{label}.max_pages must be a positive integer")

    include_patterns = _string_list(
        raw.get("include_patterns", []), f"{label}.include_patterns", required=False
    )
    exclude_patterns = _string_list(
        raw.get("exclude_patterns", []), f"{label}.exclude_patterns", required=False
    )
    content_types = _string_list(
        raw.get("allowed_content_types", ["text/html"]),
        f"{label}.allowed_content_types",
    )
    if any("/" not in content_type for content_type in content_types):
        raise ValueError(f"{label}.allowed_content_types must use MIME types")
    review_required = raw.get("review_required", True)
    if not isinstance(review_required, bool):
        raise ValueError(f"{label}.review_required must be a boolean")

    return SourceConfig(
        id=source_id,
        title=_string(raw.get("title"), f"{label}.title", optional=True),
        publisher=_string(raw.get("publisher"), f"{label}.publisher", optional=True),
        source_type=_string(raw.get("source_type", "web-documentation"), f"{label}.source_type"),
        career_tracks=careers,
        skills=skills,
        seed_urls=seeds,
        allowed_hosts=hosts,
        allowed_path_prefixes=paths,
        max_depth=max_depth,
        max_pages=max_pages,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        allowed_content_types=tuple(item.lower() for item in content_types),
        review_required=review_required,
    )


def load_document_sources(path: Path) -> DocumentSourcesConfig:
    """Load and validate YAML source configurations."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as yaml_file:
            raw = yaml.safe_load(yaml_file)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML in {path}: {error}") from error

    if not isinstance(raw, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError(f"Unsupported document source schema_version: {schema_version!r}")
    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("sources must be a non-empty list")

    sources = tuple(_parse_source(source, index) for index, source in enumerate(raw_sources))
    ids = [source.id for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Each source config id must be unique")
    return DocumentSourcesConfig(schema_version=schema_version, sources=sources)


def select_document_source(config: DocumentSourcesConfig, source_id: str) -> SourceConfig:
    """Return one source config by ID or raise a useful error."""
    for source in config.sources:
        if source.id == source_id:
            return source
    known_ids = ", ".join(source.id for source in config.sources)
    raise ValueError(f"Unknown source id {source_id!r}; configured IDs: {known_ids}")