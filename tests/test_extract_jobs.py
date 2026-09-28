import pytest
from requests import HTTPError

from src.config.settings import load_settings
from src.extract.extract_jobs import extract_jobs


def test_extract_jobs_calls_client_for_each_query(monkeypatch, tmp_path):
    settings = load_settings()
    calls = []

    def fake_search_jobs(query, country, settings):
        calls.append((query, country))
        return {"data": [{"query": query}]}

    monkeypatch.setattr(
        "src.extract.extract_jobs.extract_single_query",
        fake_search_jobs,
    )

    results = extract_jobs(
        settings,
        output_dir=tmp_path,
        run_id="test-run-001",
    )

    expected_query_count = sum(
        len(career.queries) for career in settings.careers.values()
    )

    saved_files = list(tmp_path.rglob("*.json"))

    assert len(saved_files) == expected_query_count
    assert len(calls) == expected_query_count
    assert len(results) == expected_query_count
    assert results[0]["career_slug"] == "data_engineer"
    assert results[0]["query"] == "Data Engineer"
    assert results[0]["response"] == {"data": [{"query": "Data Engineer"}]}


def test_extract_jobs_keeps_saved_results_when_query_fails(monkeypatch, tmp_path):
    settings = load_settings()
    calls = []

    def fake_search_jobs(query, country, settings):
        calls.append(query)

        if len(calls) == 3:
            raise HTTPError("JSearch rate limit exceeded")

        return {"data": [{"query": query}]}

    monkeypatch.setattr(
        "src.extract.extract_jobs.extract_single_query",
        fake_search_jobs,
    )

    with pytest.raises(HTTPError, match="JSearch rate limit exceeded"):
        extract_jobs(
            settings,
            output_dir=tmp_path,
            run_id="test-run-429",
        )

    saved_files = list(tmp_path.rglob("*.json"))

    assert len(calls) == 3
    assert len(saved_files) == 2
