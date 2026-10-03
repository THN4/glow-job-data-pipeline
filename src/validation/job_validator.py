"""Validate JSearch job records before they enter later pipeline stages."""

from datetime import datetime, timedelta, timezone
from typing import TypeAlias

from src.config.settings import Settings
from src.utils.job_dates import parse_job_posted_at

JobRecord: TypeAlias = dict[str, object]
ValidatedJob: TypeAlias = dict[str, object]

_COUNTRY_ALIASES = {"THAILAND": "TH"}


def _text(value: object) -> str | None:
    """Return non-empty text values, ignoring nulls and whitespace-only strings."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _country_code(value: object) -> str | None:
    country = _text(value)
    if country is None:
        return None
    normalized = country.upper()
    return _COUNTRY_ALIASES.get(normalized, normalized)


def _job_errors(
    job: JobRecord,
    *,
    expected_country: str,
    minimum_description_length: int,
    time_window_days: int,
    now: datetime,
    collected_at: object,
) -> list[str]:
    errors: list[str] = []

    title = _text(job.get("job_title"))
    if title is None:
        errors.append("missing job title")

    description = _text(job.get("job_description"))
    if description is None:
        errors.append("missing job description")
    elif len(description) < minimum_description_length:
        errors.append(
            "job description is shorter than "
            f"{minimum_description_length} characters"
        )

    actual_country = _country_code(job.get("job_country")) or _country_code(
        job.get("job_country_code")
    )
    if actual_country is None:
        errors.append("missing job country")
    elif actual_country != expected_country:
        errors.append(
            f"job country {actual_country} is outside selected country "
            f"{expected_country}"
        )

    provider_id = job.get("job_id")
    has_provider_id = (
        _text(provider_id) is not None
        or isinstance(provider_id, int)
        and not isinstance(provider_id, bool)
    )
    has_job_url = _text(job.get("job_apply_link")) is not None or _text(
        job.get("job_url")
    ) is not None
    has_fallback_key = (
        _text(job.get("employer_name")) is not None
        and title is not None
        and (
            _text(job.get("job_location")) is not None
            or _text(job.get("job_city")) is not None
        )
    )
    if not (has_provider_id or has_job_url or has_fallback_key):
        errors.append("missing stable job identifier")

    posted_at, _ = parse_job_posted_at(
        job,
        collected_at=collected_at,
        fallback_time=now,
    )
    if posted_at is None:
        has_date_value = any(
            job.get(field) not in (None, "")
            for field in (
                "job_posted_at_datetime_utc",
                "job_posted_at_timestamp",
                "job_posted_at",
            )
        )
        if not has_date_value:
            errors.append("missing posted date")
        else:
            errors.append("invalid posted date")
    else:
        try:
            reference_time = datetime.fromisoformat(
                str(collected_at).replace("Z", "+00:00")
            )
            if reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=timezone.utc)
            reference_time = reference_time.astimezone(timezone.utc)
        except ValueError:
            reference_time = now
        if posted_at < reference_time - timedelta(days=time_window_days):
            errors.append(f"posted date is older than {time_window_days} days")

    return errors


def validate_jobs(
    query_results: list[dict[str, object]],
    settings: Settings,
) -> tuple[list[ValidatedJob], list[ValidatedJob]]:
    """Split saved query responses into valid and invalid job records.

    Each returned item contains the original ``job`` and its query ``metadata``.
    Invalid items also contain an ``errors`` list with human-readable reasons.
    """
    valid_jobs: list[ValidatedJob] = []
    invalid_jobs: list[ValidatedJob] = []
    expected_country = _country_code(settings.search.country) or ""
    now = datetime.now(timezone.utc)

    for query_result in query_results:
        metadata = {
            key: value for key, value in query_result.items() if key != "response"
        }
        response = query_result.get("response")
        data = response.get("data") if isinstance(response, dict) else None

        if not isinstance(data, list):
            invalid_jobs.append(
                {
                    "job": None,
                    "metadata": metadata,
                    "errors": ["response data is missing or is not a list"],
                }
            )
            continue

        for job in data:
            if not isinstance(job, dict):
                invalid_jobs.append(
                    {
                        "job": job,
                        "metadata": metadata,
                        "errors": ["job record is not an object"],
                    }
                )
                continue

            errors = _job_errors(
                job,
                expected_country=expected_country,
                minimum_description_length=settings.validation.minimum_description_length,
                time_window_days=settings.validation.time_window_days,
                now=now,
                collected_at=metadata.get("collected_at"),
            )
            result = {"job": job, "metadata": metadata}
            if errors:
                invalid_jobs.append({**result, "errors": errors})
            else:
                valid_jobs.append(result)

    return valid_jobs, invalid_jobs
