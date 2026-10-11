from decimal import Decimal

import pytest

from datetime import datetime, timezone

from src.market.skill_extraction.job_skill_loader import (
    _first_seen_at,
    _posted_at,
    _posted_at_status,
    importance_weight,
)


def test_importance_weight_follows_specified_requirement_and_level_rule():
    assert importance_weight("required", "advanced") == Decimal("0.970")
    assert importance_weight("preferred", "beginner") == Decimal("0.570")
    assert importance_weight("required", "unknown") == Decimal("0.880")


def test_posted_at_rejects_timestamp_without_timezone():
    with pytest.raises(ValueError, match="must include a timezone"):
        _posted_at("2026-09-27T10:00:00")


def test_posted_at_status_supports_current_and_older_checkpoints():
    assert _posted_at_status({"posted_at": None}) == "unknown"
    assert _posted_at_status({"posted_at": "2026-09-27T10:00:00+00:00"}) == "exact"
    assert _posted_at_status(
        {
            "posted_at": "2026-09-27T10:00:00+00:00",
            "posted_at_is_estimated": True,
        }
    ) == "estimated"
    assert _posted_at_status({"posted_at_status": "unknown"}) == "unknown"


def test_first_seen_at_uses_earliest_matching_query_collection_time():
    entry = {
        "metadata": {"collected_at": "2026-10-08T10:02:00+00:00"},
        "matches": [
            {"collected_at": "2026-10-08T10:01:00+00:00"},
            {"collected_at": "2026-10-08T10:03:00+00:00"},
        ],
    }

    assert _first_seen_at(entry) == datetime(
        2026, 10, 8, 10, 1, tzinfo=timezone.utc
    )
