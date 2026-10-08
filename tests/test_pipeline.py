from datetime import date

import pytest

from src.pipeline import run_pipeline


def test_replay_runs_stages_in_order_with_same_run_id(monkeypatch):
    calls = []

    def process_jobs(**kwargs):
        calls.append(("process", kwargs))
        return [{"extraction_status": "completed"}]

    def load_jobs(run_id):
        calls.append(("load", run_id))
        return {"postings_loaded": 1}

    def aggregate(start, end, *, date_basis):
        calls.append(("aggregate", (start, end, date_basis)))
        return {"skill_stats": 2}

    monkeypatch.setattr("src.pipeline.process_jobs", process_jobs)
    monkeypatch.setattr("src.pipeline.load_job_skills_from_run", load_jobs)
    monkeypatch.setattr("src.pipeline.refresh_career_skill_stats", aggregate)
    start, end = date(2026, 9, 1), date(2026, 9, 30)

    result = run_pipeline(
        replay_run_id="saved-run", start_date=start, end_date=end, skill_limit=1
    )

    assert [stage for stage, _ in calls] == ["process", "load", "aggregate"]
    assert calls[0][1]["replay_run_id"] == "saved-run"
    assert calls[0][1]["replay_query_count"] is None
    assert calls[0][1]["new_run_id"] is None
    assert calls[0][1]["extract_skills"] is True
    assert calls[0][1]["skill_limit"] == 1
    assert calls[1][1] == "saved-run"
    assert calls[2][1] == (start, end, "posted_at")
    assert result == {
        "run_id": "saved-run",
        "processed_jobs": 1,
        "loaded": {"postings_loaded": 1},
        "aggregation": {"skill_stats": 2},
    }


def test_incomplete_extraction_stops_before_database_stages(monkeypatch):
    monkeypatch.setattr(
        "src.pipeline.process_jobs",
        lambda **_kwargs: [{"extraction_status": "failed"}],
    )
    monkeypatch.setattr(
        "src.pipeline.load_job_skills_from_run",
        lambda _run_id: pytest.fail("must not load an incomplete run"),
    )

    with pytest.raises(RuntimeError, match="resume the same run"):
        run_pipeline(
            replay_run_id="saved-run",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )


def test_live_run_passes_generated_id_to_processing(monkeypatch):
    captured = {}

    def process_jobs(**kwargs):
        captured.update(kwargs)
        return [{"extraction_status": "completed"}]

    monkeypatch.setattr("src.pipeline.process_jobs", process_jobs)
    monkeypatch.setattr("src.pipeline.load_job_skills_from_run", lambda _id: {})
    monkeypatch.setattr(
        "src.pipeline.refresh_career_skill_stats", lambda *_args, **_kwargs: {}
    )

    result = run_pipeline(
        live=True, start_date=date(2026, 9, 1), end_date=date(2026, 9, 30)
    )

    assert result["run_id"].endswith("Z")
    assert captured["new_run_id"] == result["run_id"]
    assert captured["replay_run_id"] is None


def test_invalid_window_stops_before_processing(monkeypatch):
    monkeypatch.setattr(
        "src.pipeline.process_jobs", lambda **_kwargs: pytest.fail("must not process")
    )
    with pytest.raises(ValueError, match="start_date"):
        run_pipeline(
            live=True, start_date=date(2026, 10, 1), end_date=date(2026, 9, 30)
        )


def test_first_seen_date_basis_is_passed_to_aggregation(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "src.pipeline.process_jobs",
        lambda **_kwargs: [{"extraction_status": "completed"}],
    )
    monkeypatch.setattr("src.pipeline.load_job_skills_from_run", lambda _id: {})

    def aggregate(_start, _end, *, date_basis):
        captured["date_basis"] = date_basis
        return {}

    monkeypatch.setattr("src.pipeline.refresh_career_skill_stats", aggregate)

    run_pipeline(
        replay_run_id="saved-run",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        date_basis="first_seen_at",
    )

    assert captured["date_basis"] == "first_seen_at"


def test_replay_query_count_is_forwarded_to_processing(monkeypatch):
    captured = {}

    def process_jobs(**kwargs):
        captured.update(kwargs)
        return [{"extraction_status": "completed"}]

    monkeypatch.setattr("src.pipeline.process_jobs", process_jobs)
    monkeypatch.setattr("src.pipeline.load_job_skills_from_run", lambda _id: {})
    monkeypatch.setattr(
        "src.pipeline.refresh_career_skill_stats", lambda *_args, **_kwargs: {}
    )

    run_pipeline(
        replay_run_id="older-run",
        replay_query_count=6,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    assert captured["replay_query_count"] == 6
