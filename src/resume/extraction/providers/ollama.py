"""Talks to Ollama through its native /api/chat endpoint.

Why not just the OpenAI-compatible /v1 endpoint? The native API lets the backend set, per request:
  * ``num_ctx``: Ollama otherwise loads many models with their full (e.g. 131k) context, which spills
    the KV cache out of GPU memory and makes inference many times slower on a small GPU;
  * ``think``: thinking models (Qwen3 / Qwen3.5) otherwise spend the token budget reasoning first.
The JSON schema goes in ``format`` (constrained decoding) and images are sent as base64 in ``images``.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from ...errors import ResumeProcessingError
from ..prompt import SYSTEM_PROMPT, USER_INSTRUCTIONS, repair_instructions
from ...schemas.cv_extraction import CvExtraction, cv_extraction_json_schema
from ..contracts import ExtractorOutput, PreparedCv, Usage
from .openai_compatible import parse_json_loose

MAX_TOKENS = 4096


class OllamaExtractor:
    groundable = True

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_ms: int = 180_000,
        vision: bool = True,
        num_ctx: int = 16384,
        think: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.name = model
        self.model = model
        self.vision = vision
        self.num_ctx = num_ctx
        self.think = think
        base = base_url.rstrip("/")
        self._url = f"{base.removesuffix('/v1')}/api/chat"  # accept both http://host:11434 and .../v1
        self._schema = cv_extraction_json_schema()
        self._client = http_client or httpx.AsyncClient(timeout=timeout_ms / 1000)

    async def extract(self, prepared: PreparedCv) -> ExtractorOutput:
        if prepared.kind == "images" and not self.vision:
            raise ResumeProcessingError(
                "UNREADABLE_DOCUMENT",
                "This file is a scan or photo, and the configured AI model cannot read images. "
                "Please upload a text-based PDF.",
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            _user_message(prepared),
        ]
        usage = Usage()
        for _attempt in range(2):
            data = await self._chat(messages)
            usage.input_tokens += data.get("prompt_eval_count") or 0
            usage.output_tokens += data.get("eval_count") or 0
            content = (data.get("message") or {}).get("content") or ""
            if data.get("done_reason") == "length":
                raise ResumeProcessingError("EXTRACTION_FAILED", "The AI response was cut off (output limit reached).")
            try:
                return ExtractorOutput(extraction=CvExtraction.model_validate(parse_json_loose(content)), usage=usage)
            except ValidationError as err:
                error_text = str(err)[:2000]
            # One repair attempt: show the model its own answer and the validation error.
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": repair_instructions(error_text)})

        raise ResumeProcessingError("EXTRACTION_FAILED", "The AI response did not match the expected format.")

    async def _chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "stream": False,
            "think": self.think,
            "format": self._schema,
            "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": MAX_TOKENS},
            "messages": messages,
        }
        try:
            res = await self._client.post(self._url, json=body)
        except httpx.TimeoutException as err:
            raise ResumeProcessingError("EXTRACTION_TIMEOUT") from err
        except httpx.TransportError as err:  # connection refused, DNS, reset...
            raise ResumeProcessingError("MODEL_UNAVAILABLE") from err

        if res.status_code == 404:
            raise ResumeProcessingError("MODEL_UNAVAILABLE", "The configured AI model was not found on the server.")
        if res.status_code >= 400:
            raise ResumeProcessingError("EXTRACTION_FAILED", f"The AI server returned an error ({res.status_code}).")
        try:
            return res.json()
        except ValueError as err:
            raise ResumeProcessingError("EXTRACTION_FAILED", "The AI server returned an unreadable response.") from err


def _user_message(prepared: PreparedCv) -> dict[str, Any]:
    if prepared.kind == "text":
        return {"role": "user", "content": f"<cv>\n{prepared.text}\n</cv>\n\n{USER_INSTRUCTIONS}"}
    return {"role": "user", "content": USER_INSTRUCTIONS, "images": [img.b64 for img in prepared.images]}
