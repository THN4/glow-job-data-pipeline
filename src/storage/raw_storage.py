import json
from datetime import datetime, timezone
from pathlib import Path


def save_raw_result(
    result: dict[str, object],
    output_dir: Path,
    run_id: str,
    query_number: int,
) -> Path:

    collected_at = datetime.now(timezone.utc)
    career_slug = str(result["career_slug"])
    date_partition = Path(collected_at.strftime("%Y/%m/%d"))

    file_path = (
        output_dir / date_partition / run_id / f"{query_number:03d}_{career_slug}.json"
    )

    file_path.parent.mkdir(parents=True, exist_ok=True)

    raw_record = {
        "run_id": run_id,
        "query_number": query_number,
        "collected_at": collected_at.isoformat(),
        **result,
    }

    with file_path.open("w", encoding="utf-8") as raw_file:
        json.dump(raw_record, raw_file, ensure_ascii=False, indent=2)

    return file_path


def load_raw_result(
    output_dir: Path,
    run_id: str,
    expected_query_count: int,
) -> list[dict[str, object]]:
    run_dirs = [
        path
        for path in output_dir.rglob(run_id)
        if path.is_dir()
    ]

    if not run_dirs:
        raise FileNotFoundError(f"No raw data found for run_id: {run_id}")

    if len(run_dirs) > 1:
        raise ValueError(f"Multiple raw-data folders found for run_id: {run_id}")

    run_dir = run_dirs[0]
    json_files = list(run_dir.glob("*.json"))

    records = []
    for json_file in json_files:
        with json_file.open("r", encoding="utf-8") as raw_file:
            records.append(json.load(raw_file))

    records.sort(key=lambda record: record["query_number"])

    actual_query_numbers = [record["query_number"] for record in records]
    expected_query_numbers = list(range(1, expected_query_count + 1))

    if actual_query_numbers != expected_query_numbers:
        raise ValueError(
            f"Raw run {run_id} is incomplete: "
            f"expected query numbers {expected_query_numbers}, "
            f"found {actual_query_numbers}"
        )

    result_fields = (
        "run_id",
        "query_number",
        "collected_at",
        "career_slug",
        "career_name",
        "query",
        "response",
    )
    return [
        {field: record[field] for field in result_fields}
        for record in records
    ]
