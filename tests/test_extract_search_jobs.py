import pytest
from requests import HTTPError

from src.extract.extract_single_query import extract_search_jobs
from src.config.settings import JSearchSettings


def test_extract_search_jobs_success(requests_mock, monkeypatch):
    # 1. Arrange
    fake_response = {
        "status": "OK",
        "data": {
            "jobs": [
                {"jod_id": "1001", "job_title": "Data Engineer"},
                {"jod_id": "1002", "job_title": "Data Science"},
            ]
        },
    }

    # 2. Act
    settings = JSearchSettings(
        method="GET",
        url="https://example.test/search-v2",
        host="example.test",
        content_type="application/json",
        api_key_env="JSEARCH_API_KEY",
        num_pages=1,
        date_posted="all",
    )
    
    monkeypatch.setenv(settings.api_key_env, "test-api-key")
    requests_mock.get(settings.url, json=fake_response, status_code=200)

    response_data = extract_search_jobs(
        query="Data Engineer",
        country="TH",
        settings=settings,
    )

    # 3. Assert
    assert response_data == fake_response
    assert requests_mock.last_request.qs["query"] == ["Data Engineer"]
    assert requests_mock.last_request.qs["country"] == ["TH"]
    assert requests_mock.last_request.headers["X-RapidAPI-Key"] == "test-api-key"
    

def test_extract_search_jobs_failure(requests_mock, monkeypatch):
    settings = JSearchSettings(
        method="GET",
        url="https://example.test/search-v2",
        host="example.test",
        content_type="application/json",
        api_key_env="JSEARCH_API_KEY",
        num_pages=1,
        date_posted="all",
    )
    monkeypatch.setenv(settings.api_key_env, "test-api-key")
    requests_mock.get(settings.url, status_code=500)

    with pytest.raises(HTTPError):
        extract_search_jobs(
            query="Data Engineer",
            country="TH",
            settings=settings,
        )

    assert requests_mock.call_count == 1