from datetime import datetime, timezone

from src.shared.utils.job_dates import parse_job_posted_at


def test_parse_english_relative_hours_ago():
    collected_at = "2026-10-03T12:00:00+00:00"

    posted_at, estimated = parse_job_posted_at(
        {"job_posted_at": "10 hours ago"}, collected_at=collected_at
    )

    assert posted_at == datetime(2026, 10, 3, 2, tzinfo=timezone.utc)
    assert estimated is True


def test_parse_thai_relative_hours_ago():
    collected_at = "2026-10-03T12:00:00+00:00"

    posted_at, estimated = parse_job_posted_at(
        {"job_posted_at": "10 ชั่วโมงที่ผ่านมา"}, collected_at=collected_at
    )

    assert posted_at == datetime(2026, 10, 3, 2, tzinfo=timezone.utc)
    assert estimated is True
