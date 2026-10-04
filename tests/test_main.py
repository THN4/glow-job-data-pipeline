from datetime import datetime, timezone

from src.config.settings import load_settings
from src.main import main
from src.storage.raw_storage import load_raw_result, save_raw_result


def test_main_replays_raw_run_without_calling_api(monkeypatch, tmp_path, caplog):
    caplog.set_level("INFO")
    settings = load_settings()
    run_id = "test-replay-run"
    query_number = 0

    for career_slug, career in settings.careers.items():
        for query in career.queries:
            query_number += 1
            save_raw_result(
                result={
                    "career_slug": career_slug,
                    "career_name": career.career_name,
                    "query": query,
                    "response": {
                        "data": [
                            {
                                "job_id": f"job-{query_number}",
                                "job_title": f"  {query}  ",
                                "job_description": (
                                    "<p>Build and maintain data pipelines. "
                                    "Collaborate with engineering teams. </p>"
                                    * 3
                                ),
                                "job_country": "Thailand",
                                "job_posted_at_datetime_utc": datetime.now(
                                    timezone.utc
                                ).isoformat(),
                            }
                        ]
                    },
                },
                output_dir=tmp_path,
                run_id=run_id,
                query_number=query_number,
            )

    def fail_if_extraction_runs(*args, **kwargs):
        raise AssertionError("Replay mode must not call the JSearch extractor")

    monkeypatch.setattr("src.main.extract_jobs", fail_if_extraction_runs)

    cleaned_jobs = main(
        replay_run_id=run_id,
        raw_output_dir=tmp_path,
        company_review_output_dir=tmp_path / "company-review",
    )

    expected_query_count = sum(
        len(career.queries) for career in settings.careers.values()
    )
    assert len(cleaned_jobs) == expected_query_count
    assert cleaned_jobs[0]["metadata"]["run_id"] == run_id
    assert cleaned_jobs[0]["job"]["job_title"] == settings.careers[
        "data_engineer"
    ].queries[0]
    assert cleaned_jobs[0]["job"]["job_country"] == "TH"
    assert cleaned_jobs[0]["job"]["posted_at_is_estimated"] is False
    assert cleaned_jobs[0]["job"]["career_slug"] == "data_engineer"
    assert cleaned_jobs[0]["job"]["normalized_job_title"] == "Data Engineer"
    assert cleaned_jobs[0]["matches"] == [cleaned_jobs[0]["metadata"]]
    assert "Validation completed: valid_jobs=6, invalid_jobs=0" in caplog.text
    assert "Cleaning completed: cleaned_jobs=6, rejected_after_cleaning=0" in caplog.text
    assert "Deduplication completed: unique_jobs=6, duplicates_removed=0" in caplog.text

    raw_results = load_raw_result(
        output_dir=tmp_path,
        run_id=run_id,
        expected_query_count=expected_query_count,
    )
    assert raw_results[0]["response"]["data"][0]["job_title"].startswith("  ")


def test_main_deduplicates_across_queries_and_keeps_match_metadata(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level("INFO")
    settings = load_settings()
    run_id = "test-deduplicate-run"
    query_number = 0

    for career_slug, career in settings.careers.items():
        for query in career.queries:
            query_number += 1
            save_raw_result(
                result={
                    "career_slug": career_slug,
                    "career_name": career.career_name,
                    "query": query,
                    "response": {
                        "data": [
                            {
                                "job_id": "same-provider-job",
                                "job_title": "Data Engineer",
                                "employer_name": "Siam Commercial Ban",
                                "job_description": "Build reliable data pipelines. " * 5,
                                "job_country": "Thailand",
                                "job_posted_at_datetime_utc": datetime.now(
                                    timezone.utc
                                ).isoformat(),
                                "apply_options": [
                                    {
                                        "publisher": f"publisher-{query_number}",
                                        "apply_link": (
                                            "https://jobs.example/apply/"
                                            f"{query_number}"
                                        ),
                                        "is_direct": True,
                                    }
                                ],
                            }
                        ]
                    },
                },
                output_dir=tmp_path,
                run_id=run_id,
                query_number=query_number,
            )

    def fail_if_extraction_runs(*args, **kwargs):
        raise AssertionError("Replay mode must not call the JSearch extractor")

    monkeypatch.setattr("src.main.extract_jobs", fail_if_extraction_runs)

    review_output_dir = tmp_path / "company-review"
    unique_jobs = main(
        replay_run_id=run_id,
        raw_output_dir=tmp_path,
        company_review_output_dir=review_output_dir,
    )

    assert len(unique_jobs) == 1
    assert unique_jobs[0]["metadata"]["query_number"] == 1
    assert len(unique_jobs[0]["matches"]) == query_number
    assert [match["query_number"] for match in unique_jobs[0]["matches"]] == list(
        range(1, query_number + 1)
    )
    assert len(unique_jobs[0]["job"]["apply_options"]) == query_number
    assert unique_jobs[0]["job"]["company_normalization"]["match_method"] == (
        "candidate_review"
    )
    assert unique_jobs[0]["job"]["career_slug"] == "data_engineer"
    report_path = review_output_dir / f"{run_id}.csv"
    assert report_path.exists()
    assert "Siam Commercial Ban" in report_path.read_text(encoding="utf-8-sig")
    assert (
        f"Deduplication completed: unique_jobs=1, duplicates_removed={query_number - 1}"
        in caplog.text
    )
