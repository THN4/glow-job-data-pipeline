from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.market.config.settings import load_settings
from src.market.ingestion.validation.job_validator import validate_jobs


def _job(**overrides: object) -> dict[str, object]:
    job: dict[str, object] = {
        "job_id": "jsearch-123",
        "job_title": "Data Engineer",
        "job_description": "Build and maintain data pipelines. " * 5,
        "job_country": "Thailand",
        "job_posted_at_datetime_utc": datetime.now(timezone.utc).isoformat(),
    }
    job.update(overrides)
    return job


def test_validate_jobs_keeps_valid_job_and_query_metadata() -> None:
    settings = load_settings()
    settings = replace(
        settings,
        validation=replace(settings.validation, minimum_description_length=50),
    )
    raw_results = [
        {
            "run_id": "run-001",
            "query_number": 1,
            "career_slug": "data_engineer",
            "query": "Data Engineer",
            "response": {"data": [_job()]},
        }
    ]

    valid_jobs, invalid_jobs = validate_jobs(raw_results, settings)

    assert len(valid_jobs) == 1
    assert valid_jobs[0]["job"] == raw_results[0]["response"]["data"][0]
    assert valid_jobs[0]["metadata"]["query"] == "Data Engineer"
    assert invalid_jobs == []


def test_validate_jobs_accepts_jsearch_data_object_with_jobs_list() -> None:
    settings = load_settings()
    job = _job()
    raw_results = [
        {
            "run_id": "run-001",
            "query_number": 1,
            "career_slug": "data_engineer",
            "query": "Data Engineer",
            "response": {
                "status": "OK",
                "data": {"jobs": [job], "cursor": "next-page-token"},
            },
        }
    ]

    valid_jobs, invalid_jobs = validate_jobs(raw_results, settings)

    assert len(valid_jobs) == 1
    assert valid_jobs[0]["job"] == job
    assert valid_jobs[0]["metadata"]["query_number"] == 1
    assert invalid_jobs == []


def test_validate_jobs_reports_reasons_for_invalid_job() -> None:
    settings = load_settings()
    settings = replace(
        settings,
        validation=replace(settings.validation, minimum_description_length=50),
    )
    invalid_job = _job(
        job_title="  ",
        job_description="too short",
        job_country="US",
        job_id=None,
        job_posted_at_datetime_utc=(
            datetime.now(timezone.utc)
            - timedelta(days=settings.validation.time_window_days + 1)
        ).isoformat(),
    )

    valid_jobs, invalid_jobs = validate_jobs(
        [{"query": "Data Engineer", "response": {"data": [invalid_job]}}],
        settings,
    )

    assert valid_jobs == []
    assert invalid_jobs[0]["errors"] == [
        "missing job title",
        "job description is shorter than 50 characters",
        "job country US is outside selected country TH",
        "missing stable job identifier",
        f"posted date is older than {settings.validation.time_window_days} days",
    ]


def test_validate_jobs_accepts_provider_id_fallback_and_unix_timestamp() -> None:
    settings = load_settings()
    job = _job(
        job_id=None,
        employer_name="Example Company",
        job_location="Bangkok",
        job_posted_at_datetime_utc=None,
        job_posted_at_timestamp=int(datetime.now(timezone.utc).timestamp()),
    )

    valid_jobs, invalid_jobs = validate_jobs(
        [{"response": {"data": [job]}}],
        settings,
    )

    assert len(valid_jobs) == 1
    assert invalid_jobs == []


def test_validate_jobs_infers_country_from_explicit_location_marker() -> None:
    settings = load_settings()
    job = _job(
        job_country="",
        job_country_code=None,
        job_location="ประเทศไทย • ผ่าน LinkedIn",
        job_posted_at_datetime_utc=None,
        job_posted_at="20 วันที่ผ่านมา",
    )

    valid_jobs, invalid_jobs = validate_jobs(
        [
            {
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "response": {"data": [job]},
            }
        ],
        settings,
    )

    assert len(valid_jobs) == 1
    assert invalid_jobs == []


def test_validate_jobs_does_not_infer_country_from_city_alone() -> None:
    settings = load_settings()
    job = _job(
        job_country="",
        job_country_code=None,
        job_location="กรุงเทพมหานคร",
        job_posted_at="3 วันที่ผ่านมา",
    )

    valid_jobs, invalid_jobs = validate_jobs(
        [{"response": {"data": [job]}}],
        settings,
    )

    assert valid_jobs == []
    assert invalid_jobs[0]["errors"] == ["missing job country"]


def test_validate_jobs_accepts_relative_posting_date_using_collection_time() -> None:
    settings = load_settings()
    collected_at = "2026-10-03T12:00:00+00:00"
    job = _job(
        job_posted_at_datetime_utc=None,
        job_posted_at="10 วันที่ผ่านมา",
    )

    valid_jobs, invalid_jobs = validate_jobs(
        [{"collected_at": collected_at, "response": {"data": [job]}}],
        settings,
    )

    assert len(valid_jobs) == 1
    assert invalid_jobs == []


def test_validate_jobs_rejects_unsupported_relative_posting_date() -> None:
    settings = load_settings()
    job = _job(
        job_posted_at_datetime_utc=None,
        job_posted_at="recently",
    )

    valid_jobs, invalid_jobs = validate_jobs(
        [{"response": {"data": [job]}}],
        settings,
    )

    assert valid_jobs == []
    assert invalid_jobs[0]["errors"] == ["invalid posted date"]


def test_validate_jobs_reports_malformed_response_and_job_records() -> None:
    settings = load_settings()
    query_results = [
        {"query": "missing data", "response": {}},
        {"query": "not an object", "response": {"data": ["bad record"]}},
    ]

    valid_jobs, invalid_jobs = validate_jobs(query_results, settings)

    assert valid_jobs == []
    assert [result["errors"] for result in invalid_jobs] == [
        ["response data is missing or is not a list"],
        ["job record is not an object"],
    ]
