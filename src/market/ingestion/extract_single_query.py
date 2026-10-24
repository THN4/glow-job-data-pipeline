import os
from functools import lru_cache

import requests

from src.market.config.settings import JSearchSettings, SearchSettings


@lru_cache(maxsize=8)
def _secret_string(secret_id: str) -> str:
    """Load and cache a plaintext secret using the ambient AWS credentials."""
    import boto3

    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    secret_value = response.get("SecretString")
    if not isinstance(secret_value, str) or not secret_value.strip():
        raise ValueError("JSearch secret must contain a non-empty SecretString")
    return secret_value.strip()


def _api_key(api_key_env: str) -> str:
    api_key = os.getenv(api_key_env, "").strip()
    if api_key:
        return api_key

    secret_id = os.getenv("JSEARCH_SECRET_ID", "").strip()
    if secret_id:
        try:
            return _secret_string(secret_id)
        except Exception as error:
            raise RuntimeError(
                f"Could not load JSearch API key from Secrets Manager secret {secret_id!r}"
            ) from error

    raise ValueError(
        f"Set {api_key_env} or configure JSEARCH_SECRET_ID for Secrets Manager"
    )


def extract_single_query(
    query: str,
    search_settings: SearchSettings,
    jsearch_settings: JSearchSettings,
) -> dict:
    api_key = _api_key(jsearch_settings.api_key_env)

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
