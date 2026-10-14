"""Read-only summary of stored knowledge chunk embeddings."""

from src.shared.db.database import get_database_connection

EXPECTED_MODEL = "gemini-embedding-2"
EXPECTED_DIMENSIONS = 768


def main() -> None:
    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) AS total_chunks,
                       count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded_chunks,
                       count(*) FILTER (WHERE embedding IS NULL) AS pending_chunks,
                       count(*) FILTER (
                           WHERE embedding IS NOT NULL
                             AND embedding_model IS DISTINCT FROM %s
                       ) AS unexpected_model,
                       count(*) FILTER (
                           WHERE embedding IS NOT NULL
                             AND vector_dims(embedding) <> %s
                       ) AS unexpected_dimensions
                FROM knowledge.knowledge_chunks
                """,
                (EXPECTED_MODEL, EXPECTED_DIMENSIONS),
            )
            total, embedded, pending, wrong_model, wrong_dimensions = cursor.fetchone()

            cursor.execute(
                """
                SELECT embedding_model, vector_dims(embedding), count(*)
                FROM knowledge.knowledge_chunks
                WHERE embedding IS NOT NULL
                GROUP BY embedding_model, vector_dims(embedding)
                ORDER BY embedding_model, vector_dims(embedding)
                """
            )
            groups = cursor.fetchall()

    complete = (
        total > 0
        and embedded == total
        and pending == 0
        and wrong_model == 0
        and wrong_dimensions == 0
    )

    print("Knowledge embedding check (read-only)")
    print(f"Total chunks: {total}")
    print(f"With embeddings: {embedded}")
    print(f"Still pending: {pending}")
    print(f"Unexpected model: {wrong_model}")
    print(f"Unexpected dimensions: {wrong_dimensions}")
    print("Stored vector groups:")
    if groups:
        for model, dimensions, count in groups:
            print(f"  - {model or '(model missing)'} | {dimensions} dimensions | {count} vectors")
    else:
        print("  - none")
    print(f"Result: {'PASS' if complete else 'INCOMPLETE'}")


if __name__ == "__main__":
    main()
