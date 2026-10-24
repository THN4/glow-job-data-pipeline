import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def validate_run_id(run_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id) or run_id in {".", ".."}:
        raise ValueError("run_id contains unsafe path characters")


def _partition(run_id: str, collected_at: datetime) -> str:
    validate_run_id(run_id)
    # New timestamp run IDs keep every response in the run's start-day folder,
    # including a request that finishes after midnight. Legacy labels retain
    # the collection-day convention.
    if re.fullmatch(r"\d{8}T\d{6,12}Z", run_id):
        return datetime.strptime(run_id[:8], "%Y%m%d").strftime("%Y/%m/%d")
    return collected_at.astimezone(timezone.utc).strftime("%Y/%m/%d")


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
    date_partition = _partition(run_id, collected_at)
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
    date_partition = Path(_partition(run_id, collected_at))

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

    temporary_path = file_path.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as raw_file:
        json.dump(raw_record, raw_file, ensure_ascii=False, indent=2)
    temporary_path.replace(file_path)

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


def load_saved_query(
    *, output_dir: Path, run_id: str, query_number: int, career_slug: str,
    query: str, s3_bucket: str | None = None, s3_prefix: str = "raw/jsearch",
) -> dict[str, object] | None:
    """Resume a timestamp run using local raw data, then an exact S3 object.

    Missing keys allow the caller to fetch the query. Access errors, corrupt
    responses and changed query configurations fail instead of being re-fetched.
    """
    validate_run_id(run_id)
    if not re.fullmatch(r"\d{8}T\d{6,12}Z", run_id):
        raise ValueError("Resumable ingestion requires a timestamp run ID")
    key = _raw_object_key(
        prefix="", run_id=run_id, query_number=query_number,
        career_slug=career_slug, collected_at=datetime.now(timezone.utc),
    )
    path = output_dir / key
    if path.is_file():
        record = json.loads(path.read_text(encoding="utf-8"))
    elif s3_bucket:
        import boto3
        from botocore.exceptions import ClientError

        s3_key = "/".join(part for part in (s3_prefix.strip("/"), key) if part)
        client = boto3.client("s3")
        # A missing GetObject can return AccessDenied without ListBucket. Check
        # the exact prefix first so a missing response is not confused with an
        # IAM failure. List permission can be restricted to raw/jsearch/*.
        found = client.list_objects_v2(Bucket=s3_bucket, Prefix=s3_key, MaxKeys=1)
        if not any(item.get("Key") == s3_key for item in found.get("Contents", [])):
            return None
        try:
            response = client.get_object(Bucket=s3_bucket, Key=s3_key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        body = response["Body"]
        try:
            record = json.loads(body.read())
        finally:
            body.close()
    else:
        return None
    if not isinstance(record, dict) or any(
        record.get(field) != expected for field, expected in (
            ("run_id", run_id), ("query_number", query_number),
            ("career_slug", career_slug), ("query", query),
        )
    ) or not isinstance(record.get("response"), dict):
        raise ValueError(f"Saved raw query {query_number} does not match this run/config")
    collected_at = datetime.fromisoformat(str(record["collected_at"]).replace("Z", "+00:00"))
    if collected_at.tzinfo is None:
        raise ValueError("Saved raw timestamp must include a timezone")
    save_raw_result(record, output_dir, run_id, query_number, collected_at=collected_at)
    return record


def load_raw_result(
    output_dir: Path,
    run_id: str,
    expected_query_count: int,
) -> list[dict[str, object]]:
    validate_run_id(run_id)
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
