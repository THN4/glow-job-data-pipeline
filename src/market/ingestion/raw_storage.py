import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _raw_record(
    result: dict[str, object],
    *,
    run_id: str,
    query_number: int,
    collected_at: datetime,
) -> dict[str, object]:
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)
    collected_at = collected_at.astimezone(timezone.utc)
    return {
        "run_id": run_id,
        "query_number": query_number,
        "collected_at": collected_at.isoformat(),
        **result,
    }


def _raw_object_key(
    *, prefix: str, run_id: str, query_number: int, career_slug: str, collected_at: datetime
) -> str:
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)
    collected_at = collected_at.astimezone(timezone.utc)
    date_partition = collected_at.strftime("%Y/%m/%d")
    normalized_prefix = prefix.strip("/")
    key_prefix = f"{normalized_prefix}/" if normalized_prefix else ""
    return (
        f"{key_prefix}{date_partition}/{run_id}/"
        f"{query_number:03d}_{career_slug}.json"
    )


def save_raw_result(
    result: dict[str, object],
    output_dir: Path,
    run_id: str,
    query_number: int,
    *,
    collected_at: datetime | None = None,
) -> Path:

    collected_at = collected_at or datetime.now(timezone.utc)
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)
    collected_at = collected_at.astimezone(timezone.utc)
    career_slug = str(result["career_slug"])
    date_partition = Path(collected_at.strftime("%Y/%m/%d"))

    file_path = (
        output_dir / date_partition / run_id / f"{query_number:03d}_{career_slug}.json"
    )

    file_path.parent.mkdir(parents=True, exist_ok=True)

    raw_record = _raw_record(
        result,
        run_id=run_id,
        query_number=query_number,
        collected_at=collected_at,
    )

    with file_path.open("w", encoding="utf-8") as raw_file:
        json.dump(raw_record, raw_file, ensure_ascii=False, indent=2)

    return file_path


def save_raw_result_to_s3(
    result: dict[str, object],
    *,
    bucket: str,
    run_id: str,
    query_number: int,
    prefix: str = "raw/jsearch",
    collected_at: datetime | None = None,
    s3_client: Any | None = None,
) -> str:
    """Save one complete JSearch response to S3 using the ambient AWS role."""
    if not bucket.strip():
        raise ValueError("S3 bucket must be non-empty")

    collected_at = collected_at or datetime.now(timezone.utc)
    career_slug = str(result["career_slug"])
    object_key = _raw_object_key(
        prefix=prefix,
        run_id=run_id,
        query_number=query_number,
        career_slug=career_slug,
        collected_at=collected_at,
    )
    client = s3_client
    if client is None:
        import boto3

        client = boto3.client("s3")

    raw_record = _raw_record(
        result,
        run_id=run_id,
        query_number=query_number,
        collected_at=collected_at,
    )
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=json.dumps(raw_record, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    return f"s3://{bucket}/{object_key}"


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
