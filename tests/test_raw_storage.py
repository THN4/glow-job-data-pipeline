import json

from src.storage.raw_storage import save_raw_result


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