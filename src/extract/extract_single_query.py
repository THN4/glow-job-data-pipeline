import os

import requests

from src.config.settings import JSearchSettings, SearchSettings


def extract_single_query(
    query: str,
    search_settings: SearchSettings,
    jsearch_settings: JSearchSettings,
) -> dict:
    api_key = os.getenv(jsearch_settings.api_key_env)
    if not api_key:
        raise ValueError(f"Missing API key: {jsearch_settings.api_key_env}")

    params = {
        "query": query,
        "country": search_settings.country,
        "num_pages": search_settings.max_pages,
        "date_posted": search_settings.date_posted,
    }

    headers = {
        "Content-Type": jsearch_settings.content_type,
        "X-RapidAPI-Host": jsearch_settings.host,
        "X-RapidAPI-Key": api_key,
    }

    response = requests.request(
        method=jsearch_settings.method,
        url=jsearch_settings.url,
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
