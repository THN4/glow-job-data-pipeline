"""Shared Bedrock Converse text generation for application and pipeline tasks."""

from __future__ import annotations

from dataclasses import dataclass
import json

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_NOVA_MODEL = "us.amazon.nova-2-lite-v1:0"
# Keep the existing output cap; reject truncated responses instead of parsing partial JSON.
MAX_OUTPUT_TOKENS = 5000


class BedrockTextSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    AWS_DEFAULT_REGION: str = "us-east-1"
    AWS_REGION: str | None = None
    BEDROCK_TEXT_MODEL: str | None = None
    # Backward-compatible fallback for existing local .env files.
    BEDROCK_RAG_MODEL: str | None = None

    @property
    def model_id(self) -> str:
        return self.BEDROCK_TEXT_MODEL or self.BEDROCK_RAG_MODEL or DEFAULT_NOVA_MODEL


class BedrockRequestError(RuntimeError):
    """Safe provider failure, without credentials, source documents or response bodies."""

    def __init__(self, message: str, *, timeout: bool = False, retryable: bool = False,
                 code: str | None = None, stop_reason: str | None = None):
        self.timeout = timeout
        self.retryable = retryable
        self.code = code
        self.stop_reason = stop_reason
        super().__init__(message)


@dataclass
class TextResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


def create_bedrock_client(*, region: str, timeout_ms: int = 180_000):
    try:
        return boto3.client(
            "bedrock-runtime", region_name=region,
            config=Config(retries={"total_max_attempts": 3, "mode": "adaptive"},
                          connect_timeout=10, read_timeout=timeout_ms / 1000),
        )
    except (BotoCoreError, OSError) as error:
        raise BedrockRequestError("Bedrock credentials or client configuration are unavailable.") from error


def converse_text(client, *, model_id: str, content: list[dict], system: str | None = None,
                  output_schema: dict | None = None, output_tool_name: str = "submit_cv") -> TextResponse:
    request = dict(
        modelId=model_id, messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0},
    )
    if system is not None:
        request["system"] = [{"text": system}]
    if output_schema is not None:
        request["toolConfig"] = {
            "tools": [{"toolSpec": {
                "name": output_tool_name, "description": "Return the complete result using the required JSON schema.",
                "inputSchema": {"json": output_schema},
            }}],
            "toolChoice": {"tool": {"name": output_tool_name}},
        }
    try:
        response = client.converse(**request)
    except (ConnectTimeoutError, ReadTimeoutError, TimeoutError) as error:
        raise BedrockRequestError("Bedrock request timed out.", timeout=True, code="RequestTimeout") from error
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", "BedrockClientError"))
        if not code.isalnum():
            code = "BedrockClientError"
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        raise BedrockRequestError(
            f"Bedrock request failed ({code}). Check AWS credentials, model access, region and request settings.",
            retryable=code in {"ThrottlingException", "ModelNotReadyException", "ModelTimeoutException"} or status >= 500,
            code=code,
        ) from error
    except (BotoCoreError, OSError) as error:
        error_type = type(error).__name__
        if not error_type.isalnum():
            error_type = "BedrockClientError"
        raise BedrockRequestError(
            f"Bedrock client error ({error_type}). Check AWS credentials, model access and region.", code=error_type,
        ) from error
    expected_stop = "tool_use" if output_schema is not None else "end_turn"
    if response.get("stopReason") != expected_stop:
        stop = response.get("stopReason")
        safe_stop = stop if stop in {"end_turn", "tool_use", "max_tokens", "stop_sequence",
                                    "guardrail_intervened", "content_filtered"} else "unknown"
        raise BedrockRequestError("Bedrock did not return a complete response.",
                                  code="IncompleteResponse", stop_reason=safe_stop)
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    if output_schema is not None:
        tools = [block["toolUse"] for block in blocks if "toolUse" in block]
        if len(tools) != 1 or tools[0].get("name") != output_tool_name or not isinstance(tools[0].get("input"), dict):
            label = "CV" if output_tool_name == "submit_cv" else "structured"
            raise BedrockRequestError(f"Bedrock did not return the required {label} tool response.", code="InvalidToolResponse")
        text = json.dumps(tools[0]["input"], ensure_ascii=False)
    else:
        text = "".join(block.get("text", "") for block in blocks)
    if not text.strip():
        raise BedrockRequestError("Bedrock returned no text.")
    usage = response.get("usage", {})
    return TextResponse(text, usage.get("inputTokens", 0), usage.get("outputTokens", 0))


def nova_generate(prompt: str, *, timeout_ms: int = 90_000, model_id: str | None = None,
                  output_schema: dict | None = None, output_tool_name: str = "submit_cv") -> str:
    """Generate text with the shared Nova model; caller prompts/contracts stay unchanged."""
    cfg = BedrockTextSettings()
    client = create_bedrock_client(
        region=cfg.AWS_REGION or cfg.AWS_DEFAULT_REGION,
        timeout_ms=timeout_ms,
    )
    try:
        return converse_text(
            client,
            model_id=model_id or cfg.model_id,
            content=[{"text": prompt}],
            output_schema=output_schema, output_tool_name=output_tool_name,
        ).text
    finally:
        client.close()


# Compatibility alias for existing RAG scripts; both paths use the configured Nova model.
bedrock_generate = nova_generate
