"""Back up and restore the small, run-specific Market recovery artifacts."""

import json
from pathlib import Path
from typing import Any

from src.market.ingestion.raw_storage import validate_run_id


class RunArtifactStore:
    def __init__(self, bucket: str, run_id: str, *, prefix: str = "market/pipeline-runs", client: Any = None):
        if not bucket.strip():
            raise ValueError("Run artifact backup requires a bucket")
        validate_run_id(run_id)
        self.bucket = bucket
        self.run_id = run_id
        self.prefix = prefix.strip("/")
        if not self.prefix:
            raise ValueError("Run artifact prefix must not be empty")
        if client is None:
            import boto3
            client = boto3.client("s3")
        self.client = client

    def key(self, name: str) -> str:
        if name not in {"state.json", "skill_checkpoint.json", "summary.json", "company_candidates.csv"}:
            raise ValueError("Unknown Market run artifact")
        return f"{self.prefix}/{self.run_id}/{name}"

    def upload(self, name: str, path: Path) -> str:
        key = self.key(name)
        content_type = "text/csv; charset=utf-8" if name.endswith(".csv") else "application/json; charset=utf-8"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=path.read_bytes(), ContentType=content_type)
        return f"s3://{self.bucket}/{key}"

    def restore_missing(self, name: str, path: Path) -> bool:
        """Never replace local work; a missing S3 key is different from AccessDenied."""
        if path.exists():
            return False
        key = self.key(name)
        found = self.client.list_objects_v2(Bucket=self.bucket, Prefix=key, MaxKeys=1)
        if not any(item.get("Key") == key for item in found.get("Contents", [])):
            return False
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            data = body.read()
        finally:
            body.close()
        if name.endswith(".json"):
            document = json.loads(data)
            if not isinstance(document, dict):
                raise ValueError(f"Invalid saved {name}")
            if name == "state.json":
                saved_run_id = document.get("plan", {}).get("run_id")
            elif name == "summary.json":
                saved_run_id = document.get("run_id")
            else:
                saved_run_id = document.get("run_id")
                if not isinstance(document.get("jobs"), list):
                    raise ValueError("Invalid saved skill checkpoint")
            if saved_run_id != self.run_id:
                raise ValueError(f"Saved {name} belongs to another run")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        return True
