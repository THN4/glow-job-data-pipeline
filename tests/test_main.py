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

    cleaned_jobs = main(replay_run_id=run_id, raw_output_dir=tmp_path)

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
    assert "Validation completed: valid_jobs=6, invalid_jobs=0" in caplog.text
    assert "Cleaning completed: cleaned_jobs=6, rejected_after_cleaning=0" in caplog.text

    raw_results = load_raw_result(
        output_dir=tmp_path,
        run_id=run_id,
        expected_query_count=expected_query_count,
    )
    assert raw_results[0]["response"]["data"][0]["job_title"].startswith("  ")
