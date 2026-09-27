import logging
from pathlib import Path

from src.storage.raw_storage import save_raw_result
from src.config.settings import Settings
from src.extract.extract_single_query import extract_single_query

logger = logging.getLogger(__name__)


def extract_jobs(
    settings: Settings,
    *,
    output_dir: Path,
    run_id: str,
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

            response_data = extract_single_query(
                query=query,
                country=settings.pipeline.country,
                settings=settings.jsearch,
            )

            logger.info(
                "Received JSearch response (%d/%d): career=%s, query=%r",
                query_number,
                total_queries,
                career_slug,
                query,
            )

            result = {
                "career_slug": career_slug,
                "career_name": career.career_name,
                "query": query,
                "response": response_data,
            }

            saved_path = save_raw_result(
                result=result,
                output_dir=output_dir,
                run_id=run_id,
                query_number=query_number,
            )

            extracted_results.append(result)

            logger.info("Saved raw JSearch response: %s", saved_path)

    return extracted_results
