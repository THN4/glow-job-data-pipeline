"""Write reviewed-page candidates to a newline-delimited JSON manifest."""

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from src.documents.schemas.candidate_page import CandidatePage


def write_candidate_manifest(
    pages: Iterable[CandidatePage], destination: Path
) -> int:
    """Atomically write one JSON object per candidate page and return its row count.

    The caller should use a run-specific destination so earlier crawl results remain
    available for review and audit.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    row_count = 0
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as manifest_file:
            temp_path = Path(manifest_file.name)
            for page in pages:
                manifest_file.write(
                    json.dumps(page.to_record(), ensure_ascii=False, sort_keys=True)
                )
                manifest_file.write("\n")
                row_count += 1
        os.replace(temp_path, destination)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    return row_count