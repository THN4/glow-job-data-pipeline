"""Shared Gemini model, credential loading, and client setup for pipeline domains."""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors
from google.genai import types


PROJECT_ROOT = Path(__file__).resolve().parents[3]
GEMINI_MODEL = "gemini-3.5-flash-lite"
SERVER_ERROR_MAX_ATTEMPTS = 3
SERVER_ERROR_RETRY_DELAY_SECONDS = 2


class GeminiRateLimitError(RuntimeError):
    """The SDK exhausted its own retries for a Gemini 429 response."""


def create_gemini_client(
    *, api_key: str | None = None, timeout_ms: int | None = None
) -> genai.Client:
    """Create a configured Gemini SDK client using the shared API key by default."""
    resolved_api_key = api_key.strip() if api_key else ""
    if not resolved_api_key:
        load_dotenv(PROJECT_ROOT / ".env")
        resolved_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not resolved_api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    options = {"api_key": resolved_api_key}
    if timeout_ms is not None:
        options["http_options"] = types.HttpOptions(timeout=timeout_ms)
    return genai.Client(**options)


def gemini_generate(prompt: str) -> str:
    """Return Gemini's JSON response text for one prompt."""
    for attempt in range(1, SERVER_ERROR_MAX_ATTEMPTS + 1):
        try:
            with create_gemini_client() as client:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
                response_text = response.text
            break
        except errors.ClientError as error:
            if error.code == 429:
                raise GeminiRateLimitError(
                    "Gemini rate limit reached (HTTP 429); resume this run later"
                ) from error
            raise RuntimeError(
                f"Gemini request failed ({type(error).__name__})"
            ) from error
        except errors.ServerError as error:
            if attempt == SERVER_ERROR_MAX_ATTEMPTS:
                raise RuntimeError(
                    "Gemini server error persisted after "
                    f"{SERVER_ERROR_MAX_ATTEMPTS} attempts (HTTP {error.code})"
                ) from error
            time.sleep(SERVER_ERROR_RETRY_DELAY_SECONDS * attempt)
        except ValueError as error:
            if str(error) == "GEMINI_API_KEY is not set":
                raise
            raise RuntimeError(
                f"Gemini request failed ({type(error).__name__})"
            ) from error
        except Exception as error:
            raise RuntimeError(
                f"Gemini request failed ({type(error).__name__})"
            ) from error

    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError("Gemini returned no text")
    return response_text
