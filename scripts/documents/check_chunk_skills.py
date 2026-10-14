"""Read-only check of chunk skill labels against the canonical database catalog."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

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


def _read_chunk_skill_counts(path: Path) -> tuple[int, Counter[str]]:
    chunk_count = 0
    skill_counts: Counter[str] = Counter()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON on line {line_number}: {error.msg}") from error
        chunk_count += 1
        skills = record.get("skills", [])
        if not isinstance(skills, list):
            continue
        # Count chunks per skill, rather than duplicate mentions in one chunk.
        skill_counts.update({skill.strip() for skill in skills if isinstance(skill, str) and skill.strip()})
    return chunk_count, skill_counts


def _load_catalog_matches(skill_names: list[str]) -> dict[str, dict[str, Any]]:
    normalized_names = sorted({name.casefold() for name in skill_names})
    if not normalized_names:
        return {}

    query = """
        SELECT lower(skill_name) AS label, skill_id, skill_name AS canonical_skill, 'exact' AS match_type
        FROM core.skills
        WHERE lower(skill_name) = ANY(%s)
        UNION ALL
        SELECT lower(a.alias) AS label, s.skill_id, s.skill_name AS canonical_skill, 'alias' AS match_type
        FROM core.skill_aliases AS a
        JOIN core.skills AS s ON s.skill_id = a.skill_id
        WHERE lower(a.alias) = ANY(%s)
    """
    matches: dict[str, dict[str, Any]] = {}
    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (normalized_names, normalized_names))
            for label, skill_id, canonical_skill, match_type in cursor.fetchall():
                current = matches.get(label)
                # Prefer an exact canonical-name match if both forms exist.
                if current is None or match_type == "exact":
                    matches[label] = {
                        "skill_id": skill_id,
                        "canonical_skill": canonical_skill,
                        "match_type": match_type,
                    }
    return matches


def _render_table(report: dict[str, Any]) -> str:
    summary = report["matches"]
    lines = [
        "Chunk skill catalog check",
        f"Input: {report['input']}",
        f"Chunks scanned: {report['chunks']} | Unique skill labels: {report['unique_document_skills']}",
        f"Matches: exact {summary['exact']} | alias {summary['alias']} | missing {summary['missing']}",
        "",
    ]
    headers = ["MATCH", "SKILL ID", "SKILL IN CHUNKS", "CANONICAL SKILL", "CHUNKS"]
    table_rows = []
    for item in report["skills"]:
        table_rows.append([
            item["match_type"].upper(),
            str(item["skill_id"] or "-"),
            item["document_skill"],
            item["canonical_skill"] or "-",
            str(item["chunks"]),
        ])

    widths = [
        max([len(header), *(len(row[index]) for row in table_rows)])
        for index, header in enumerate(headers)
    ]

    def format_row(row: list[str]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    lines.extend([
        format_row(headers),
        "-+-".join("-" * width for width in widths),
        *(format_row(row) for row in table_rows),
        "",
        "MATCH legend: EXACT = canonical name | ALIAS = matched alias | MISSING = no catalog match",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Combined chunks JSONL to check")
    parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format (default: table)")
    args = parser.parse_args()

    try:
        chunk_count, skill_counts = _read_chunk_skill_counts(args.input)
        catalog_matches = _load_catalog_matches(list(skill_counts))
        result = []
        for skill_name in sorted(skill_counts, key=str.casefold):
            match = catalog_matches.get(skill_name.casefold())
            result.append({
                "document_skill": skill_name,
                "chunks": skill_counts[skill_name],
                "match_type": match["match_type"] if match else "missing",
                "skill_id": match["skill_id"] if match else None,
                "canonical_skill": match["canonical_skill"] if match else None,
            })

        report = {
            "input": str(args.input),
            "chunks": chunk_count,
            "unique_document_skills": len(skill_counts),
            "matches": {
                "exact": sum(row["match_type"] == "exact" for row in result),
                "alias": sum(row["match_type"] == "alias" for row in result),
                "missing": sum(row["match_type"] == "missing" for row in result),
            },
            "skills": result,
        }
        if args.format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(_render_table(report))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
