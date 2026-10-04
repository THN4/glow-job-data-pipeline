"""Write fuzzy company-match suggestions as a human-review CSV."""

import csv
import re
from pathlib import Path

_COLUMNS = (
    "run_id",
    "query_numbers",
    "job_id",
    "job_title",
    "employer_name",
    "employer_website",
    "normalized_company_name",
    "candidate_company",
    "candidate_matched_alias",
    "candidate_score",
    "candidate_source",
    "publisher",
    "source_url",
    "review_decision",
    "confirmed_company_name",
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def save_company_match_candidates(
    jobs: list[dict[str, object]],
    *,
    run_id: str,
    output_dir: Path = Path("data/processed/company_match_candidates"),
) -> Path:
    """Write fuzzy candidates, retaining a header-only report when none are found."""
    if not _SAFE_RUN_ID.fullmatch(run_id) or run_id in {".", ".."}:
        raise ValueError("run_id may contain only letters, numbers, '.', '_' and '-'")

    rows: list[dict[str, object]] = []
    for entry in jobs:
        job = entry.get("job")
        if not isinstance(job, dict):
            continue
        normalization = job.get("company_normalization")
        if not isinstance(normalization, dict):
            continue
        candidates = normalization.get("candidates")
        if not isinstance(candidates, list):
            continue

        metadata = entry.get("metadata")
        matches = entry.get("matches")
        query_references = matches if isinstance(matches, list) else [metadata]
        query_numbers = sorted(
            {
                str(reference["query_number"])
                for reference in query_references
                if isinstance(reference, dict)
                and reference.get("query_number") is not None
            }
        )

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            rows.append(
                {
                    "run_id": run_id,
                    "job_id": job.get("job_id", ""),
                    "job_title": job.get("job_title", ""),
                    "employer_name": job.get("employer_name", ""),
                    "employer_website": job.get("employer_website", ""),
                    "normalized_company_name": normalization.get(
                        "normalized_name", ""
                    ),
                    "candidate_company": candidate.get("canonical_name", ""),
                    "candidate_matched_alias": candidate.get("matched_alias", ""),
                    "candidate_score": candidate.get("score", ""),
                    "candidate_source": candidate.get("candidate_source", ""),
                    "publisher": job.get("job_publisher", ""),
                    "source_url": job.get("job_url") or job.get("job_apply_link", ""),
                    "query_numbers": ",".join(query_numbers),
                    "review_decision": "",
                    "confirmed_company_name": "",
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{run_id}.csv"
    with report_path.open("w", encoding="utf-8-sig", newline="") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return report_path
