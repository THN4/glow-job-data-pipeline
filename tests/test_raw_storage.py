import json
import pytest

from src.storage.raw_storage import load_raw_result, save_raw_result


def test_save_raw_result_writes_json_file(tmp_path):
    result = {
        "career_slug": "data_engineer",
        "career_name": "Data Engineer",
        "query": "Data Engineer",
        "response": {
            "data": [{"job_title": "Data Engineer"}],
        },
    }

    file_path = save_raw_result(
        result=result,
        output_dir=tmp_path,
        run_id="test-run-001",
        query_number=1,
    )

    assert file_path.exists()

    saved_data = json.loads(file_path.read_text(encoding="utf-8"))

    assert saved_data["run_id"] == "test-run-001"
    assert saved_data["query_number"] == 1
    assert saved_data["career_slug"] == "data_engineer"
    assert saved_data["career_name"] == "Data Engineer"
    assert saved_data["query"] == "Data Engineer"
    assert saved_data["response"] == result["response"]
    assert "collected_at" in saved_data


def test_load_raw_result_preserves_metadata(tmp_path):
    result = {
        "career_slug": "data_engineer",
        "career_name": "Data Engineer",
        "query": "Data Engineer",
        "response": {"data": [{"job_title": "Data Engineer"}]},
    }
    run_id = "test-run-002"

    file_path = save_raw_result(
        result=result,
        output_dir=tmp_path,
        run_id=run_id,
        query_number=1,
    )
    
    saved_data = json.loads(file_path.read_text(encoding="utf-8"))

    loaded_results = load_raw_result(
        output_dir=tmp_path,
        run_id=run_id,
        expected_query_count=1,
    )

    assert len(loaded_results) == 1
    loaded_result = loaded_results[0]
    assert loaded_result["run_id"] == run_id
    assert loaded_result["query_number"] == 1
    assert loaded_result["collected_at"]
    assert loaded_result["career_slug"] == "data_engineer"
    assert loaded_result["career_name"] == "Data Engineer"
    assert loaded_result["query"] == "Data Engineer"
    assert loaded_result["response"] == result["response"]
    assert loaded_result["collected_at"] == saved_data["collected_at"]


def test_load_raw_result_rejects_incomplete_run(tmp_path):
    result = {
        "career_slug": "data_engineer",
        "career_name": "Data Engineer",
        "query": "Data Engineer",
        "response": {"data": []},
    }
    run_id = "test-run-incomplete"

    save_raw_result(result, tmp_path, run_id, query_number=1)
    save_raw_result(result, tmp_path, run_id, query_number=3)

    with pytest.raises(ValueError, match="incomplete"):
        load_raw_result(
            output_dir=tmp_path,
            run_id=run_id,
            expected_query_count=3,
        )
        

def test_load_raw_result_raises_when_run_id_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="No raw data found"):
        load_raw_result(
            output_dir=tmp_path,
            run_id="missing-run",
            expected_query_count=6,
        )