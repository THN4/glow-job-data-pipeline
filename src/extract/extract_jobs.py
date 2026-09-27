from src.config.settings import Settings
from src.extract.extract_single_query import extract_single_query


def extract_jobs(settings: Settings) -> list[dict[str, object]]:
    extracted_results = []

    for career_slug, career in settings.careers.items():
        for query in career.queries:
            response_data = extract_single_query(
                query=query,
                country=settings.pipeline.country,
                settings=settings.jsearch,
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