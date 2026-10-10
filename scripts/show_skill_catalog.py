"""Browse the current skill catalog in PostgreSQL without changing it.

Examples:
    python -m scripts.show_skill_catalog
    python -m scripts.show_skill_catalog --search "machine learning"
    python -m scripts.show_skill_catalog --status provisional --sort jobs
    python -m scripts.show_skill_catalog --category database --format csv --output skills.csv
    python -m scripts.show_skill_catalog --list-categories
"""

import argparse
import csv
import sys
from pathlib import Path

from src.load.database import get_database_connection
from src.skills.normalizer import skill_name_key


def _load_catalog() -> list[dict[str, object]]:
    """Load canonical skills, aliases, and linked-posting counts using SELECTs only."""
    with get_database_connection() as connection:
        records = connection.execute(
            """
            SELECT s.skill_id,
                   s.skill_name,
                   s.skill_category,
                   s.catalog_status,
                   COALESCE(
                       ARRAY_AGG(DISTINCT a.alias)
                           FILTER (WHERE a.alias IS NOT NULL),
                       ARRAY[]::text[]
                   ) AS aliases,
                   COUNT(DISTINCT js.job_id) AS job_count
            FROM core.skills AS s
            LEFT JOIN core.skill_aliases AS a ON a.skill_id = s.skill_id
            LEFT JOIN market.job_skills AS js ON js.skill_id = s.skill_id
            GROUP BY s.skill_id, s.skill_name, s.skill_category, s.catalog_status
            ORDER BY LOWER(s.skill_name), s.skill_name
            """
        ).fetchall()

    return [
        {
            "skill_id": int(skill_id),
            "skill_name": str(skill_name),
            "skill_category": str(skill_category or ""),
            "catalog_status": str(catalog_status or ""),
            "aliases": sorted(
                (str(alias) for alias in aliases), key=lambda value: (value.casefold(), value)
            ),
            "job_count": int(job_count),
        }
        for skill_id, skill_name, skill_category, catalog_status, aliases, job_count in records
    ]


def _filter_catalog(
    rows: list[dict[str, object]], arguments: argparse.Namespace
) -> list[dict[str, object]]:
    filtered = rows
    if arguments.search:
        query = skill_name_key(arguments.search)
        filtered = [
            row
            for row in filtered
            if query in skill_name_key(str(row["skill_name"]))
            or any(query in skill_name_key(alias) for alias in row["aliases"])
        ]
    if arguments.category:
        category_key = skill_name_key(arguments.category)
        filtered = [
            row
            for row in filtered
            if skill_name_key(str(row["skill_category"])) == category_key
        ]
    if arguments.status:
        status_key = skill_name_key(arguments.status)
        filtered = [
            row
            for row in filtered
            if skill_name_key(str(row["catalog_status"])) == status_key
        ]
    if arguments.min_jobs is not None:
        filtered = [row for row in filtered if int(row["job_count"]) >= arguments.min_jobs]

    if arguments.sort == "jobs":
        filtered.sort(
            key=lambda row: (
                -int(row["job_count"]),
                skill_name_key(str(row["skill_name"])),
                int(row["skill_id"]),
            )
        )
    else:
        filtered.sort(
            key=lambda row: (
                skill_name_key(str(row["skill_name"])),
                int(row["skill_id"]),
            )
        )
    if arguments.limit is not None:
        filtered = filtered[: arguments.limit]
    return filtered


def _write_csv(rows: list[dict[str, object]], output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
    destination = output.open("w", encoding="utf-8-sig", newline="") if output else sys.stdout
    try:
        writer = csv.DictWriter(
            destination,
            fieldnames=[
                "skill_id",
                "skill_name",
                "skill_category",
                "catalog_status",
                "job_count",
                "aliases",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "aliases": "; ".join(row["aliases"])})
    finally:
        if output:
            destination.close()


def _print_catalog(rows: list[dict[str, object]], total: int, *, show_aliases: bool) -> None:
    print(f"Current DB catalog: {total} canonical skills; showing {len(rows)}")
    for row in rows:
        category = str(row["skill_category"]) or "(no category)"
        status = str(row["catalog_status"]) or "(no status)"
        print(
            f"[{row['skill_id']}] {row['skill_name']} | {category} | {status} | "
            f"jobs={row['job_count']}"
        )
        aliases = row["aliases"]
        if show_aliases and aliases:
            print(f"    aliases ({len(aliases)}): {'; '.join(aliases)}")


def _print_categories(rows: list[dict[str, object]]) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        category = str(row["skill_category"]) or "(no category)"
        counts[category] = counts.get(category, 0) + 1
    print(f"Catalog categories ({len(rows)} skills):")
    for category, count in sorted(counts.items(), key=lambda item: item[0].casefold()):
        print(f"{category}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--search", help="Case-insensitive substring in canonical names or aliases")
    parser.add_argument("--category", help="Show only one exact category")
    parser.add_argument("--status", help="Show only one catalog status, such as approved or provisional")
    parser.add_argument("--min-jobs", type=int, help="Require at least this many linked postings")
    parser.add_argument("--limit", type=int, help="Show at most this many skills")
    parser.add_argument("--sort", choices=("name", "jobs"), default="name")
    parser.add_argument("--format", choices=("text", "csv"), default="text")
    parser.add_argument("--output", type=Path, help="Write CSV to this path (requires --format csv)")
    parser.add_argument("--list-categories", action="store_true", help="List category names and counts")
    parser.add_argument("--hide-aliases", action="store_true", help="Hide aliases in text output")
    arguments = parser.parse_args()

    if arguments.min_jobs is not None and arguments.min_jobs < 0:
        parser.error("--min-jobs must be zero or greater")
    if arguments.limit is not None and arguments.limit < 1:
        parser.error("--limit must be at least 1")
    if arguments.output and arguments.format != "csv":
        parser.error("--output requires --format csv")

    try:
        catalog = _load_catalog()
    except Exception as error:
        parser.error(f"Could not read the current DB skill catalog: {error}")

    if arguments.list_categories:
        _print_categories(catalog)
        return

    rows = _filter_catalog(catalog, arguments)
    if arguments.format == "csv":
        try:
            _write_csv(rows, arguments.output)
        except OSError as error:
            parser.error(f"Could not write CSV output: {error}")
        if arguments.output:
            print(f"Exported {len(rows)} skills to {arguments.output}")
        return

    _print_catalog(rows, len(catalog), show_aliases=not arguments.hide_aliases)


if __name__ == "__main__":
    main()
