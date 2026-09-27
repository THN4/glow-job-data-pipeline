import logging

from src.config.settings import Settings
from src.extract.extract_single_query import extract_single_query

logger = logging.getLogger(__name__)


def extract_jobs(settings: Settings) -> list[dict[str, object]]:
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
            extracted_results.append(
                {
                    "career_slug": career_slug,
                    "career_name": career.career_name,
                    "query": query,
                    "response": response_data,
                }
            )

    return extracted_results
