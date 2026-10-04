"""Map job titles to configured career categories and general profiles."""

import re

from src.config.settings import CareerSettings
from src.transform.job_title_normalizer import normalize_job_title

CareerDefinitions = dict[str, CareerSettings]
JobEntry = dict[str, object]


def _title_key(value: object) -> str | None:
    title = normalize_job_title(value)
    if title is None:
        return None
    key = " ".join(title.casefold().split())
    return key or None


def _contains_title_alias(title_key: str, alias_key: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(alias_key)}(?!\w)", title_key) is not None


def _configured_title_matches(
    title_key: str, careers: CareerDefinitions
) -> list[str]:
    matches = []
    for slug, career in careers.items():
        aliases = (career.career_name, *career.title_aliases)
        alias_keys = {key for alias in aliases if (key := _title_key(alias)) is not None}
        if any(_contains_title_alias(title_key, alias_key) for alias_key in alias_keys):
            matches.append(slug)
    return matches


def _query_career_slugs(entry: JobEntry, careers: CareerDefinitions) -> list[str]:
    matches = entry.get("matches")
    references = matches if isinstance(matches, list) else []
    if not references:
        metadata = entry.get("metadata")
        references = [metadata] if isinstance(metadata, dict) else []

    slugs = {
        reference.get("career_slug")
        for reference in references
        if isinstance(reference, dict)
        and isinstance(reference.get("career_slug"), str)
        and reference.get("career_slug") in careers
    }
    return sorted(slugs)


def _attach_mapping(
    job: dict[str, object],
    *,
    normalized_title: str | None,
    career_slug: str | None,
    careers: CareerDefinitions,
    status: str,
    method: str,
    candidates: list[str] | None = None,
) -> None:
    career = careers.get(career_slug) if career_slug is not None else None
    job["normalized_job_title"] = career.career_name if career is not None else normalized_title
    job["career_slug"] = career_slug
    job["career_name"] = career.career_name if career is not None else None
    job["career_profile_slug"] = f"{career_slug}_general" if career is not None else None
    job["career_mapping_status"] = status
    job["career_mapping_method"] = method
    job["career_candidates"] = candidates or []


def map_careers(
    jobs: list[JobEntry], careers: CareerDefinitions
) -> list[JobEntry]:
    """Return copied entries with normalized titles and career mapping fields.

    Title rules take precedence. A unique query career is a fallback for generic
    titles. Conflicting or missing evidence leaves the job unmapped.
    """
    mapped_jobs: list[JobEntry] = []
    for entry in jobs:
        output_entry = dict(entry)
        source_job = entry.get("job")
        if not isinstance(source_job, dict):
            mapped_jobs.append(output_entry)
            continue

        job = dict(source_job)
        raw_title = job.get("job_title")
        normalized_title = normalize_job_title(raw_title)
        title_key = _title_key(raw_title)
        title_matches = (
            _configured_title_matches(title_key, careers)
            if title_key is not None
            else []
        )

        if len(title_matches) == 1:
            _attach_mapping(
                job,
                normalized_title=normalized_title,
                career_slug=title_matches[0],
                careers=careers,
                status="mapped",
                method="title_alias",
            )
        elif len(title_matches) > 1:
            _attach_mapping(
                job,
                normalized_title=normalized_title,
                career_slug=None,
                careers=careers,
                status="ambiguous",
                method="title_alias_conflict",
                candidates=title_matches,
            )
        else:
            query_slugs = _query_career_slugs(entry, careers)
            if len(query_slugs) == 1:
                _attach_mapping(
                    job,
                    normalized_title=normalized_title,
                    career_slug=query_slugs[0],
                    careers=careers,
                    status="mapped",
                    method="query_context",
                )
            elif len(query_slugs) > 1:
                _attach_mapping(
                    job,
                    normalized_title=normalized_title,
                    career_slug=None,
                    careers=careers,
                    status="ambiguous",
                    method="query_context_conflict",
                    candidates=query_slugs,
                )
            else:
                _attach_mapping(
                    job,
                    normalized_title=normalized_title,
                    career_slug=None,
                    careers=careers,
                    status="unmapped",
                    method="no_match",
                )

        output_entry["job"] = job
        mapped_jobs.append(output_entry)

    return mapped_jobs
