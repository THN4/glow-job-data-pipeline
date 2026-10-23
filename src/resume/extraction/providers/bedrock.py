"""Nova Pro adapter preserving the shared CV prompt, schema and repair flow."""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from pydantic import ValidationError

from src.shared.llm.bedrock_client import (
    DEFAULT_NOVA_MODEL, MAX_OUTPUT_TOKENS, BedrockRequestError,
    converse_text, create_bedrock_client,
)
from ...errors import ResumeProcessingError
from ...schemas.cv_extraction import CvExtraction, cv_extraction_json_schema
from ..contracts import ExtractorOutput, PreparedCv, Usage
from ..prompt import SYSTEM_PROMPT, USER_INSTRUCTIONS, repair_instructions

log = logging.getLogger("cv_extraction")


class BedrockExtractor:
    provider = "bedrock_converse"
    groundable = True

    def __init__(self, *, region: str = "us-east-1", model_id: str = DEFAULT_NOVA_MODEL,
                 timeout_ms: int = 180_000):
        self.name = model_id
        self.cache_identity = {
            "temperature": 0, "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseJsonSchema": "CvExtraction-v1", "region": region,
            "responseFormat": "nova-tool-v1",
        }
        self._region = region
        self._timeout_ms = timeout_ms

    async def extract(self, prepared: PreparedCv) -> ExtractorOutput:
        # boto3 is synchronous: keep model IO off the async API event loop.
        return await asyncio.to_thread(self._extract, prepared)

    def _extract(self, prepared: PreparedCv) -> ExtractorOutput:
        client = None
        try:
            client = create_bedrock_client(region=self._region, timeout_ms=self._timeout_ms)
            return self._extract_with_client(client, prepared)
        except BedrockRequestError as error:
            raise ResumeProcessingError(
                "EXTRACTION_TIMEOUT" if error.timeout else "MODEL_UNAVAILABLE", str(error),
            ) from error
        finally:
            if client is not None:
                client.close()

    def _extract_with_client(self, client, prepared: PreparedCv) -> ExtractorOutput:
        usage = Usage()
        # Nova uses a forced tool to carry structured JSON. Keep the complete
        # original contract in the instruction and Pydantic as the authority.
        system = SYSTEM_PROMPT + "\nReturn JSON only matching this schema:\n" + json.dumps(
            CvExtraction.model_json_schema(by_alias=True), ensure_ascii=False,
        ) + "\nReturn the JSON object as the input of the submit_cv tool. Do not emit markdown."
        schema = cv_extraction_json_schema()
        # Nova supports only these three keys at the tool schema's top level.
        # This affects the wire format, not the strict validation contract.
        tool_schema = {key: schema[key] for key in ("type", "properties", "required")}
        field_names = _schema_field_names(schema)
        for schema_attempt in range(2):
            content = _user_parts(prepared)
            if schema_attempt:
                content.extend([
                    {"text": "\n\nPrevious response:\n" + previous_response},
                    {"text": repair_instructions(validation_error)},
                ])
            response = converse_text(client, model_id=self.name, content=content, system=system,
                                     output_schema=tool_schema)
            usage.input_tokens += response.input_tokens
            usage.output_tokens += response.output_tokens
            try:
                return ExtractorOutput(extraction=CvExtraction.model_validate_json(response.text), usage=usage)
            except ValidationError as error:
                previous_response = response.text
                issues = error.errors(include_input=False, include_context=False, include_url=False)
                # Never log document values or unknown model-generated property names.
                safe_issues = [{"type": issue["type"], "path": [
                    part if isinstance(part, int) or part in field_names else "<unknown-field>"
                    for part in issue["loc"]]} for issue in issues[:20]]
                log.warning("cv.nova.schema_invalid %s", json.dumps({
                    "attempt": schema_attempt + 1, "errorCount": len(issues), "issues": safe_issues,
                }))
                validation_error = json.dumps(issues, ensure_ascii=False)[:2000]
        raise ResumeProcessingError("EXTRACTION_FAILED", "Nova did not return the required CV schema.")


def _schema_field_names(node) -> set[str]:
    if not isinstance(node, dict):
        return set()
    names = set(node.get("properties", {}))
    for child in node.values():
        for item in child if isinstance(child, list) else [child]:
            if isinstance(item, dict):
                names.update(_schema_field_names(item))
    return names


def _image_part(image) -> dict:
    return {"image": {"format": image.mime.split("/")[-1],
                      "source": {"bytes": base64.b64decode(image.b64)}}}


def _user_parts(prepared: PreparedCv) -> list[dict]:
    if prepared.kind == "text":
        return [{"text": f"<cv>\n{prepared.text}\n</cv>\n\n{USER_INSTRUCTIONS}"}]
    if prepared.pages:
        parts = [{"text": "<cv pages in original order>\n"}]
        for page in prepared.pages:
            if page.text is not None:
                parts.append({"text": f"--- page {page.page_number} (text) ---\n{page.text}\n"})
            if page.image is not None:
                parts.extend([{"text": f"--- page {page.page_number} (scanned image) ---"}, _image_part(page.image)])
        if prepared.omitted_pages:
            parts.append({"text": "Omitted scanned PDF pages: "
                          + ", ".join(str(page) for page in prepared.omitted_pages)
                          + ". The provided document is partial; do not infer content from omitted pages."})
        parts.extend([{"text": "</cv>\n\n"}, {"text": USER_INSTRUCTIONS}])
        return parts
    return [*(_image_part(image) for image in prepared.images), {"text": USER_INSTRUCTIONS}]
