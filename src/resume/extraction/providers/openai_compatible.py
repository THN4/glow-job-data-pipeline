"""Talks to any OpenAI-compatible chat server: Ollama, vLLM, LM Studio. Used for Qwen on the DevOps notebook."""

from __future__ import annotations

import json
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from ...errors import ResumeProcessingError
from ..prompt import SYSTEM_PROMPT, USER_INSTRUCTIONS, repair_instructions
from ...schemas.cv_extraction import CvExtraction, cv_extraction_json_schema
from ..contracts import ExtractorOutput, PreparedCv, Usage

MAX_TOKENS = 4096


class OpenAiCompatibleExtractor:
    groundable = True

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "not-needed",
        timeout_ms: int = 180_000,
        vision: bool = True,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.name = model
        self.model = model
        self.vision = vision
        self._schema = cv_extraction_json_schema()
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout_ms / 1000,
            max_retries=1,
            http_client=http_client,
        )

    async def extract(self, prepared: PreparedCv) -> ExtractorOutput:
        if prepared.kind == "images" and not self.vision:
            raise ResumeProcessingError(
                "UNREADABLE_DOCUMENT",
                "This file is a scan or photo, and the configured AI model cannot read images. "
                "Please upload a text-based PDF.",
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_content(prepared)},
        ]
        usage = Usage()
        for _attempt in range(2):
            res = await self._complete(messages)
            if res.usage:
                usage.input_tokens += res.usage.prompt_tokens or 0
                usage.output_tokens += res.usage.completion_tokens or 0

            choice = res.choices[0] if res.choices else None
            content = (choice.message.content if choice else None) or ""
            if choice and choice.finish_reason == "length":
                raise ResumeProcessingError("EXTRACTION_FAILED", "The AI response was cut off (output limit reached).")

            try:
                return ExtractorOutput(extraction=CvExtraction.model_validate(parse_json_loose(content)), usage=usage)
            except ValidationError as err:
                error_text = str(err)[:2000]
            # One repair attempt: show the model its own answer and the validation error.
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": repair_instructions(error_text)})

        raise ResumeProcessingError("EXTRACTION_FAILED", "The AI response did not match the expected format.")

    async def _complete(self, messages: list[dict[str, Any]]):
        try:
            return await self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                max_tokens=MAX_TOKENS,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "cv_extraction", "schema": self._schema, "strict": True},
                },
                messages=messages,  # type: ignore[arg-type]
            )
        except APITimeoutError as err:
            raise ResumeProcessingError("EXTRACTION_TIMEOUT") from err
        except APIConnectionError as err:
            raise ResumeProcessingError("MODEL_UNAVAILABLE") from err
        except APIStatusError as err:
            if err.status_code == 404:
                raise ResumeProcessingError("MODEL_UNAVAILABLE", "The configured AI model was not found on the server.") from err
            raise ResumeProcessingError("EXTRACTION_FAILED", f"The AI server returned an error ({err.status_code}).") from err


def _user_content(prepared: PreparedCv) -> list[dict[str, Any]]:
    if prepared.kind == "text":
        return [{"type": "text", "text": f"<cv>\n{prepared.text}\n</cv>\n\n{USER_INSTRUCTIONS}"}]
    return [
        *({"type": "image_url", "image_url": {"url": f"data:{img.mime};base64,{img.b64}"}} for img in prepared.images),
        {"type": "text", "text": USER_INSTRUCTIONS},
    ]


def parse_json_loose(content: str) -> Any:
    """Accepts plain JSON, or JSON wrapped in a ```json fence / surrounding text. Returns None if unparseable."""
    try:
        return json.loads(content)
    except ValueError:
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except ValueError:
                pass
    return None
