from dataclasses import replace
from datetime import datetime, timezone

from src.config.settings import load_settings
from src.transform.job_cleaner import clean_jobs
from src.validation.job_validator import validate_jobs


def _valid_job(**overrides: object) -> dict[str, object]:
    job: dict[str, object] = {
        "job_id": "provider-001",
        "job_title": "  Data   Engineer  ",
        "job_description": (
            "<p>Build&nbsp;and maintain data pipelines.</p>"
            "<ul><li>Use Python</li><li>Work with SQL</li></ul>"
            "<p>Collaborate with the engineering team.</p>"
        ),
        "job_country": "Thailand",
        "job_location": "  Bangkok   Thailand ",
        "job_posted_at_datetime_utc": "2026-10-01T12:00:00Z",
    }
    job.update(overrides)
    return job


def test_clean_jobs_cleans_text_and_keeps_metadata_and_source_unchanged() -> None:
    settings = load_settings()
    settings = replace(
        settings,
        validation=replace(settings.validation, minimum_description_length=20),
    )
    source_job = _valid_job()
    entry = {
        "job": source_job,
        "metadata": {
            "run_id": "run-001",
            "query": "Data Engineer",
            "collected_at": "2026-10-03T12:00:00+00:00",
        },
    }

    cleaned_jobs, rejected_jobs = clean_jobs([entry], settings)

    cleaned_job = cleaned_jobs[0]["job"]
    assert cleaned_job["job_title"] == "Data Engineer"
    assert cleaned_job["job_description"] == (
        "Build and maintain data pipelines.\n\n"
        "Use Python\n"
        "Work with SQL\n\n"
        "Collaborate with the engineering team."
    )
    assert cleaned_job["job_country"] == "TH"
    assert cleaned_job["job_location"] == "Bangkok Thailand"
    assert cleaned_job["posted_at"] == datetime(
        2026, 10, 1, 12, tzinfo=timezone.utc
    )
    assert cleaned_job["posted_at_is_estimated"] is False
    assert cleaned_job["posted_at_status"] == "exact"
    assert cleaned_jobs[0]["metadata"] == entry["metadata"]
    assert source_job["job_title"] == "  Data   Engineer  "
    assert source_job["job_description"].startswith("<p>")
    assert rejected_jobs == []


def test_relative_posted_text_becomes_estimated_datetime() -> None:
    settings = load_settings()
    settings = replace(
        settings,
        validation=replace(settings.validation, minimum_description_length=20),
    )
    collected_at = "2026-10-03T12:00:00+00:00"
    raw_results = [
        {
            "run_id": "run-relative",
            "collected_at": collected_at,
            "response": {
                "data": [
                    _valid_job(
                        job_posted_at_datetime_utc=None,
                        job_posted_at="10 วันที่ผ่านมา",
                    )
                ]
            },
        }
    ]

    valid_jobs, invalid_jobs = validate_jobs(raw_results, settings)
    cleaned_jobs, rejected_jobs = clean_jobs(valid_jobs, settings)

    assert invalid_jobs == []
    assert rejected_jobs == []
    assert cleaned_jobs[0]["job"]["posted_at"] == datetime(
        2026, 9, 23, 12, tzinfo=timezone.utc
    )
    assert cleaned_jobs[0]["job"]["posted_at_is_estimated"] is True
    assert cleaned_jobs[0]["job"]["posted_at_status"] == "estimated"
    assert cleaned_jobs[0]["job"]["job_posted_at"] == "10 วันที่ผ่านมา"


def test_clean_jobs_normalizes_country_from_explicit_location_marker() -> None:
    settings = load_settings()
    settings = replace(
        settings,
        validation=replace(settings.validation, minimum_description_length=20),
    )
    entry = {
        "job": _valid_job(
            job_country="",
            job_country_code=None,
            job_location="ประเทศไทย • ผ่าน LinkedIn",
        ),
        "metadata": {"collected_at": "2026-10-03T12:00:00+00:00"},
    }

    cleaned_jobs, rejected_jobs = clean_jobs([entry], settings)

    assert cleaned_jobs[0]["job"]["job_country"] == "TH"
    assert rejected_jobs == []


def test_clean_jobs_rejects_description_that_is_too_short_after_html_removal() -> None:
    settings = load_settings()
    settings = replace(
        settings,
        validation=replace(settings.validation, minimum_description_length=50),
    )
    entry = {
        "job": _valid_job(job_description=f"<p>{'Useful text. ' * 3}</p>"),
        "metadata": {"query": "Data Engineer"},
    }

    cleaned_jobs, rejected_jobs = clean_jobs([entry], settings)

    assert cleaned_jobs == []
    assert rejected_jobs[0]["errors"] == [
        "job description is shorter than 50 characters after cleaning"
    ]


def test_relative_posting_older_than_configured_window_fails_validation() -> None:
    settings = load_settings()
    raw_results = [
        {
            "collected_at": "2026-10-03T12:00:00+00:00",
            "response": {
                "data": [
                    _valid_job(
                        job_posted_at_datetime_utc=None,
                        job_posted_at=f"{settings.validation.time_window_days + 1} days ago",
                    )
                ]
            },
        }
    ]

    valid_jobs, invalid_jobs = validate_jobs(raw_results, settings)

    assert valid_jobs == []
    assert invalid_jobs[0]["errors"] == [
        f"posted date is older than {settings.validation.time_window_days} days"
    ]


def test_job_without_posted_date_is_retained_and_marked_unknown() -> None:
    settings = load_settings()
    raw_results = [
        {
            "collected_at": "2026-10-03T12:00:00+00:00",
            "response": {
                "data": [
                    _valid_job(
                        job_posted_at_datetime_utc=None,
                        job_posted_at_timestamp=None,
                        job_posted_at=None,
                    )
                ]
            },
        }
    ]

    valid_jobs, invalid_jobs = validate_jobs(raw_results, settings)
    cleaned_jobs, rejected_jobs = clean_jobs(valid_jobs, settings)

    assert invalid_jobs == []
    assert rejected_jobs == []
    assert len(cleaned_jobs) == 1
    assert cleaned_jobs[0]["job"]["posted_at"] is None
    assert cleaned_jobs[0]["job"]["posted_at_is_estimated"] is False
    assert cleaned_jobs[0]["job"]["posted_at_status"] == "unknown"


def test_relative_hour_posted_date_is_estimated() -> None:
    settings = load_settings()
    collected_at = "2026-10-03T12:00:00+00:00"
    raw_results = [
        {
            "collected_at": collected_at,
            "response": {
                "data": [
                    _valid_job(
                        job_posted_at_datetime_utc=None,
                        job_posted_at_timestamp=None,
                        job_posted_at="10 ชั่วโมงที่ผ่านมา",
                    )
                ]
            },
        }
    ]

    valid_jobs, invalid_jobs = validate_jobs(raw_results, settings)
    cleaned_jobs, rejected_jobs = clean_jobs(valid_jobs, settings)

    assert invalid_jobs == []
    assert rejected_jobs == []
    assert cleaned_jobs[0]["job"]["posted_at"] == datetime(
        2026, 10, 3, 2, tzinfo=timezone.utc
    )
    assert cleaned_jobs[0]["job"]["posted_at_is_estimated"] is True
    assert cleaned_jobs[0]["job"]["posted_at_status"] == "estimated"
