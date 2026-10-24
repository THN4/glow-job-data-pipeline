"""Amazon Nova Multimodal Embeddings adapter for text retrieval."""

from __future__ import annotations

import json
import math
from typing import Any, Literal

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

MODEL_ID = "amazon.nova-2-multimodal-embeddings-v1:0"
DIMENSIONS = 1024
EmbeddingPurpose = Literal["GENERIC_INDEX", "TEXT_RETRIEVAL"]


def create_nova_embedding_client(region: str = "us-east-1") -> Any:
    """Create a Bedrock Runtime client; boto3 reads AWS_BEARER_TOKEN_BEDROCK."""
    try:
        return boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                retries={"total_max_attempts": 5, "mode": "adaptive"},
                connect_timeout=10,
                read_timeout=60,
            ),
        )
    except (BotoCoreError, OSError) as error:
        raise RuntimeError("Could not configure the Bedrock Runtime client.") from error


def embed_text(client: Any, text: str, *, purpose: EmbeddingPurpose) -> list[float]:
    """Create one Nova vector and validate its type, dimension, and values."""
    if not text.strip():
        raise ValueError("Embedding text must not be empty")

    request = {
        "taskType": "SINGLE_EMBEDDING",
        "singleEmbeddingParams": {
            "embeddingPurpose": purpose,
            "embeddingDimension": DIMENSIONS,
            "text": {"truncationMode": "NONE", "value": text},
        },
    }
    try:
        response = client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(request, ensure_ascii=False),
            accept="application/json",
            contentType="application/json",
        )
        payload = json.loads(response["body"].read())
    except (BotoCoreError, ClientError, OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f"Nova embedding request failed ({type(error).__name__}).") from error

    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != 1:
        raise ValueError("Nova did not return exactly one embedding")
    item = embeddings[0]
    if not isinstance(item, dict) or item.get("embeddingType") != "TEXT":
        raise ValueError("Nova returned an unexpected embedding type")
    if item.get("truncatedCharLength") is not None:
        raise ValueError("Nova truncated text; refusing to store an incomplete embedding")

    values = item.get("embedding")
    if not isinstance(values, list) or len(values) != DIMENSIONS:
        actual = len(values) if isinstance(values, list) else 0
        raise ValueError(f"Expected {DIMENSIONS} dimensions, received {actual}")
    vector = [float(value) for value in values]
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding contains a non-finite value")
    return vector


def vector_literal(values: list[float]) -> str:
    """Serialize a validated Nova vector for pgvector."""
    if len(values) != DIMENSIONS or not all(math.isfinite(value) for value in values):
        raise ValueError(f"Expected {DIMENSIONS} finite vector values")
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"
