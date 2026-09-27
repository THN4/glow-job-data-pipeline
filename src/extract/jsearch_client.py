import os

import requests

from src.config.settings import JSearchSettings
from src.config.settings import load_settings


def extract_search_jobs(
    query: str,
    country: str,
    settings: JSearchSettings,
) -> dict:
    api_key = os.getenv(settings.api_key_env)
    if not api_key:
        raise ValueError(f"Missing API key: {settings.api_key_env}")

    params = {
        "query": query,
        "country": country,
        "num_pages": settings.num_pages,
        "date_posted": settings.date_posted,
    }

    headers = {
        "Content-Type": settings.content_type,
        "X-RapidAPI-Host": settings.host,
        "X-RapidAPI-Key": api_key,
    }

    response = requests.get(
        settings.url,
        headers=headers,
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()

# Local module testing block
if __name__ == "__main__":
    
    settings = load_settings()
    
    response_data = extract_search_jobs(
        query="Data Engineer",
        country=settings.pipeline.country,
        settings=settings.jsearch,
    )
    
    print(response_data)