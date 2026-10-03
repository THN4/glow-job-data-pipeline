"""Parse JSearch posting dates into timezone-aware UTC datetimes."""

import re
from datetime import datetime, timedelta, timezone


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None

    if abs(value) >= 1_000_000_000_000:
        value /= 1000
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_relative_date(value: object, reference_time: datetime) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip().casefold()

    if text in {"today", "just posted", "วันนี้"}:
        return reference_time
    if text in {"yesterday", "เมื่อวาน", "เมื่อวานนี้"}:
        return reference_time - timedelta(days=1)

    english_match = re.fullmatch(
        r"(\d+)\s+(day|week|month|year)s?\s+ago", text
    )
    thai_match = re.fullmatch(r"(\d+)\s*(วัน|สัปดาห์|เดือน|ปี)ที่ผ่านมา", text)
    match = english_match or thai_match
    if match is None:
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    days_per_unit = {
        "day": 1,
        "week": 7,
        "month": 30,
        "year": 365,
        "วัน": 1,
        "สัปดาห์": 7,
        "เดือน": 30,
        "ปี": 365,
    }
    return reference_time - timedelta(days=amount * days_per_unit[unit])


def parse_job_posted_at(
    job: dict[str, object],
    *,
    collected_at: object = None,
    fallback_time: datetime | None = None,
) -> tuple[datetime | None, bool]:
    """Return (UTC posting time, estimated) using exact fields before relative text."""
    reference_time = _as_datetime(collected_at)
    if reference_time is None:
        reference_time = fallback_time or datetime.now(timezone.utc)
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        reference_time = reference_time.astimezone(timezone.utc)

    exact_datetime = _as_datetime(job.get("job_posted_at_datetime_utc"))
    if exact_datetime is not None:
        return exact_datetime, False

    timestamp = _parse_timestamp(job.get("job_posted_at_timestamp"))
    if timestamp is not None:
        return timestamp, False

    relative_datetime = _parse_relative_date(job.get("job_posted_at"), reference_time)
    if relative_datetime is not None:
        return relative_datetime, True

    return None, False
