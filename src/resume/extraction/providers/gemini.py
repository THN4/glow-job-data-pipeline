"""Gemini adapter for structured CV extraction, including scanned CV images."""

from __future__ import annotations

import asyncio
import base64

import httpx
from google.genai import errors, types
from pydantic import ValidationError

from src.shared.llm.gemini_client import GEMINI_MODEL, create_gemini_client

from ...errors import ResumeProcessingError
from ..contracts import ExtractorOutput, PreparedCv, Usage
from ..prompt import SYSTEM_PROMPT, USER_INSTRUCTIONS, repair_instructions
from ...schemas.cv_extraction import CvExtraction

MAX_OUTPUT_TOKENS = 8192


class GeminiExtractor:
    """Extract a CV through the same Gemini model and API key as the market pipeline."""

    provider = "gemini"
    groundable = True

    def __init__(self, *, api_key: str, timeout_ms: int = 180_000):
        if not api_key.strip():
            raise ValueError("GEMINI_API_KEY is not set")
        self.name = GEMINI_MODEL
        self.cache_identity = {
            "temperature": 0,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseJsonSchema": "CvExtraction-v1",
        }
        self._client_owner = create_gemini_client(api_key=api_key, timeout_ms=timeout_ms)
        self._client = self._client_owner.aio

    async def extract(self, prepared: PreparedCv) -> ExtractorOutput:
        contents = _user_parts(prepared)
        usage = Usage()

        for schema_attempt in range(2):
            contents = _user_parts(prepared)
            if schema_attempt:
                contents.extend(
                    [
                        "\n\nPrevious response:\n" + previous_response,
                        repair_instructions(validation_error),
                    ]
                )

            for service_attempt in range(3):
                try:
                    response = await self._client.models.generate_content(
                        model=self.name,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            temperature=0,
                            max_output_tokens=MAX_OUTPUT_TOKENS,
                            response_mime_type="application/json",
                            # Pydantic models are converted to the Gemini Schema
                            # representation by the SDK. That path serializes
                            # `additionalProperties` as `additional_properties`,
                            # which Gemini rejects. Pass Pydantic's JSON Schema via
                            # the dedicated JSON Schema field instead; we still
                            # validate the returned JSON strictly with Pydantic.
                            response_json_schema=CvExtraction.model_json_schema(by_alias=True),
                        ),
                    )
                    break
                except (TimeoutError, httpx.TimeoutException) as err:
                    raise ResumeProcessingError("EXTRACTION_TIMEOUT") from err
                except errors.APIError as err:
                    if err.code in (429, 500, 503) and service_attempt < 2:
                        await asyncio.sleep(1.0 * (2**service_attempt))
                        continue
                    if err.code == 404:
                        raise ResumeProcessingError(
                            "MODEL_UNAVAILABLE", "The configured Gemini model was not found."
                        ) from err
                    raise ResumeProcessingError(
                        "EXTRACTION_FAILED", f"Gemini returned an error ({err.code})."
                    ) from err
                except Exception as err:  # noqa: BLE001 - normalize SDK/network failures
                    raise ResumeProcessingError("MODEL_UNAVAILABLE", "Could not connect to Gemini.") from err

            metadata = response.usage_metadata
            usage.input_tokens += getattr(metadata, "prompt_token_count", 0) or 0
            usage.output_tokens += getattr(metadata, "candidates_token_count", 0) or 0
            candidates = response.candidates or []
            finish_reason = candidates[0].finish_reason if candidates else None
            if getattr(finish_reason, "name", str(finish_reason)) == "MAX_TOKENS":
                raise ResumeProcessingError(
                    "EXTRACTION_FAILED", "Gemini's structured response was cut off at the output limit."
                )
            content = response.text or ""
            if not content.strip():
                raise ResumeProcessingError("EXTRACTION_FAILED", "Gemini returned no structured output.")
            try:
                return ExtractorOutput(
                    extraction=CvExtraction.model_validate_json(content),
                    usage=usage,
                )
            except ValidationError as err:
                previous_response = content
                validation_error = str(err)[:2000]

        raise ResumeProcessingError("EXTRACTION_FAILED", "Gemini did not return the required CV schema.")


def _user_parts(prepared: PreparedCv) -> list[str | types.Part]:
    if prepared.kind == "text":
        return [f"<cv>\n{prepared.text}\n</cv>\n\n{USER_INSTRUCTIONS}"]
    if prepared.pages:
        parts: list[str | types.Part] = ["<cv pages in original order>\n"]
        for page in prepared.pages:
            if page.text is not None:
                parts.append(f"--- page {page.page_number} (text) ---\n{page.text}\n")
            if page.image is not None:
                parts.extend(
                    [
                        f"--- page {page.page_number} (scanned image) ---",
                        types.Part.from_bytes(
                            data=base64.b64decode(page.image.b64), mime_type=page.image.mime
                        ),
                    ]
                )
        if prepared.omitted_pages:
            parts.append(
                "Omitted scanned PDF pages: "
                + ", ".join(str(page) for page in prepared.omitted_pages)
                + ". The provided document is partial; do not infer content from omitted pages."
            )
        parts.extend(["</cv>\n\n", USER_INSTRUCTIONS])
        return parts
    return [
        *(
            types.Part.from_bytes(data=base64.b64decode(image.b64), mime_type=image.mime)
            for image in prepared.images
        ),
        USER_INSTRUCTIONS,
    ]
