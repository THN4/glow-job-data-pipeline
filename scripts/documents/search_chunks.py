"""Search Gemini vectors by default, or the separate Nova vectors."""

import argparse
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.shared.db.database import get_database_connection
from src.shared.llm.gemini_embedding_client import (
    MODEL_ID as GEMINI_MODEL_ID,
    create_gemini_client,
    embed_text as embed_gemini_text,
    vector_literal as gemini_vector_literal,
)
from src.shared.llm.nova_embedding_client import (
    MODEL_ID as NOVA_MODEL_ID,
    create_nova_embedding_client,
    embed_text as embed_nova_text,
    vector_literal as nova_vector_literal,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
def _embed_query(client: Any, query: str, provider: str = "gemini") -> str:
    if provider == "nova":
        return nova_vector_literal(embed_nova_text(client, query.strip(), purpose="TEXT_RETRIEVAL"))
    return gemini_vector_literal(embed_gemini_text(client, query.strip(), task_type="RETRIEVAL_QUERY"))


def _resolve_skill(connection: Any, skill_name: str) -> tuple[int, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT skill_id, skill_name
            FROM core.skills
            WHERE lower(skill_name) = lower(%s)
            """,
            (skill_name.strip(),),
        )
        matches = cursor.fetchall()
        if not matches:
            cursor.execute(
                """
                SELECT s.skill_id, s.skill_name
                FROM core.skill_aliases AS a
                JOIN core.skills AS s ON s.skill_id = a.skill_id
                WHERE lower(a.alias) = lower(%s)
                """,
                (skill_name.strip(),),
            )
            matches = cursor.fetchall()
    if not matches:
        raise ValueError(f"Skill not found in core.skills or core.skill_aliases: {skill_name}")
    if len(matches) > 1:
        raise ValueError(f"Skill label is ambiguous in the catalog: {skill_name}")
    return matches[0]


def _search(
    connection: Any,
    vector: str,
    limit: int,
    skill_id: int | None,
    provider: str = "gemini",
) -> list[tuple[Any, ...]]:
    skill_filter = ""
    model = NOVA_MODEL_ID if provider == "nova" else GEMINI_MODEL_ID
    embedding_column = "embedding_nova" if provider == "nova" else "embedding"
    model_column = "embedding_nova_model" if provider == "nova" else "embedding_model"
    parameters: list[Any] = [vector, model]
    if skill_id is not None:
        skill_filter = """
            AND EXISTS (
                SELECT 1
                FROM knowledge.knowledge_chunk_skills AS filter_map
                WHERE filter_map.chunk_id = c.chunk_id AND filter_map.skill_id = %s
            )
        """
        parameters.append(skill_id)
    parameters.extend([vector, limit])

    query = f"""
        SELECT c.chunk_id,
               COALESCE(NULLIF(c.metadata->>'page_title', ''), s.title) AS page_title,
               c.topic,
               s.source_url,
               string_agg(DISTINCT skill.skill_name, ', ' ORDER BY skill.skill_name) AS skills,
               round((1 - (c.{embedding_column} <=> %s::vector))::numeric, 4) AS similarity,
               left(c.content, 700) AS excerpt
        FROM knowledge.knowledge_chunks AS c
        JOIN knowledge.knowledge_sources AS s ON s.source_id = c.source_id
        LEFT JOIN knowledge.knowledge_chunk_skills AS chunk_map ON chunk_map.chunk_id = c.chunk_id
        LEFT JOIN core.skills AS skill ON skill.skill_id = chunk_map.skill_id
        WHERE c.{embedding_column} IS NOT NULL
          AND c.{model_column} = %s
          {skill_filter}
        GROUP BY c.chunk_id, s.source_id
        ORDER BY c.{embedding_column} <=> %s::vector
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(query, parameters)
        return cursor.fetchall()


def _print_results(rows: list[tuple[Any, ...]], skill_label: str | None) -> None:
    print("Semantic search results")
    print(f"Skill filter: {skill_label or 'none'}")
    if not rows:
        print("No embedded chunks matched the search.")
        return
    for rank, (chunk_id, title, topic, source_url, skills, score, excerpt) in enumerate(rows, 1):
        print(f"\n{rank}. {title or '(untitled)'} | similarity {score}")
        print(f"   Chunk: {chunk_id} | Topic: {topic or '(no topic)'}")
        print(f"   Skills: {skills or '(unmapped)'}")
        print(f"   Source: {source_url or '(no URL)'}")
        print(f"   {excerpt.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Natural-language search question")
    parser.add_argument("--skill", help="Optional canonical skill name or alias to filter results")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of chunks to show (default: 5)")
    parser.add_argument("--provider", choices=("gemini", "nova"), default="gemini",
                        help="Embedding provider to search (default: gemini)")
    args = parser.parse_args()
    if not args.query.strip():
        parser.error("--query cannot be empty")
    if args.limit < 1 or args.limit > 50:
        parser.error("--limit must be between 1 and 50")

    try:
        load_dotenv(REPOSITORY_ROOT / ".env")
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        client = create_nova_embedding_client(region) if args.provider == "nova" else create_gemini_client()
        try:
            query_vector = _embed_query(client, args.query, args.provider)
        finally:
            client.close()
        with get_database_connection() as connection:
            skill_id = None
            canonical_skill = None
            if args.skill:
                skill_id, canonical_skill = _resolve_skill(connection, args.skill)
            results = _search(connection, query_vector, args.limit, skill_id, args.provider)
        _print_results(results, canonical_skill)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
