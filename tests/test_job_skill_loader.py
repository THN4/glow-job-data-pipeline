from decimal import Decimal

import pytest

from src.load.job_skill_loader import _posted_at, importance_weight


def test_importance_weight_follows_specified_requirement_and_level_rule():
    assert importance_weight("required", "advanced") == Decimal("0.970")
    assert importance_weight("preferred", "beginner") == Decimal("0.570")
    assert importance_weight("required", "unknown") == Decimal("0.880")


def test_posted_at_rejects_timestamp_without_timezone():
    with pytest.raises(ValueError, match="must include a timezone"):
        _posted_at("2026-09-27T10:00:00")
