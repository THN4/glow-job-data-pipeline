import pytest
from requests import HTTPError

from src.market.ingestion.extract_single_query import extract_single_query
from src.market.config.settings import JSearchSettings, SearchSettings


def test_extract_single_query_success(requests_mock, monkeypatch):
    fake_response = {
        "status": "OK",
        "data": {
            "jobs": [
                {"jod_id": "1001", "job_title": "Data Engineer"},
                {"jod_id": "1002", "job_title": "Data Science"},
            ]
        },
    }

    search_settings = SearchSettings(
        country="TH",
        max_pages=2,
        date_posted="week",
    )
    jsearch_settings = JSearchSettings(
        method="GET",
        url="https://example.test/search-v2",
        host="example.test",
        content_type="application/json",
        api_key_env="JSEARCH_API_KEY",
    )

    monkeypatch.setenv(jsearch_settings.api_key_env, "test-api-key")
    requests_mock.get(jsearch_settings.url, json=fake_response, status_code=200)

    response_data = extract_single_query(
        query="Data Engineer",
        search_settings=search_settings,
        jsearch_settings=jsearch_settings,
    )

    assert response_data == fake_response
    assert requests_mock.last_request.qs["query"] == ["Data Engineer"]
    assert requests_mock.last_request.qs["country"] == ["TH"]
    assert requests_mock.last_request.qs["num_pages"] == ["2"]
    assert requests_mock.last_request.qs["date_posted"] == ["week"]
    assert requests_mock.last_request.headers["X-RapidAPI-Key"] == "test-api-key"

def test_extract_single_query_failure(requests_mock, monkeypatch):
    search_settings = SearchSettings(country="TH", max_pages=1, date_posted="all")
    jsearch_settings = JSearchSettings(
        method="GET",
        url="https://example.test/search-v2",
        host="example.test",
        content_type="application/json",
        api_key_env="JSEARCH_API_KEY",
    )
    monkeypatch.setenv(jsearch_settings.api_key_env, "test-api-key")
    requests_mock.get(jsearch_settings.url, status_code=500)

    with pytest.raises(HTTPError):
        extract_single_query(
            query="Data Engineer",
            search_settings=search_settings,
            jsearch_settings=jsearch_settings,
        )

    assert requests_mock.call_count == 1
    

def test_extract_single_query_rate_limit(requests_mock, monkeypatch):
    search_settings = SearchSettings(country="TH", max_pages=1, date_posted="all")
    jsearch_settings = JSearchSettings(
        method="GET",
        url="https://example.test/search-v2",
        host="example.test",
        content_type="application/json",
        api_key_env="JSEARCH_API_KEY",
    )
    monkeypatch.setenv(jsearch_settings.api_key_env, "test-api-key")
    requests_mock.get(jsearch_settings.url, status_code=429, headers={"Retry-After": "60"})

    with pytest.raises(HTTPError, match="JSearch rate limit exceeded"):
        extract_single_query(
            query="Data Engineer",
            search_settings=search_settings,
            jsearch_settings=jsearch_settings,
        )

    assert requests_mock.call_count == 1
