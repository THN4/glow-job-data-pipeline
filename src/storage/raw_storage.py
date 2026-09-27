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
