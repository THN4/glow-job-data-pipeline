"""Bedrock Converse transport shared by CV extraction and RAG text review.

Gemini embeddings and all other pipeline model callers are independent of this adapter.
"""

from __future__ import annotations

from dataclasses import dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_NOVA_MODEL = "amazon.nova-pro-v1:0"
# Nova v1's output limit; reject truncated responses instead of parsing partial JSON.
MAX_OUTPUT_TOKENS = 5000


class BedrockTextSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    AWS_DEFAULT_REGION: str = "us-east-1"
    AWS_REGION: str | None = None
    BEDROCK_RAG_MODEL: str = Field(default=DEFAULT_NOVA_MODEL, min_length=1)


class BedrockRequestError(RuntimeError):
    """Safe provider failure, without credentials, source documents or response bodies."""

    def __init__(self, message: str, *, timeout: bool = False):
        self.timeout = timeout
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


def converse_text(client, *, model_id: str, content: list[dict], system: str | None = None) -> TextResponse:
    request = dict(
        modelId=model_id, messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0},
    )
    if system is not None:
        request["system"] = [{"text": system}]
    try:
        response = client.converse(**request)
    except (ConnectTimeoutError, ReadTimeoutError, TimeoutError) as error:
        raise BedrockRequestError("Bedrock request timed out.", timeout=True) from error
    except (ClientError, BotoCoreError, OSError) as error:
        raise BedrockRequestError("Bedrock request failed. Check AWS credentials, model access and region.") from error
    if response.get("stopReason") != "end_turn":
        raise BedrockRequestError("Bedrock did not return a complete response.")
    text = "".join(block.get("text", "") for block in response.get("output", {}).get("message", {}).get("content", []))
    if not text.strip():
        raise BedrockRequestError("Bedrock returned no text.")
    usage = response.get("usage", {})
    return TextResponse(text, usage.get("inputTokens", 0), usage.get("outputTokens", 0))


def bedrock_generate(prompt: str) -> str:
    """RAG's existing prompt already specifies its JSON contract and evidence rules."""
    cfg = BedrockTextSettings()
    client = create_bedrock_client(region=cfg.AWS_REGION or cfg.AWS_DEFAULT_REGION)
    try:
        return converse_text(client, model_id=cfg.BEDROCK_RAG_MODEL, content=[{"text": prompt}]).text
    finally:
        client.close()
