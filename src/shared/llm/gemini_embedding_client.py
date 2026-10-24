"""Gemini Embedding 2 adapter shared by indexing and retrieval."""

from __future__ import annotations

import math
from typing import Any, Literal

from google.genai import types

from src.shared.llm.gemini_client import create_gemini_client

MODEL_ID = "gemini-embedding-2"
DIMENSIONS = 768
EmbeddingTask = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


def embed_text(client: Any, text: str, *, task_type: EmbeddingTask | None = None) -> list[float]:
    if not text.strip():
        raise ValueError("Embedding text must not be empty")
    response = client.models.embed_content(
        model=MODEL_ID,
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=DIMENSIONS),
    )
    embeddings = getattr(response, "embeddings", None) or []
    values = getattr(embeddings[0], "values", None) if embeddings else None
    if not isinstance(values, list) or len(values) != DIMENSIONS:
        raise ValueError("Gemini returned an embedding with an invalid dimension")
    vector = [float(value) for value in values]
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Gemini returned a non-finite embedding value")
    return vector


def embed_documents(client: Any, texts: list[str]) -> list[list[float]]:
    """Embed a batch with the legacy Gemini request shape and output dimensions."""
    if not texts or any(not text.strip() for text in texts):
        raise ValueError("Embedding texts must not be empty")
    contents = [types.Content(parts=[types.Part.from_text(text=text)]) for text in texts]
    response = client.models.embed_content(
        model=MODEL_ID,
        contents=contents,
        config=types.EmbedContentConfig(output_dimensionality=DIMENSIONS),
    )
    embeddings = getattr(response, "embeddings", None) or []
    if len(embeddings) != len(texts):
        raise ValueError("Gemini returned an unexpected number of embeddings")
    vectors = []
    for embedding in embeddings:
        values = getattr(embedding, "values", None)
        if not isinstance(values, list) or len(values) != DIMENSIONS:
            raise ValueError("Gemini returned an embedding with an invalid dimension")
        vector = [float(value) for value in values]
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Gemini returned a non-finite embedding value")
        vectors.append(vector)
    return vectors


def vector_literal(values: list[float]) -> str:
    if len(values) != DIMENSIONS or not all(math.isfinite(value) for value in values):
        raise ValueError(f"Expected {DIMENSIONS} finite vector values")
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"
