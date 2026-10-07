"""Persist skill extraction checkpoints for a raw ingestion run."""

import json
import re
from datetime import date, datetime
from pathlib import Path


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _result_path(output_dir: Path, run_id: str) -> Path:
    if not _SAFE_RUN_ID.fullmatch(run_id) or run_id in {".", ".."}:
        raise ValueError("run_id may contain only letters, numbers, '.', '_' and '-'")
    return output_dir / f"{run_id}.json"


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__} to JSON")


def load_skill_results(
    *, run_id: str, output_dir: Path
) -> list[dict[str, object]]:
    """Read a run checkpoint, or return an empty list for a new run."""
    path = _result_path(output_dir, run_id)
    if not path.exists():
        return []

    with path.open(encoding="utf-8") as result_file:
        saved = json.load(result_file)
    if (
        not isinstance(saved, dict)
        or saved.get("run_id") != run_id
        or not isinstance(saved.get("jobs"), list)
        or any(not isinstance(entry, dict) for entry in saved["jobs"])
    ):
        raise ValueError(f"Invalid skill checkpoint for run_id: {run_id}")
    return saved["jobs"]


def save_skill_results(
    jobs: list[dict[str, object]], *, run_id: str, output_dir: Path
) -> Path:
    """Atomically replace a run checkpoint after each processed job."""
    path = _result_path(output_dir, run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as result_file:
        json.dump(
            {"run_id": run_id, "jobs": jobs},
            result_file,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    temporary_path.replace(path)
    return path
