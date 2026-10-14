"""Preview or load reviewed document chunks into the knowledge schema."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from psycopg.types.json import Jsonb

from src.shared.db.database import get_database_connection

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "documents"
    / "chunks"
    / "combined"
    / "all-careers-approved-pages-20261014-chunks.jsonl"
)


def _read_chunks(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON on line {line_number}: {error.msg}") from error
        if not isinstance(record, dict):
            raise ValueError(f"Expected a JSON object on line {line_number}")

        source_url = record.get("canonical_url") or record.get("source_url")
        if not isinstance(source_url, str) or not source_url.strip():
            raise ValueError(f"Missing canonical_url/source_url on line {line_number}")
        if not isinstance(record.get("chunk_index"), int) or record["chunk_index"] < 0:
            raise ValueError(f"Invalid chunk_index on line {line_number}")
        if not isinstance(record.get("content"), str) or not record["content"].strip():
            raise ValueError(f"Missing chunk content on line {line_number}")
        if not isinstance(record.get("skills", []), list):
            raise ValueError(f"Expected skills to be a list on line {line_number}")

        record["canonical_url"] = source_url.strip()
        chunks.append(record)

    if not chunks:
        raise ValueError("Input contains no chunks")

    seen: set[tuple[str, int]] = set()
    for record in chunks:
        key = (record["canonical_url"], record["chunk_index"])
        if key in seen:
            raise ValueError(f"Duplicate source URL and chunk_index: {key[0]} #{key[1]}")
        seen.add(key)
    return chunks


def _load_skill_catalog(connection: Any) -> dict[str, dict[str, Any]]:
    query = """
        SELECT s.skill_id, s.skill_name, s.skill_name AS label, true AS is_canonical
        FROM core.skills AS s
        UNION ALL
        SELECT s.skill_id, s.skill_name, a.alias AS label, false AS is_canonical
        FROM core.skill_aliases AS a
        JOIN core.skills AS s ON s.skill_id = a.skill_id
    """
    labels: dict[str, dict[str, Any]] = {}
    with connection.cursor() as cursor:
        cursor.execute(query)
        for skill_id, canonical_name, label, is_canonical in cursor.fetchall():
            key = label.strip().casefold()
            current = labels.get(key)
            if current is None or is_canonical:
                labels[key] = {
                    "skill_id": skill_id,
                    "canonical_name": canonical_name,
                    "is_canonical": is_canonical,
                }
            elif not current.get("is_canonical") and current["skill_id"] != skill_id:
                labels[key] = {"ambiguous": True, "label": label}
    return labels


def _resolve_chunk_skills(
    chunks: list[dict[str, Any]], catalog: dict[str, dict[str, Any]]
) -> tuple[dict[tuple[str, int], list[int]], set[str]]:
    resolved: dict[tuple[str, int], list[int]] = {}
    missing: set[str] = set()
    for record in chunks:
        skill_ids: set[int] = set()
        for raw_name in record.get("skills", []):
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            name = raw_name.strip()
            match = catalog.get(name.casefold())
            if match is None or match.get("ambiguous"):
                missing.add(name)
                continue
            skill_ids.add(match["skill_id"])
        resolved[(record["canonical_url"], record["chunk_index"])] = sorted(skill_ids)
    return resolved, missing


def _chunk_metadata(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_url": record["canonical_url"],
        "source_url": record.get("source_url"),
        "source_config_id": record.get("source_config_id"),
        "page_title": record.get("page_title"),
        "career_tracks": record.get("career_tracks", []),
        "heading_path": record.get("heading_path", []),
        "content_hash": record.get("content_hash"),
        "word_count": record.get("word_count"),
        "review_flags": record.get("review_flags", []),
    }


def _report_preview(
    input_path: Path,
    chunks: list[dict[str, Any]],
    skill_links: dict[tuple[str, int], list[int]],
    missing: set[str],
) -> None:
    pages = {row["canonical_url"] for row in chunks}
    links = sum(len(skill_ids) for skill_ids in skill_links.values())
    print("Knowledge chunk load preview")
    print(f"Input: {input_path}")
    print(f"Source pages: {len(pages)}")
    print(f"Chunks: {len(chunks)}")
    print(f"Chunk-to-skill links: {links}")
    print(f"Unmatched/ambiguous skill labels: {len(missing)}")
    if missing:
        for name in sorted(missing, key=str.casefold):
            print(f"  - {name}")


def _persist_chunks(
    connection: Any,
    chunks: list[dict[str, Any]],
    skill_links: dict[tuple[str, int], list[int]],
) -> tuple[int, int, int]:
    pages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in chunks:
        pages[record["canonical_url"]].append(record)

    source_count = 0
    chunk_count = 0
    link_count = 0
    for source_url, page_chunks in pages.items():
        first = page_chunks[0]
        parsed = urlparse(source_url)
        publisher = parsed.hostname or None
        title = first.get("page_title") or source_url

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_id
                FROM knowledge.knowledge_sources
                WHERE source_url = %s
                ORDER BY source_id
                """,
                (source_url,),
            )
            matching_sources = cursor.fetchall()
            if len(matching_sources) > 1:
                raise ValueError(f"Multiple knowledge_sources rows use URL {source_url}")
            if matching_sources:
                source_id = matching_sources[0][0]
                cursor.execute(
                    """
                    UPDATE knowledge.knowledge_sources
                    SET title = %s, publisher = %s, source_type = 'html',
                        is_active = true, updated_at = now()
                    WHERE source_id = %s
                    """,
                    (title, publisher, source_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO knowledge.knowledge_sources
                        (source_type, title, source_url, publisher)
                    VALUES ('html', %s, %s, %s)
                    RETURNING source_id
                    """,
                    (title, source_url, publisher),
                )
                source_id = cursor.fetchone()[0]
            source_count += 1

            for record in page_chunks:
                key = (source_url, record["chunk_index"])
                cursor.execute(
                    """
                    INSERT INTO knowledge.knowledge_chunks
                        (source_id, topic, chunk_index, content, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_id, chunk_index) DO UPDATE SET
                        topic = EXCLUDED.topic,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding_model = CASE
                            WHEN knowledge.knowledge_chunks.content IS DISTINCT FROM EXCLUDED.content
                            THEN NULL ELSE knowledge.knowledge_chunks.embedding_model END,
                        embedding = CASE
                            WHEN knowledge.knowledge_chunks.content IS DISTINCT FROM EXCLUDED.content
                            THEN NULL ELSE knowledge.knowledge_chunks.embedding END
                    RETURNING chunk_id
                    """,
                    (
                        source_id,
                        record.get("topic"),
                        record["chunk_index"],
                        record["content"],
                        Jsonb(_chunk_metadata(record)),
                    ),
                )
                chunk_id = cursor.fetchone()[0]
                chunk_count += 1

                cursor.execute(
                    "DELETE FROM knowledge.knowledge_chunk_skills WHERE chunk_id = %s",
                    (chunk_id,),
                )
                ids = skill_links[key]
                if ids:
                    cursor.executemany(
                        """
                        INSERT INTO knowledge.knowledge_chunk_skills (chunk_id, skill_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        [(chunk_id, skill_id) for skill_id in ids],
                    )
                    link_count += len(ids)

            current_indexes = [record["chunk_index"] for record in page_chunks]
            cursor.execute(
                """
                DELETE FROM knowledge.knowledge_chunks
                WHERE source_id = %s AND NOT (chunk_index = ANY(%s))
                """,
                (source_id, current_indexes),
            )

    return source_count, chunk_count, link_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Combined chunks JSONL")
    parser.add_argument("--apply", action="store_true", help="Persist changes; default is a read-only preview")
    args = parser.parse_args()

    try:
        chunks = _read_chunks(args.input)
        with get_database_connection() as connection:
            catalog = _load_skill_catalog(connection)
            resolved, missing = _resolve_chunk_skills(chunks, catalog)
            _report_preview(args.input, chunks, resolved, missing)
            if missing:
                raise ValueError("Resolve all unmatched or ambiguous skill labels before loading")
            if not args.apply:
                print("No database rows were changed. Re-run with --apply to load these chunks.")
                return

            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('knowledge.knowledge_chunk_skills')")
                if cursor.fetchone()[0] is None:
                    raise ValueError("Migration 013 is not applied yet; run the database migration command first")

            with connection.transaction():
                counts = _persist_chunks(connection, chunks, resolved)
            print("Database load complete")
            print(f"Source records processed: {counts[0]}")
            print(f"Chunks upserted: {counts[1]}")
            print(f"Chunk-to-skill links written: {counts[2]}")
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
