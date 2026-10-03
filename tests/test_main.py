from src.config.settings import load_settings
from src.main import main
from src.storage.raw_storage import save_raw_result


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
                    "response": {"data": [{"job_title": query}]},
                },
                output_dir=tmp_path,
                run_id=run_id,
                query_number=query_number,
            )

    def fail_if_extraction_runs(*args, **kwargs):
        raise AssertionError("Replay mode must not call the JSearch extractor")

    monkeypatch.setattr("src.main.extract_jobs", fail_if_extraction_runs)

    results = main(replay_run_id=run_id, raw_output_dir=tmp_path)

    expected_query_count = sum(
        len(career.queries) for career in settings.careers.values()
    )
    assert len(results) == expected_query_count
    assert [result["query_number"] for result in results] == list(
        range(1, expected_query_count + 1)
    )
    assert results[0]["run_id"] == run_id
    assert "Validation completed: valid_jobs=0, invalid_jobs=6" in caplog.text
