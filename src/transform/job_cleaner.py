"""Clean validated JSearch job records while preserving query provenance."""

import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from src.config.settings import Settings
from src.utils.job_dates import parse_job_posted_at

_BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ol",
    "p",
    "section",
    "tr",
    "ul",
}
_TEXT_FIELDS = (
    "job_title",
    "job_description",
    "employer_name",
    "job_location",
    "job_city",
    "job_state",
    "job_country",
    "job_country_code",
    "job_employment_type",
    "job_publisher",
)
_URL_FIELDS = ("job_apply_link", "job_url", "employer_website")


class _DescriptionParser(HTMLParser):
    """Extract readable text and keep boundaries between HTML block elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag == "li":
            self.parts.append("\n")
        elif self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def _clean_text(value: object) -> object:
    if not isinstance(value, str):
        return value

    parser = _DescriptionParser()
    parser.feed(value)
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    cleaned = text.strip()
    return cleaned or None


def _clean_url(value: object) -> object:
    if not isinstance(value, str):
        return value
    cleaned = value.strip()
    return cleaned or None


def _normalize_country(job: dict[str, object]) -> None:
    value = job.get("job_country") or job.get("job_country_code")
    if not isinstance(value, str):
        return
    country = value.strip()
    if country.casefold() == "thailand":
        job["job_country"] = "TH"
    elif len(country) == 2:
        job["job_country"] = country.upper()
    elif country:
        job["job_country"] = country
    else:
        job["job_country"] = None


def clean_jobs(
    valid_jobs: list[dict[str, object]],
    settings: Settings,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Clean validated entries; return usable and newly unusable records.

    The source job dictionaries are copied. Each output keeps the original
    metadata; cleaned jobs gain ``posted_at`` and ``posted_at_is_estimated``.
    """
    cleaned_jobs: list[dict[str, object]] = []
    rejected_jobs: list[dict[str, object]] = []
    fallback_time = datetime.now(timezone.utc)

    for entry in valid_jobs:
        source_job = entry.get("job")
        if not isinstance(source_job, dict):
            rejected_jobs.append(
                {
                    **entry,
                    "errors": ["job record is not an object after validation"],
                }
            )
            continue

        job = dict(source_job)
        for field in _TEXT_FIELDS:
            if field in job:
                job[field] = _clean_text(job[field])
        for field in _URL_FIELDS:
            if field in job:
                job[field] = _clean_url(job[field])

        _normalize_country(job)

        metadata = entry.get("metadata")
        collected_at = (
            metadata.get("collected_at") if isinstance(metadata, dict) else None
        )
        posted_at, is_estimated = parse_job_posted_at(
            job,
            collected_at=collected_at,
            fallback_time=fallback_time,
        )
        job["posted_at"] = posted_at
        job["posted_at_is_estimated"] = is_estimated

        errors: list[str] = []
        if not isinstance(job.get("job_title"), str) or not job["job_title"]:
            errors.append("job title is empty after cleaning")

        description = job.get("job_description")
        minimum_length = settings.validation.minimum_description_length
        if not isinstance(description, str) or len(description) < minimum_length:
            errors.append(
                "job description is shorter than "
                f"{minimum_length} characters after cleaning"
            )

        if posted_at is None:
            errors.append("posted date could not be normalized")

        cleaned_entry = {**entry, "job": job}
        if errors:
            rejected_jobs.append({**cleaned_entry, "errors": errors})
        else:
            cleaned_jobs.append(cleaned_entry)

    return cleaned_jobs, rejected_jobs
