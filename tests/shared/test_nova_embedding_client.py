"""Contract tests for Amazon Nova Multimodal Embeddings."""

import io
import json
import math

import pytest

from src.shared.llm.nova_embedding_client import (
    DIMENSIONS,
    MODEL_ID,
    embed_text,
    vector_literal,
)


class FakeRuntime:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        return {"body": io.BytesIO(json.dumps(self.payload).encode("utf-8"))}


def payload(values=None, *, truncated=None, kind="TEXT"):
    values = values if values is not None else [0.25] * DIMENSIONS
    item = {"embeddingType": kind, "embedding": values}
    if truncated is not None:
        item["truncatedCharLength"] = truncated
    return {"embeddings": [item]}


def test_embed_text_sends_nova_retrieval_request_and_validates_vector():
    client = FakeRuntime(payload())

    vector = embed_text(client, "A synthetic search query", purpose="TEXT_RETRIEVAL")

    call = client.calls[0]
    request = json.loads(call["body"])
    assert call["modelId"] == MODEL_ID
    assert call["contentType"] == call["accept"] == "application/json"
    assert request["taskType"] == "SINGLE_EMBEDDING"
    assert request["singleEmbeddingParams"]["embeddingPurpose"] == "TEXT_RETRIEVAL"
    assert request["singleEmbeddingParams"]["embeddingDimension"] == DIMENSIONS
    assert request["singleEmbeddingParams"]["text"] == {
        "truncationMode": "NONE", "value": "A synthetic search query"
    }
    assert len(vector) == DIMENSIONS and all(math.isfinite(value) for value in vector)


@pytest.mark.parametrize("response, message", [
    (payload([0.1] * (DIMENSIONS - 1)), "Expected 1024 dimensions"),
    (payload(truncated=10), "truncated text"),
    (payload(kind="IMAGE"), "unexpected embedding type"),
    ({"embeddings": []}, "exactly one embedding"),
])
def test_embed_text_rejects_incompatible_response(response, message):
    with pytest.raises(ValueError, match=message):
        embed_text(FakeRuntime(response), "Synthetic text", purpose="GENERIC_INDEX")


def test_vector_literal_rejects_wrong_dimensions_and_non_finite_values():
    with pytest.raises(ValueError, match="1024 finite"):
        vector_literal([0.1])
    values = [0.1] * DIMENSIONS
    values[-1] = float("nan")
    with pytest.raises(ValueError, match="1024 finite"):
        vector_literal(values)
