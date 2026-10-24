import logging
from datetime import datetime, timezone
from pathlib import Path

from src.market.ingestion.raw_storage import (
    load_saved_query, save_raw_result, save_raw_result_to_s3,
)
from src.market.config.settings import Settings
from src.market.ingestion.extract_single_query import extract_single_query

logger = logging.getLogger(__name__)


def _usable_response(response: object) -> bool:
    if not isinstance(response, dict) or response.get("status") not in (None, "OK"):
        return False
    data = response.get("data")
    if isinstance(data, dict):
        data = data.get("jobs")
    return isinstance(data, list)


def extract_jobs(
    settings: Settings,
    *,
    output_dir: Path,
    run_id: str,
    s3_bucket: str | None = None,
    s3_prefix: str = "raw/jsearch",
    resume_raw: bool = False,
) -> list[dict[str, object]]:
    extracted_results = []

    total_queries = sum(len(career.queries) for career in settings.careers.values())

    query_number = 0

    for career_slug, career in settings.careers.items():
        for query in career.queries:

            query_number += 1

            logger.info(
                "Requesting JSearch (%d/%d): career=%s, query=%r",
                query_number,
                total_queries,
                career_slug,
                query,
            )

            result = None
            if resume_raw:
                result = load_saved_query(
                    output_dir=output_dir, run_id=run_id, query_number=query_number,
                    career_slug=career_slug, query=query,
                    s3_bucket=s3_bucket, s3_prefix=s3_prefix,
                )
            if result is not None and not _usable_response(result.get("response")):
                logger.warning("Re-fetching an unusable saved API response: query_number=%d", query_number)
                result = None
            if result is None:
                response_data = extract_single_query(
                    query=query,
                    search_settings=settings.search,
                    jsearch_settings=settings.jsearch,
                )
                collected_at = datetime.now(timezone.utc)
                result = {
                    "run_id": run_id, "query_number": query_number,
                    "collected_at": collected_at.isoformat(),
                    "career_slug": career_slug, "career_name": career.career_name,
                    "query": query, "response": response_data,
                }
            else:
                collected_at = datetime.fromisoformat(
                    str(result["collected_at"]).replace("Z", "+00:00")
                )
                logger.info(
                    "Reusing saved raw query: run_id=%s, query_number=%d", run_id, query_number,
                )

            logger.info(
                "Received JSearch response (%d/%d): career=%s, query=%r",
                query_number,
                total_queries,
                career_slug,
                query,
            )

            # Keep the response before attempting S3 so a failed upload can be
            # retried without another paid JSearch request.
            saved_path = save_raw_result(
                result=result, output_dir=output_dir, run_id=run_id,
                query_number=query_number, collected_at=collected_at,
            )
            if s3_bucket:
                saved_path = save_raw_result_to_s3(
                    result=result,
                    bucket=s3_bucket,
                    prefix=s3_prefix,
                    run_id=run_id,
                    query_number=query_number,
                    collected_at=collected_at,
                )

            if not _usable_response(result.get("response")):
                raise ValueError(
                    f"JSearch query {query_number} returned an unsuccessful or malformed response; "
                    "raw evidence was saved and resume will retry this query"
                )

            extracted_results.append(result)

            logger.info("Saved raw JSearch response: %s", saved_path)

    return extracted_results
