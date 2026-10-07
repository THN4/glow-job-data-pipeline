from datetime import datetime, timezone

import pytest

from src.storage.skill_result_storage import load_skill_results, save_skill_results


def test_skill_checkpoint_roundtrip_with_datetime(tmp_path):
    jobs = [
        {
            "job": {"job_id": "job-1", "posted_at": datetime(2026, 10, 7, tzinfo=timezone.utc)},
            "skills": [],
            "extraction_status": "completed",
        }
    ]
    save_skill_results(jobs, run_id="example-run", output_dir=tmp_path)

    loaded = load_skill_results(run_id="example-run", output_dir=tmp_path)
    assert loaded[0]["job"]["posted_at"] == "2026-10-07T00:00:00+00:00"
    assert loaded[0]["extraction_status"] == "completed"


def test_skill_checkpoint_rejects_unsafe_run_id(tmp_path):
    with pytest.raises(ValueError, match="run_id"):
        save_skill_results([], run_id="../outside", output_dir=tmp_path)
