import os

import requests

from src.config.settings import JSearchSettings


def extract_single_query(
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

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unspecified")
        raise requests.HTTPError(
            f"JSearch rate limit exceeded (HTTP 429). Retry-After: {retry_after}",
            response=response,
        )

    response.raise_for_status()
    return response.json()
