"""Browse the proposed skill-catalog decisions waiting for rebuild/apply.

This script reads the saved preview CSV only. It does not query or change the DB.

Examples:
    python -m scripts.market.show_skill_catalog_preview
    python -m scripts.market.show_skill_catalog_preview --status pending_review
    python -m scripts.market.show_skill_catalog_preview --search "machine learning"
    python -m scripts.market.show_skill_catalog_preview --format csv --output proposed_skills.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from src.shared.skill_normalization.normalizer import skill_name_key


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREVIEW = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "skill_candidates"
    / "catalog_rebuild_preview.csv"
)

PLAN_STATUSES = (
    "auto_create",
    "auto_map",
    "create_new",
    "map_existing",
    "split_into_skills",
    "pending_review",
    "ignore",
)


def _parse_json_list(value: str, *, field: str, candidate: str) -> list[object]:
    if not value.strip():
        return []
    parsed: object = value
    while isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid {field} JSON for {candidate!r}: {error}") from error
    if not isinstance(parsed, list):
        raise ValueError(f"{field} for {candidate!r} must be a JSON list")
    return parsed


def _load_plan(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(f"Preview CSV not found: {path}")
    csv.field_size_limit(min(sys.maxsize, 2_147_483_647))
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    plan: list[dict[str, object]] = []
    for row in rows:
        candidate = row.get("candidate_name", "").strip()
        decision = row.get("review_decision", "").strip()
        suggestion = row.get("suggestion_decision", "").strip()
        confidence = row.get("confidence_level", "").strip()
        preview_status = row.get("preview_status", "").strip()
        canonical = ""
        category = ""
        details = ""

        if decision == "create_new":
            action = "create_new"
            canonical = row.get("canonical_skill_name", "").strip()
            category = row.get("skill_category", "").strip()
        elif decision == "map_existing":
            action = "map_existing"
            canonical = row.get("canonical_skill_name", "").strip()
            category = row.get("skill_category", "").strip()
        elif decision == "split_into_skills":
            action = "split_into_skills"
            members = _parse_json_list(
                row.get("split_skills", "[]"), field="split_skills", candidate=candidate
            )
            details = json.dumps(members, ensure_ascii=False)
        elif decision == "ignore":
            action = "ignore"
        elif preview_status == "ready_for_approval" and confidence == "high":
            if suggestion == "new_skill":
                action = "auto_create"
                canonical = row.get("suggested_skill_name", "").strip()
                category = row.get("suggested_skill_category", "").strip()
            elif suggestion == "existing_skill":
                action = "auto_map"
                canonical = row.get("suggested_skill_name", "").strip()
                category = row.get("suggested_skill_category", "").strip()
            else:
                action = "pending_review"
        else:
            action = "pending_review"

        plan.append(
            {
                "candidate_name": candidate,
                "observed_names": "; ".join(
                    str(value)
                    for value in _parse_json_list(
                        row.get("observed_names", "[]"),
                        field="observed_names",
                        candidate=candidate,
                    )
                ),
                "plan_action": action,
                "target_skill_name": canonical,
                "skill_category": category,
                "confidence_level": confidence,
                "job_count": row.get("job_count", ""),
                "preview_status": preview_status,
                "suggestion_decision": suggestion,
                "possible_existing_skill": row.get("possible_existing_skill", ""),
                "existing_database_matches": row.get("existing_database_matches", ""),
                "similar_database_skills": row.get("similar_database_skills", ""),
                "possible_duplicate_candidates": row.get("possible_duplicate_candidates", ""),
                "example_job_titles": row.get("example_job_titles", ""),
                "example_evidence": row.get("example_evidence", ""),
                "suggestion_reason": row.get("suggestion_reason", ""),
                "split_members": details,
            }
        )
    return plan


def _filter_plan(
    rows: list[dict[str, object]], arguments: argparse.Namespace
) -> list[dict[str, object]]:
    result = rows
    if arguments.status != "all":
        result = [row for row in result if row["plan_action"] == arguments.status]
    if arguments.search:
        query = skill_name_key(arguments.search)
        result = [
            row
            for row in result
            if query in skill_name_key(str(row["candidate_name"]))
            or query in skill_name_key(str(row["target_skill_name"]))
            or query in skill_name_key(str(row["observed_names"]))
        ]
    result.sort(
        key=lambda row: (
            skill_name_key(str(row["candidate_name"])),
            str(row["plan_action"]),
        )
    )
    if arguments.limit is not None:
        result = result[: arguments.limit]
    return result


def _write_csv(rows: list[dict[str, object]], output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
    destination = output.open("w", encoding="utf-8-sig", newline="") if output else sys.stdout
    try:
        fields = list(rows[0].keys()) if rows else [
            "candidate_name",
            "plan_action",
            "target_skill_name",
            "skill_category",
            "confidence_level",
            "job_count",
        ]
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if output:
            destination.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--search", help="Search candidate or proposed canonical name")
    parser.add_argument(
        "--status",
        choices=("all", *PLAN_STATUSES),
        default="all",
        help="Filter by planned action (default: all)",
    )
    parser.add_argument("--limit", type=int, help="Show at most this many rows")
    parser.add_argument("--format", choices=("text", "csv"), default="text")
    parser.add_argument("--output", type=Path, help="Write CSV to this path (requires --format csv)")
    arguments = parser.parse_args()
    if arguments.limit is not None and arguments.limit < 1:
        parser.error("--limit must be at least 1")
    if arguments.output and arguments.format != "csv":
        parser.error("--output requires --format csv")

    try:
        full_plan = _load_plan(arguments.preview)
    except (FileNotFoundError, ValueError, OSError) as error:
        parser.error(str(error))
    rows = _filter_plan(full_plan, arguments)

    if arguments.format == "csv":
        try:
            _write_csv(rows, arguments.output)
        except OSError as error:
            parser.error(f"Could not write CSV output: {error}")
        if arguments.output:
            print(f"Exported {len(rows)} preview decisions to {arguments.output}")
        return

    counts = {status: 0 for status in PLAN_STATUSES}
    for row in full_plan:
        counts[str(row["plan_action"])] += 1
    print(f"Rebuild preview: {len(full_plan)} candidates; no DB access or writes")
    print("Planned actions: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    print(f"Showing {len(rows)} rows from {arguments.preview}")
    for row in rows:
        target = str(row["target_skill_name"])
        detail = f" -> {target}" if target else ""
        category = f" [{row['skill_category']}]" if row["skill_category"] else ""
        print(
            f"{row['plan_action']}: {row['candidate_name']}{detail}{category} | "
            f"confidence={row['confidence_level'] or '-'} | jobs={row['job_count'] or '-'}"
        )
        if row["existing_database_matches"]:
            print(f"    DB exact match: {row['existing_database_matches']}")
        if row["similar_database_skills"]:
            print(f"    DB similar: {row['similar_database_skills']}")
        if row["possible_duplicate_candidates"]:
            print(f"    Possible duplicate candidates: {row['possible_duplicate_candidates']}")
        if row["suggestion_reason"]:
            print(f"    Reason: {row['suggestion_reason']}")
        if row["split_members"]:
            print(f"    Split components: {row['split_members']}")
    print("These are preview decisions, not a confirmation that apply has succeeded.")


if __name__ == "__main__":
    main()
