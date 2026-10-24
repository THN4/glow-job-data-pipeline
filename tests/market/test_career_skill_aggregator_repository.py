from contextlib import nullcontext
from datetime import date

import pytest

from src.market.aggregation.career_skill_aggregator import refresh_career_skill_stats


class _FakeConnection:
    def __init__(self):
        self.statements = []

    def transaction(self):
        return nullcontext()

    def execute(self, statement, params):
        self.statements.append((statement, params))
        if "SELECT job_id, career_profile_id" in statement:
            return self
        return self

    def fetchall(self):
        return []


def test_first_seen_basis_selects_jobs_by_collection_time(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(
        "src.market.aggregation.career_skill_aggregator.get_database_connection",
        lambda: nullcontext(connection),
    )

    result = refresh_career_skill_stats(
        date(2026, 10, 1), date(2026, 10, 8), date_basis="first_seen_at"
    )

    select_sql, _ = connection.statements[0]
    delete_sql, delete_params = connection.statements[1]
    assert "first_seen_at >= %s AND first_seen_at < %s" in select_sql
    assert "analysis_date_basis = %s" in delete_sql
    assert delete_params == (date(2026, 10, 1), date(2026, 10, 8), "first_seen_at")
    assert result == {"eligible_jobs": 0, "career_profiles": 0, "skill_stats": 0}


def test_invalid_date_basis_fails_before_database_access(monkeypatch):
    monkeypatch.setattr(
        "src.market.aggregation.career_skill_aggregator.get_database_connection",
        lambda: pytest.fail("database should not be opened for an invalid basis"),
    )

    with pytest.raises(ValueError, match="date_basis"):
        refresh_career_skill_stats(
            date(2026, 10, 1), date(2026, 10, 8), date_basis="collected_at"
        )
