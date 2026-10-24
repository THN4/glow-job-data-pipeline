"""Generate Gemini (default) or Nova embeddings for knowledge chunks."""

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
from src.shared.llm.gemini_embedding_client import MODEL_ID as GEMINI_MODEL_ID
from src.shared.llm.nova_embedding_client import (
    DIMENSIONS as NOVA_DIMENSIONS,
    MODEL_ID as NOVA_MODEL_ID,
    create_nova_embedding_client,
    embed_text as embed_nova_text,
    vector_literal as nova_vector_literal,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_ROOT = Path(__file__).resolve().parents[2]
MODEL = GEMINI_MODEL_ID
BATCH_SIZE = 16
RETRY_ATTEMPTS = 3
DEFAULT_TOKENS_PER_MINUTE_TARGET = 24_000
TOKEN_WINDOW_SECONDS = 60
GEMINI_DIMENSIONS = 768


def _load_pending_chunks(connection: Any, limit: int | None, provider: str = "gemini") -> list[tuple[int, str, str]]:
    if provider == "nova":
        query = """
        SELECT c.chunk_id,
               c.content,
               COALESCE(NULLIF(c.metadata->>'page_title', ''), s.title) AS title
        FROM knowledge.knowledge_chunks AS c
        JOIN knowledge.knowledge_sources AS s ON s.source_id = c.source_id
        WHERE c.embedding_nova IS NULL OR c.embedding_nova_model IS DISTINCT FROM %s
        ORDER BY c.chunk_id
        """
        model = NOVA_MODEL_ID
    else:
        query = """
        SELECT c.chunk_id,
               c.content,
               COALESCE(NULLIF(c.metadata->>'page_title', ''), s.title) AS title
        FROM knowledge.knowledge_chunks AS c
        JOIN knowledge.knowledge_sources AS s ON s.source_id = c.source_id
        WHERE c.embedding IS NULL OR c.embedding_model IS DISTINCT FROM %s
        ORDER BY c.chunk_id
        """
        model = GEMINI_MODEL_ID
    parameters: list[Any] = [model]
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
    estimated = 0
    for _, content, title in rows:
        text = _format_document(title, content)
        estimated += max(len(text.split()) * 2, math.ceil(len(text) / 3))
    return estimated


def _wait_for_token_budget(
    recent_batches: deque[tuple[float, int]], batch_tokens: int, target_tokens_per_minute: int,
) -> None:
    while True:
        now = time.monotonic()
        while recent_batches and now - recent_batches[0][0] >= TOKEN_WINDOW_SECONDS:
            recent_batches.popleft()
        used_tokens = sum(tokens for _, tokens in recent_batches)
        if not recent_batches or used_tokens + batch_tokens <= target_tokens_per_minute:
            recent_batches.append((now, batch_tokens))
            return
        wait_seconds = max(0.1, TOKEN_WINDOW_SECONDS - (now - recent_batches[0][0]) + 0.1)
        print(f"Waiting {math.ceil(wait_seconds)}s to stay within the token-rate target")
        time.sleep(wait_seconds)


def _vector_literal(values: list[float], dimensions: int = GEMINI_DIMENSIONS) -> str:
    if len(values) != dimensions or not all(math.isfinite(value) for value in values):
        raise ValueError(f"Expected {dimensions} finite vector values")
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


def _embed_gemini_batch(client: Any, rows: list[tuple[int, str, str]]) -> list[str]:
    contents = [
        types.Content(parts=[types.Part.from_text(text=_format_document(title, content))])
        for _, content, title in rows
    ]
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = client.models.embed_content(
                model=GEMINI_MODEL_ID,
                contents=contents,
                config=types.EmbedContentConfig(output_dimensionality=GEMINI_DIMENSIONS),
            )
            embeddings = response.embeddings or []
            if len(embeddings) != len(rows):
                raise ValueError(f"Gemini returned {len(embeddings)} embeddings for {len(rows)} chunks")
            return [_vector_literal(list(embedding.values or [])) for embedding in embeddings]
        except errors.ClientError as error:
            if error.code == 429:
                raise RuntimeError(
                    "Gemini rate limit reached (HTTP 429). Completed batches are saved; "
                    "rerun this command later to continue with the remaining chunks."
                ) from error
            raise RuntimeError(f"Gemini rejected an embedding request ({type(error).__name__})") from error
        except errors.ServerError as error:
            if attempt == RETRY_ATTEMPTS:
                raise RuntimeError(f"Gemini server error persisted after {RETRY_ATTEMPTS} attempts") from error
            time.sleep(attempt * 2)
    raise RuntimeError("Embedding batch failed")


def _embed_batch(client: Any, rows: list[tuple[int, str, str]], provider: str = "gemini") -> list[str]:
    if provider == "nova":
        return [nova_vector_literal(embed_nova_text(
            client, _format_document(title, content), purpose="GENERIC_INDEX")) for _, content, title in rows]
    return _embed_gemini_batch(client, rows)


def _store_batch(connection: Any, rows: list[tuple[int, str, str]], vectors: list[str], provider: str = "gemini") -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            for (chunk_id, content, _), vector in zip(rows, vectors, strict=True):
                if provider == "nova":
                    cursor.execute(
                        """UPDATE knowledge.knowledge_chunks
                           SET embedding_nova = %s::vector, embedding_nova_model = %s
                           WHERE chunk_id = %s AND content = %s""",
                        (vector, NOVA_MODEL_ID, chunk_id, content),
                    )
                else:
                    cursor.execute(
                        """UPDATE knowledge.knowledge_chunks
                           SET embedding = %s::vector, embedding_model = %s
                           WHERE chunk_id = %s AND content = %s""",
                        (vector, GEMINI_MODEL_ID, chunk_id, content),
                    )
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"Chunk {chunk_id} changed or disappeared while embedding; batch rolled back"
                    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("gemini", "nova"), default="gemini",
                        help="Embedding provider (default: gemini; nova writes the separate 1024-d vector)")
    parser.add_argument("--apply", action="store_true", help="Call the selected provider and save vectors; default is preview")
    parser.add_argument("--limit", type=int, help="Process at most this many pending chunks")
    parser.add_argument("--tokens-per-minute-target", type=int, default=DEFAULT_TOKENS_PER_MINUTE_TARGET,
                        help="Conservative Gemini pacing target (default: 24000)")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.tokens_per_minute_target < 1:
        parser.error("--tokens-per-minute-target must be at least 1")

    # Load the root .env for API-key auth; the shared DB helper also reads the
    # data-pipeline .env for standalone pipeline runs.
    load_dotenv(REPOSITORY_ROOT / ".env")
    load_dotenv(PIPELINE_ROOT / ".env")

    try:
        with get_database_connection() as connection:
            model = NOVA_MODEL_ID if args.provider == "nova" else GEMINI_MODEL_ID
            dimensions = NOVA_DIMENSIONS if args.provider == "nova" else GEMINI_DIMENSIONS
            rows = _load_pending_chunks(connection, args.limit, args.provider)
            print(f"{args.provider.title()} embedding run preview")
            print(f"Model: {model}")
            print(f"Dimensions: {dimensions}")
            print(f"Pending chunks in this run: {len(rows)}")
            print(f"DB commit batch size: {BATCH_SIZE}")
            print(f"Estimated input tokens: about {sum(_estimate_tokens(rows[i : i + BATCH_SIZE]) for i in range(0, len(rows), BATCH_SIZE)):,}")
            print(f"Pacing target: {args.tokens_per_minute_target:,} estimated tokens/minute")
            if not args.apply:
                print("No API calls or database writes were made. Add --apply to proceed.")
                return
            if not rows:
                print("All chunks already have embeddings for this model.")
                return
            if args.provider == "gemini" and not os.getenv("GEMINI_API_KEY", "").strip():
                parser.error("GEMINI_API_KEY is required for Gemini embeddings")
            if args.provider == "nova" and not os.getenv("AWS_BEARER_TOKEN_BEDROCK", "").strip() and not os.getenv("AWS_ACCESS_KEY_ID"):
                print("No Bedrock API key or explicit AWS access key found; boto3 may still use an attached AWS role/profile.")

            if args.provider == "gemini":
                api_key = os.getenv("GEMINI_API_KEY", "").strip()
                if not api_key:
                    raise ValueError("GEMINI_API_KEY is not set in the data-pipeline .env")

            # End the read transaction so each stored DB batch commits independently and can resume.
            connection.commit()
            completed = 0
            if args.provider == "gemini":
                recent_batches: deque[tuple[float, int]] = deque()
                client_context = genai.Client(api_key=api_key)
            else:
                region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
                client_context = create_nova_embedding_client(region)
            with client_context as client:
                for start in range(0, len(rows), BATCH_SIZE):
                    batch = rows[start : start + BATCH_SIZE]
                    if args.provider == "gemini":
                        _wait_for_token_budget(recent_batches, _estimate_tokens(batch), args.tokens_per_minute_target)
                    vectors = _embed_batch(client, batch, args.provider)
                    _store_batch(connection, batch, vectors, args.provider)
                    completed += len(batch)
                    print(f"Embedded and saved {completed}/{len(rows)} chunks")
            print(f"Finished. Stored {completed} {args.provider.title()} vectors ({dimensions} dimensions).")
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
