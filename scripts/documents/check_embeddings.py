"""Read-only summary of stored Gemini and optional Nova knowledge embeddings."""

from src.shared.llm.gemini_embedding_client import DIMENSIONS as GEMINI_DIMENSIONS, MODEL_ID as GEMINI_MODEL_ID

from src.shared.db.database import get_database_connection

EXPECTED_MODEL = "amazon.nova-2-multimodal-embeddings-v1:0"
EXPECTED_DIMENSIONS = 1024


def main() -> None:
    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) AS total_chunks,
                       count(*) FILTER (WHERE embedding IS NOT NULL) AS gemini_embedded,
                       count(*) FILTER (WHERE embedding IS NULL) AS gemini_pending,
                       count(*) FILTER (
                           WHERE embedding IS NOT NULL
                             AND embedding_model IS DISTINCT FROM %s
                       ) AS gemini_unexpected_model,
                       count(*) FILTER (
                           WHERE embedding IS NOT NULL
                             AND vector_dims(embedding) <> %s
                       ) AS gemini_unexpected_dimensions,
                       count(*) FILTER (WHERE embedding_nova IS NOT NULL) AS embedded_chunks,
                       count(*) FILTER (WHERE embedding_nova IS NULL) AS pending_chunks,
                       count(*) FILTER (WHERE embedding IS NOT NULL) AS legacy_gemini_chunks,
                       count(*) FILTER (
                           WHERE embedding_nova IS NOT NULL
                             AND embedding_nova_model IS DISTINCT FROM %s
                       ) AS unexpected_model,
                       count(*) FILTER (
                           WHERE embedding_nova IS NOT NULL
                             AND vector_dims(embedding_nova) <> %s
                       ) AS unexpected_dimensions
                FROM knowledge.knowledge_chunks
                """,
                (GEMINI_MODEL_ID, GEMINI_DIMENSIONS, EXPECTED_MODEL, EXPECTED_DIMENSIONS),
            )
            (total, gemini_embedded, gemini_pending, gemini_wrong_model, gemini_wrong_dimensions,
             nova_embedded, nova_pending, legacy, nova_wrong_model, nova_wrong_dimensions) = cursor.fetchone()

            cursor.execute(
                """
                SELECT embedding_nova_model, vector_dims(embedding_nova), count(*)
                FROM knowledge.knowledge_chunks
                WHERE embedding_nova IS NOT NULL
                GROUP BY embedding_nova_model, vector_dims(embedding_nova)
                ORDER BY embedding_nova_model, vector_dims(embedding_nova)
                """
            )
            groups = cursor.fetchall()

    gemini_complete = (total > 0 and gemini_embedded == total and gemini_pending == 0
                       and gemini_wrong_model == 0 and gemini_wrong_dimensions == 0)
    nova_complete = (total > 0 and nova_embedded == total and nova_pending == 0
                     and nova_wrong_model == 0 and nova_wrong_dimensions == 0)

    print("Knowledge embedding check (read-only)")
    print(f"Total chunks: {total}")
    print(f"Gemini vectors ({GEMINI_MODEL_ID}, {GEMINI_DIMENSIONS} dimensions): {gemini_embedded} complete / {gemini_pending} pending")
    print(f"Gemini unexpected model/dimensions: {gemini_wrong_model}/{gemini_wrong_dimensions}")
    print(f"Nova vectors ({EXPECTED_MODEL}, {EXPECTED_DIMENSIONS} dimensions): {nova_embedded} complete / {nova_pending} pending")
    print(f"Nova unexpected model/dimensions: {nova_wrong_model}/{nova_wrong_dimensions}")
    print(f"Legacy Gemini vectors retained: {legacy}")
    print("Stored optional Bedrock vector groups:")
    if groups:
        for model, dimensions, count in groups:
            print(f"  - {model or '(model missing)'} | {dimensions} dimensions | {count} vectors")
    else:
        print("  - none")
    print(f"Gemini result: {'PASS' if gemini_complete else 'INCOMPLETE'}")
    print(f"Nova result: {'PASS' if nova_complete else 'INCOMPLETE'}")


if __name__ == "__main__":
    main()
