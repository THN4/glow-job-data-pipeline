"""Remove repeated job postings while keeping all search provenance."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

JobEntry = dict[str, object]
IdentityKey = tuple[str, str]


def _normalized_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    return normalized or None


def _provider_job_id(job: dict[str, object]) -> str | None:
    value = job.get("job_id")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalized_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None

    raw_url = value.strip()
    try:
        parsed = urlsplit(raw_url)
        if not parsed.scheme or not parsed.netloc:
            return raw_url.split("#", maxsplit=1)[0].rstrip("/").casefold() or None

        scheme = parsed.scheme.casefold()
        hostname = parsed.hostname
        if hostname is None:
            return None
        hostname = hostname.casefold()
        port = parsed.port
        if port is not None and not (
            (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
        ):
            hostname = f"{hostname}:{port}"

        path = parsed.path.rstrip("/") or "/"
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        return urlunsplit((scheme, hostname, path, query, ""))
    except ValueError:
        return raw_url.split("#", maxsplit=1)[0].rstrip("/").casefold() or None


def _source_url_keys(job: dict[str, object]) -> set[IdentityKey]:
    keys: set[IdentityKey] = set()
    publisher = _normalized_text(job.get("job_publisher")) or ""

    for field in ("job_apply_link", "job_url"):
        url = _normalized_url(job.get(field))
        if url is not None:
            keys.add(("source_url", f"{publisher}|{url}"))

    apply_options = job.get("apply_options")
    if isinstance(apply_options, list):
        for option in apply_options:
            if not isinstance(option, dict):
                continue
            url = _normalized_url(option.get("apply_link"))
            if url is None:
                continue
            option_publisher = _normalized_text(option.get("publisher")) or ""
            keys.add(("source_url", f"{option_publisher}|{url}"))

    return keys


def _identity_keys(job: dict[str, object]) -> list[IdentityKey]:
    keys: list[IdentityKey] = []

    provider_job_id = _provider_job_id(job)
    if provider_job_id is not None:
        keys.append(("provider_job_id", provider_job_id))

    keys.extend(sorted(_source_url_keys(job)))

    return keys


def _has_conflicting_strong_identity(
    first: dict[str, object], second: dict[str, object]
) -> bool:
    first_id = _provider_job_id(first)
    second_id = _provider_job_id(second)
    if first_id is not None and second_id is not None:
        # A provider ID is the strongest signal: equal IDs win even if URLs vary.
        return first_id != second_id

    first_urls = _source_url_keys(first)
    second_urls = _source_url_keys(second)
    return bool(first_urls and second_urls and first_urls.isdisjoint(second_urls))


def _entry_matches(entry: JobEntry) -> list[dict[str, object]]:
    matches = entry.get("matches")
    if isinstance(matches, list):
        return [match for match in matches if isinstance(match, dict)]

    metadata = entry.get("metadata")
    return [metadata] if isinstance(metadata, dict) else []


def _add_matches(target: JobEntry, incoming: JobEntry) -> None:
    existing = _entry_matches(target)
    for match in _entry_matches(incoming):
        if match not in existing:
            existing.append(dict(match))
    target["matches"] = existing


def _apply_option_key(option: object) -> tuple[str, str] | None:
    if not isinstance(option, dict):
        return None
    link = _normalized_url(option.get("apply_link"))
    if link is None:
        return None
    publisher = _normalized_text(option.get("publisher")) or ""
    return publisher, link


def _add_apply_options(
    target_job: dict[str, object], incoming_job: dict[str, object]
) -> None:
    incoming_options = incoming_job.get("apply_options")
    if not isinstance(incoming_options, list):
        return

    target_options = target_job.get("apply_options")
    options = (
        [dict(option) if isinstance(option, dict) else option for option in target_options]
        if isinstance(target_options, list)
        else []
    )
    seen_keys = {
        key for option in options if (key := _apply_option_key(option)) is not None
    }

    for option in incoming_options:
        key = _apply_option_key(option)
        if key is not None:
            if key in seen_keys:
                continue
            seen_keys.add(key)
        elif option in options:
            continue

        options.append(dict(option) if isinstance(option, dict) else option)

    target_job["apply_options"] = options


def deduplicate_jobs(
    jobs: list[JobEntry],
) -> tuple[list[JobEntry], list[JobEntry]]:
    """Return unique job entries and entries folded into an earlier match.

    Identity precedence is provider ID, then a publisher-specific source URL.
    Company/title/location similarities do not merge postings. The first
    occurrence supplies the job fields; query metadata and apply options from
    duplicate observations are combined.
    """
    unique_jobs: list[JobEntry] = []
    duplicates: list[JobEntry] = []
    identity_to_index: dict[IdentityKey, int] = {}

    for entry in jobs:
        source_job = entry.get("job")
        job = source_job if isinstance(source_job, dict) else None
        keys = _identity_keys(job) if job is not None else []

        matched_index: int | None = None
        matched_by: str | None = None
        for key_type, key_value in keys:
            existing_index = identity_to_index.get((key_type, key_value))
            if existing_index is not None:
                retained_job = unique_jobs[existing_index].get("job")
                if (
                    job is not None
                    and isinstance(retained_job, dict)
                    and _has_conflicting_strong_identity(job, retained_job)
                ):
                    continue
                matched_index = existing_index
                matched_by = key_type
                break

        if matched_index is None:
            retained = dict(entry)
            if isinstance(source_job, dict):
                retained_job = dict(source_job)
                apply_options = source_job.get("apply_options")
                if isinstance(apply_options, list):
                    retained_job["apply_options"] = [
                        dict(option) if isinstance(option, dict) else option
                        for option in apply_options
                    ]
                retained["job"] = retained_job
            retained["matches"] = [dict(match) for match in _entry_matches(entry)]
            matched_index = len(unique_jobs)
            unique_jobs.append(retained)
        else:
            target = unique_jobs[matched_index]
            _add_matches(target, entry)
            retained_job = target.get("job")
            if isinstance(retained_job, dict) and isinstance(source_job, dict):
                _add_apply_options(retained_job, source_job)
            duplicates.append(
                {
                    **entry,
                    "duplicate_of": matched_index,
                    "dedupe_reason": matched_by,
                }
            )

        for key in keys:
            identity_to_index.setdefault(key, matched_index)

    return unique_jobs, duplicates
