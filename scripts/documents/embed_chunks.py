"""Generate Gemini Embedding 2 vectors for chunks and store them in pgvector."""

import argparse
from collections import deque
import math
import os
from pathlib import Path
import time
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import errors
from google.genai import types

from src.shared.db.database import get_database_connection

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL = "gemini-embedding-2"
DIMENSIONS = 768
BATCH_SIZE = 16
RETRY_ATTEMPTS = 3
DEFAULT_TOKENS_PER_MINUTE_TARGET = 24_000
TOKEN_WINDOW_SECONDS = 60


def _load_pending_chunks(connection: Any, limit: int | None) -> list[tuple[int, str, str]]:
    query = """
        SELECT c.chunk_id,
               c.content,
               COALESCE(NULLIF(c.metadata->>'page_title', ''), s.title) AS title
        FROM knowledge.knowledge_chunks AS c
        JOIN knowledge.knowledge_sources AS s ON s.source_id = c.source_id
        WHERE c.embedding IS NULL OR c.embedding_model IS DISTINCT FROM %s
        ORDER BY c.chunk_id
    """
    parameters: list[Any] = [MODEL]
    if limit is not None:
        query += " LIMIT %s"
        parameters.append(limit)
    with connection.cursor() as cursor:
        cursor.execute(query, parameters)
        return cursor.fetchall()


def _format_document(title: str, content: str) -> str:
    safe_title = title.strip() or "none"
    return f"title: {safe_title} | text: {content}"


def _estimate_tokens(rows: list[tuple[int, str, str]]) -> int:
    """Roughly estimate tokens from text size without an extra API call."""
    estimated = 0
    for _, content, title in rows:
        text = _format_document(title, content)
        word_estimate = len(text.split()) * 2
        character_estimate = math.ceil(len(text) / 3)
        estimated += max(word_estimate, character_estimate)
    return estimated


def _wait_for_token_budget(
    recent_batches: deque[tuple[float, int]],
    batch_tokens: int,
    target_tokens_per_minute: int,
) -> None:
    while True:
        now = time.monotonic()
        while recent_batches and now - recent_batches[0][0] >= TOKEN_WINDOW_SECONDS:
            recent_batches.popleft()
        used_tokens = sum(tokens for _, tokens in recent_batches)
        if not recent_batches or used_tokens + batch_tokens <= target_tokens_per_minute:
            recent_batches.append((now, batch_tokens))
            return

        wait_seconds = max(
            0.1,
            TOKEN_WINDOW_SECONDS - (now - recent_batches[0][0]) + 0.1,
        )
        print(f"Waiting {math.ceil(wait_seconds)}s to stay within the token-rate target")
        time.sleep(wait_seconds)


def _vector_literal(values: list[float]) -> str:
    if len(values) != DIMENSIONS:
        raise ValueError(f"Expected {DIMENSIONS} dimensions, received {len(values)}")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Embedding contains a non-finite value")
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


def _embed_batch(client: Any, rows: list[tuple[int, str, str]]) -> list[str]:
    contents = [
        types.Content(parts=[types.Part.from_text(text=_format_document(title, content))])
        for _, content, title in rows
    ]
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = client.models.embed_content(
                model=MODEL,
                contents=contents,
                config=types.EmbedContentConfig(output_dimensionality=DIMENSIONS),
            )
            embeddings = response.embeddings or []
            if len(embeddings) != len(rows):
                raise ValueError(
                    f"Gemini returned {len(embeddings)} embeddings for {len(rows)} chunks"
                )
            return [_vector_literal(list(embedding.values or [])) for embedding in embeddings]
        except errors.ClientError as error:
            if error.code == 429:
                raise RuntimeError(
                    "Gemini rate limit reached (HTTP 429). Completed batches are saved; "
                    "rerun this command later to continue with the remaining chunks."
                ) from error
            raise RuntimeError(
                f"Gemini rejected an embedding request ({type(error).__name__})"
            ) from error
        except errors.ServerError as error:
            if attempt == RETRY_ATTEMPTS:
                raise RuntimeError(
                    f"Gemini server error persisted after {RETRY_ATTEMPTS} attempts"
                ) from error
            time.sleep(attempt * 2)
    raise RuntimeError("Embedding batch failed")


def _store_batch(connection: Any, rows: list[tuple[int, str, str]], vectors: list[str]) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            for (chunk_id, content, _), vector in zip(rows, vectors, strict=True):
                cursor.execute(
                    """
                    UPDATE knowledge.knowledge_chunks
                    SET embedding = %s::vector, embedding_model = %s
                    WHERE chunk_id = %s AND content = %s
                    """,
                    (vector, MODEL, chunk_id, content),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"Chunk {chunk_id} changed or disappeared while embedding; batch rolled back"
                    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Call Gemini and save vectors; default is preview")
    parser.add_argument("--limit", type=int, help="Process at most this many pending chunks")
    parser.add_argument(
        "--tokens-per-minute-target",
        type=int,
        default=DEFAULT_TOKENS_PER_MINUTE_TARGET,
        help="Conservative local pacing target (default: 24000, below the shown 30000 TPM quota)",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.tokens_per_minute_target < 1:
        parser.error("--tokens-per-minute-target must be at least 1")

    try:
        with get_database_connection() as connection:
            rows = _load_pending_chunks(connection, args.limit)
            print("Embedding run preview")
            print(f"Model: {MODEL}")
            print(f"Dimensions: {DIMENSIONS}")
            print(f"Pending chunks in this run: {len(rows)}")
            print(f"API batch size: {BATCH_SIZE}")
            print(f"Estimated input tokens: about {sum(_estimate_tokens(rows[i : i + BATCH_SIZE]) for i in range(0, len(rows), BATCH_SIZE)):,}")
            print(f"Pacing target: {args.tokens_per_minute_target:,} estimated tokens/minute")
            if not args.apply:
                print("No API calls or database writes were made. Add --apply to proceed.")
                return
            if not rows:
                print("All chunks already have embeddings for this model.")
                return

            load_dotenv(PROJECT_ROOT / ".env")
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            if not api_key:
                raise ValueError("GEMINI_API_KEY is not set in the data-pipeline .env")

            # End the read transaction so each stored batch commits independently and can resume.
            connection.commit()
            completed = 0
            recent_batches: deque[tuple[float, int]] = deque()
            with genai.Client(api_key=api_key) as client:
                for start in range(0, len(rows), BATCH_SIZE):
                    batch = rows[start : start + BATCH_SIZE]
                    estimated_tokens = _estimate_tokens(batch)
                    _wait_for_token_budget(
                        recent_batches,
                        estimated_tokens,
                        args.tokens_per_minute_target,
                    )
                    vectors = _embed_batch(client, batch)
                    _store_batch(connection, batch, vectors)
                    completed += len(batch)
                    print(f"Embedded and saved {completed}/{len(rows)} chunks")
            print(f"Finished. Stored {completed} vectors using {MODEL} ({DIMENSIONS} dimensions).")
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
