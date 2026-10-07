"""Send skill extraction prompts to the Gemini API."""

import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GEMINI_MODEL = "gemini-3.5-flash-lite"


class GeminiRateLimitError(RuntimeError):
    """The SDK exhausted its own retries for a Gemini 429 response."""


def gemini_generate(prompt: str) -> str:
    """Return Gemini's JSON response text for one prompt."""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    try:
        with genai.Client(api_key=api_key) as client:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            response_text = response.text
    except errors.ClientError as error:
        if error.code == 429:
            raise GeminiRateLimitError(
                "Gemini rate limit reached (HTTP 429); resume this run later"
            ) from error
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
