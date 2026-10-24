"""Scheduled orchestration contracts; all service boundaries are replaced."""

from datetime import date, datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sys

import pytest

from src.market.config.settings import load_settings
from src.market import scheduled_pipeline as runner
from src.market.run_artifacts import RunArtifactStore


@pytest.fixture
def config(monkeypatch):
    settings = load_settings()
    monkeypatch.setattr(runner, "load_settings", lambda: settings)
    for name, value in {
        "RAW_S3_BUCKET": "unit-test-bucket", "RAW_S3_PREFIX": "raw/jsearch",
        "AWS_DEFAULT_REGION": "us-east-1", "DB_HOST": "test-database",
        "DB_PORT": "5432", "DB_NAME": "test", "DB_USER": "test",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(runner, "_preflight", lambda: None)
    class MemoryS3:
        objects = {}

        def put_object(self, *, Bucket, Key, Body, ContentType):
            self.objects[(Bucket, Key)] = Body

        def list_objects_v2(self, *, Bucket, Prefix, MaxKeys):
            return {"Contents": [{"Key": key} for bucket, key in self.objects
                                 if bucket == Bucket and key.startswith(Prefix)][:MaxKeys]}

        def get_object(self, *, Bucket, Key):
            return {"Body": BytesIO(self.objects[(Bucket, Key)])}

    client = MemoryS3()
    monkeypatch.setattr(runner, "RunArtifactStore", lambda bucket, run_id: RunArtifactStore(bucket, run_id, client=client))
    return settings


def successful_pipeline(**options):
    for stage in ("ingestion_and_skill_extraction", "database_load", "aggregation"):
        options["progress"](stage)
    return {"run_id": options["new_run_id"], "processed_jobs": 1,
            "loaded": {"postings_loaded": 1, "skills_loaded": 2}, "aggregation": {"skill_stats": 2}}


def test_plan_uses_inclusive_utc_window_without_creating_files(config, monkeypatch, tmp_path):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 24, 1, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(runner, "datetime", Clock)
    destination = tmp_path / "not-created"
    plan = runner.build_plan(data_dir=destination, window_days=30)
    assert plan["start_date"] == "2026-09-25"
    assert plan["end_date"] == "2026-10-24"
    assert plan["date_basis"] == "first_seen_at"
    assert plan["raw_storage"] == "s3"
    assert not destination.exists()


def test_s3_requires_bucket_and_local_is_explicit(config, monkeypatch, tmp_path):
    monkeypatch.delenv("RAW_S3_BUCKET")
    with pytest.raises(ValueError, match="RAW_S3_BUCKET"):
        runner.build_plan(data_dir=tmp_path)
    assert runner.build_plan(data_dir=tmp_path, raw_storage="local")["s3_bucket"] is None


@pytest.mark.parametrize("options", [
    {"start_date": date(2026, 10, 1)}, {"window_days": 0},
    {"skill_request_interval": float("nan")}, {"skill_request_interval": -1},
    {"start_date": date(2026, 10, 2), "end_date": date(2026, 10, 1)},
    {"start_date": date(2026, 10, 1), "end_date": date(2026, 10, 2), "window_days": 2},
])
def test_invalid_options_fail_before_side_effects(config, tmp_path, options):
    with pytest.raises(ValueError):
        runner.build_plan(data_dir=tmp_path / "absent", **options)
    assert not (tmp_path / "absent").exists()


def test_worker_lock_blocks_overlap_then_releases(tmp_path):
    path = tmp_path / "worker.lock"
    with runner.worker_lock(path):
        with pytest.raises(runner.WorkerBusyError):
            with runner.worker_lock(path):
                pytest.fail("overlapping worker acquired the lock")
    with runner.worker_lock(path):
        assert path.exists()


def test_completed_run_persists_summary_and_does_not_repeat(config, monkeypatch, tmp_path):
    calls = []

    def pipeline(**options):
        calls.append(options)
        return successful_pipeline(**options)

    monkeypatch.setattr(runner, "run_pipeline", pipeline)
    result = runner.execute_run(data_dir=tmp_path)
    state_path = Path(result["state_path"])
    state = json.loads(state_path.read_text())
    assert state["status"] == "completed"
    assert state["stage"] == "finished"
    assert state["attempts"][0]["status"] == "completed"
    assert state_path.with_name("summary.json").exists()
    assert Path(result["log_path"]).exists()
    repeated = runner.execute_run(data_dir=tmp_path, resume_run_id=result["run_id"])
    assert repeated["already_completed"]
    assert len(calls) == 1
    assert calls[0]["raw_output_dir"] == tmp_path / "raw"
    assert calls[0]["skill_output_dir"] == tmp_path / "processed" / "skill_extraction"


def test_failure_resume_preserves_window_and_records_both_attempts(config, monkeypatch, tmp_path):
    calls = []

    def pipeline(**options):
        calls.append(options)
        if len(calls) == 1:
            options["progress"]("aggregation")
            raise RuntimeError("simulated interruption after DB loading")
        return successful_pipeline(**options)

    monkeypatch.setattr(runner, "run_pipeline", pipeline)
    with pytest.raises(RuntimeError):
        runner.execute_run(data_dir=tmp_path, window_days=30)
    state_path = next(tmp_path.rglob("state.json"))
    failed = json.loads(state_path.read_text())
    assert failed["status"] == "failed"
    assert failed["stage"] == "aggregation"
    result = runner.execute_run(data_dir=tmp_path, resume_run_id=failed["plan"]["run_id"])
    assert calls[1]["resume_raw"] is True
    assert calls[0]["new_run_id"] == calls[1]["new_run_id"]
    assert calls[0]["start_date"] == calls[1]["start_date"]
    assert calls[0]["end_date"] == calls[1]["end_date"]
    completed = json.loads(state_path.read_text())
    assert [item["status"] for item in completed["attempts"]] == ["failed", "completed"]
    assert "error_type" not in completed
    assert result["status"] == "completed"


def test_resume_refuses_changed_config_and_window_options(config, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "run_pipeline", successful_pipeline)
    result = runner.execute_run(data_dir=tmp_path)
    with pytest.raises(ValueError, match="saved storage/window"):
        runner.build_plan(data_dir=tmp_path, resume_run_id=result["run_id"], window_days=2)
    monkeypatch.setenv("DB_HOST", "another-database")
    with pytest.raises(ValueError, match="configuration changed"):
        runner.build_plan(data_dir=tmp_path, resume_run_id=result["run_id"])


def test_local_mode_suppresses_configured_s3_then_restores_environment(config, monkeypatch, tmp_path):
    def pipeline(**options):
        import os
        assert os.environ["RAW_S3_BUCKET"] == ""
        return successful_pipeline(**options)

    monkeypatch.setattr(runner, "run_pipeline", pipeline)
    runner.execute_run(data_dir=tmp_path, raw_storage="local")
    import os
    assert os.environ["RAW_S3_BUCKET"] == "unit-test-bucket"


def test_zero_processed_jobs_finishes_no_jobs(config, monkeypatch, tmp_path):
    def pipeline(**options):
        return {**successful_pipeline(**options), "processed_jobs": 0}

    monkeypatch.setattr(runner, "run_pipeline", pipeline)
    assert runner.execute_run(data_dir=tmp_path)["status"] == "no_jobs"


def test_empty_skill_result_is_visible_in_summary(config, monkeypatch, tmp_path):
    def pipeline(**options):
        result = successful_pipeline(**options)
        result["loaded"]["skills_loaded"] = 0
        return result

    monkeypatch.setattr(runner, "run_pipeline", pipeline)
    result = runner.execute_run(data_dir=tmp_path)
    assert result["status"] == "completed"
    assert any("no verified catalog-matched skills" in warning for warning in result["warnings"])


def test_failure_restores_storage_environment(config, monkeypatch, tmp_path):
    def pipeline(**_options):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(runner, "run_pipeline", pipeline)
    with pytest.raises(RuntimeError):
        runner.execute_run(data_dir=tmp_path, raw_storage="local")
    import os
    assert os.environ["RAW_S3_BUCKET"] == "unit-test-bucket"


def test_missing_journal_and_checkpoint_restore_from_s3(config, monkeypatch, tmp_path):
    calls = []

    def pipeline(**options):
        calls.append(options)
        checkpoint = options["skill_output_dir"] / f"{options['new_run_id']}.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps({"run_id": options["new_run_id"], "jobs": [{"id": 1}]}))
        options["artifact_saved"]("skill_checkpoint.json", checkpoint)
        if len(calls) == 1:
            raise RuntimeError("worker interrupted")
        assert json.loads(checkpoint.read_text())["jobs"] == [{"id": 1}]
        return successful_pipeline(**options)

    monkeypatch.setattr(runner, "run_pipeline", pipeline)
    with pytest.raises(RuntimeError):
        runner.execute_run(data_dir=tmp_path)
    state_path = next(tmp_path.rglob("state.json"))
    run_id = state_path.parent.name
    checkpoint_path = tmp_path / "processed" / "skill_extraction" / f"{run_id}.json"
    state_path.unlink()
    checkpoint_path.unlink()
    result = runner.execute_run(data_dir=tmp_path, resume_run_id=run_id)
    assert result["status"] == "completed"
    assert result["run_id"] == run_id
    assert len(calls) == 2


def test_invalid_restored_checkpoint_does_not_replace_local_file(tmp_path):
    class Client:
        def list_objects_v2(self, **_):
            return {"Contents": [{"Key": "market/pipeline-runs/run-1/skill_checkpoint.json"}]}

        def get_object(self, **_):
            return {"Body": BytesIO(b'{"run_id":"other","jobs":[]}')}

    store = RunArtifactStore("bucket", "run-1", client=Client())
    path = tmp_path / "checkpoint.json"
    with pytest.raises(ValueError, match="another run"):
        store.restore_missing("skill_checkpoint.json", path)
    assert not path.exists()


def test_dry_run_cli_does_not_execute_or_create_files(config, monkeypatch, tmp_path, capsys):
    from scripts.market import run_scheduled_pipeline as cli

    monkeypatch.setattr(cli, "execute_run", lambda **_: pytest.fail("dry-run executed the pipeline"))
    destination = tmp_path / "unused"
    monkeypatch.setattr(sys, "argv", ["runner", "--live", "--dry-run", "--data-dir", str(destination)])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
    assert not destination.exists()


def test_empty_pipeline_skips_loader_and_still_aggregates(monkeypatch):
    from src.market import pipeline

    monkeypatch.setattr(pipeline, "process_jobs", lambda **_: [])
    monkeypatch.setattr(pipeline, "load_job_skills_from_run", lambda *_: pytest.fail("empty loader was called"))
    monkeypatch.setattr(pipeline, "refresh_career_skill_stats", lambda *_args, **_kwargs: {"eligible_jobs": 3})
    result = pipeline.run_pipeline(live=True, start_date=date(2026, 10, 1), end_date=date(2026, 10, 24))
    assert result["loaded"]["postings_loaded"] == 0
    assert result["aggregation"]["eligible_jobs"] == 3
