"""Interactively review the global skill-catalog preview CSV."""

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

from src.skills.catalog_rebuild_preview import (
    add_database_catalog_comparison,
    audit_skill_catalog_names,
    load_bootstrap_catalog,
)
from src.skills.normalizer import load_skill_catalog, skill_name_key
from src.load.database import get_database_connection


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "skill_candidates"
    / "catalog_rebuild_preview.csv"
)
REVIEW_COLUMNS = (
    "review_decision",
    "canonical_skill_name",
    "skill_category",
    "split_skills",
    "existing_database_matches",
    "similar_database_skills",
)


def _save_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _print_catalog_name_audit() -> None:
    """Print suspicious aliases and verified-acronym canonical duplicates."""
    with get_database_connection() as connection:
        skills = [
            (int(skill_id), str(name), category, int(job_count))
            for skill_id, name, category, job_count in connection.execute(
                """
                SELECT s.skill_id, s.skill_name, s.skill_category,
                       COUNT(DISTINCT js.job_id)
                FROM core.skills s
                LEFT JOIN market.job_skills js ON js.skill_id = s.skill_id
                GROUP BY s.skill_id, s.skill_name, s.skill_category
                ORDER BY s.skill_name
                """
            ).fetchall()
        ]
        aliases = [
            (int(alias_id), str(alias), str(name), int(job_count))
            for alias_id, alias, name, job_count in connection.execute(
                """
                SELECT a.alias_id, a.alias, s.skill_name,
                       COUNT(DISTINCT js.job_id)
                FROM core.skill_aliases a
                JOIN core.skills s ON s.skill_id = a.skill_id
                LEFT JOIN market.job_skills js
                  ON js.skill_id = a.skill_id
                 AND lower(trim(js.raw_skill_name)) = lower(trim(a.alias))
                GROUP BY a.alias_id, a.alias, s.skill_name
                ORDER BY a.alias
                """
            ).fetchall()
        ]
    report = audit_skill_catalog_names(skills, aliases)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Read-only audit: no catalog, alias, or job-skill rows were changed.")


def _choose_new_name(row: dict[str, str]) -> str:
    candidate_name = row.get("candidate_name", "").strip()
    suggested_name = row.get("suggested_skill_name", "").strip()
    if suggested_name and suggested_name != candidate_name:
        print(
            f"1=use candidate name [{candidate_name}], "
            f"2=use LLM name [{suggested_name}], 3=type a custom name"
        )
        choice = input("Name choice: ").strip()
        if choice == "1":
            return candidate_name
        if choice == "2":
            return suggested_name
        if choice == "3":
            return input("Custom canonical name: ").strip()
        return ""

    default_name = candidate_name or suggested_name
    print(f"1=use candidate name [{default_name}], 2=type a custom name")
    choice = input("Name choice: ").strip()
    if choice == "1":
        return candidate_name or suggested_name
    if choice == "2":
        return input("Custom canonical name: ").strip()
    return ""


def _print_catalog(
    catalog: dict[str, dict[str, object]],
    bootstrap_catalog: dict[str, dict[str, object]],
) -> None:
    database_canonical = {
        str(item["skill_name"]): item
        for item in catalog.values()
        if item.get("match_method") == "exact_canonical"
    }
    aliases_by_id: dict[int, list[str]] = {}
    for alias_key, item in catalog.items():
        if item.get("match_method") == "exact_alias":
            skill_id = int(item["skill_id"])
            aliases_by_id.setdefault(skill_id, []).append(alias_key)

    print(f"Current DB catalog: {len(database_canonical)} canonical skills")
    print("Canonical name | Category | Status | Bootstrap | Aliases")
    for name, item in sorted(database_canonical.items(), key=lambda pair: pair[0].casefold()):
        skill_id = int(item["skill_id"])
        in_bootstrap = any(
            skill_name_key(str(seed_item["skill_name"])) == skill_name_key(name)
            for seed_item in bootstrap_catalog.values()
            if seed_item.get("match_method") == "exact_canonical"
        )
        aliases = sorted(aliases_by_id.get(skill_id, []), key=str.casefold)
        print(
            f"{name} | {item.get('skill_category', '')} | "
            f"{item.get('catalog_status', 'approved')} | "
            f"{'yes' if in_bootstrap else 'no'} | {', '.join(aliases)}"
        )

    database_keys = {skill_name_key(name) for name in database_canonical}
    bootstrap_only = {
        str(item["skill_name"]): item
        for item in bootstrap_catalog.values()
        if item.get("match_method") == "exact_canonical"
        and skill_name_key(str(item["skill_name"])) not in database_keys
    }
    print(f"\nBootstrap-only canonical skills: {len(bootstrap_only)}")
    for name, item in sorted(bootstrap_only.items(), key=lambda pair: pair[0].casefold()):
        print(f"{name} | {item.get('skill_category', '')}")


def _print_saved_creations(
    report_path: Path, catalog: dict[str, dict[str, object]]
) -> None:
    """List manual create-new decisions saved in the preview, with DB status."""
    if not report_path.is_file():
        raise FileNotFoundError(f"Preview CSV not found: {report_path}")
    with report_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    creations: dict[str, dict[str, object]] = {}
    for row in rows:
        decision = row.get("review_decision", "").strip()
        if decision == "create_new":
            name = row.get("canonical_skill_name", "").strip()
            category = row.get("skill_category", "").strip()
            if name:
                item = creations.setdefault(
                    skill_name_key(name),
                    {"name": name, "category": category, "candidates": set()},
                )
                item["candidates"].add(row.get("candidate_name", "").strip())
        elif decision == "split_into_skills":
            try:
                members = json.loads(row.get("split_skills", "[]"))
            except json.JSONDecodeError:
                continue
            if not isinstance(members, list):
                continue
            for member in members:
                if not isinstance(member, dict) or member.get("decision") != "create_new":
                    continue
                name = str(member.get("skill_name", "")).strip()
                category = str(member.get("skill_category", "")).strip()
                if name:
                    item = creations.setdefault(
                        skill_name_key(name),
                        {"name": name, "category": category, "candidates": set()},
                    )
                    item["candidates"].add(row.get("candidate_name", "").strip())

    database_names = {
        skill_name_key(str(item["skill_name"]))
        for item in catalog.values()
        if item.get("match_method") == "exact_canonical"
    }
    print(f"Saved manual creations: {len(creations)}")
    print("Canonical name | Category | DB status | Candidate source")
    for key, item in sorted(
        creations.items(), key=lambda pair: str(pair[1]["name"]).casefold()
    ):
        db_status = "in DB" if key in database_names else "saved, not applied"
        candidates = ", ".join(sorted(item["candidates"], key=str.casefold))
        print(
            f"{item['name']} | {item['category']} | {db_status} | {candidates}"
        )


def _review_one(
    row: dict[str, str],
    row_number: int,
    canonical_names: set[str],
    categories: list[str],
) -> bool:
    """Review one row. Return False when the user asks to quit."""
    print("\n" + "=" * 88)
    print(f"Row {row_number}: {row.get('candidate_name', '')}")
    print(
        f"Observed: {row.get('observed_names', '')} | "
        f"jobs={row.get('job_count', '')} | occurrences={row.get('occurrence_count', '')}"
    )
    source_composites = _json_list(row.get("source_composite_names", ""))
    if source_composites:
        print(f"Split from composite labels: {source_composites}")
    print(
        f"LLM: {row.get('suggestion_decision', '')} -> "
        f"{row.get('suggested_skill_name', '')} "
        f"[{row.get('suggested_skill_category', '')}], "
        f"confidence={row.get('confidence_level', '')}"
    )
    print(f"Bootstrap match: {row.get('possible_existing_skill', '') or '(none)'}")
    print(
        "Exact current DB match: "
        f"{row.get('existing_database_matches', '') or '(none)'}"
    )
    print(
        "Similar current DB skills (name similarity only): "
        f"{row.get('similar_database_skills', '') or '(none)'}"
    )
    print(f"Possible preview duplicates: {row.get('possible_duplicate_candidates', '') or '(none)'}")
    print(f"Reason: {row.get('suggestion_reason', '') or '(no LLM suggestion yet)'}")
    for index, (title, evidence) in enumerate(
        zip(
            _json_list(row.get("example_job_titles", "")),
            _json_list(row.get("example_evidence", "")),
        ),
        start=1,
    ):
        print(f"Evidence {index} — {title}: {evidence}")
    current = row.get("review_decision", "")
    if current:
        print(
            f"Current decision: {current}; canonical={row.get('canonical_skill_name', '')}; "
            f"category={row.get('skill_category', '')}"
        )
    print("\n1=map existing, 2=create new, 3=ignore, 4=split into skills, Enter=skip, q=quit")
    choice = input("Decision: ").strip().lower()
    if choice == "q":
        return False
    if not choice:
        return True
    if choice == "1":
        print("Type an exact DB/bootstrap canonical or a canonical approved earlier in this CSV.")
        print("Enter ?text to search available canonical names.")
        canonical = input("Canonical name: ").strip()
        while canonical.startswith("?"):
            query = canonical[1:].strip().casefold()
            matches = [name for name in canonical_names if query in name.casefold()]
            print("Matches: " + (", ".join(sorted(matches, key=str.casefold)[:40]) or "(none)"))
            canonical = input("Canonical name: ").strip()
        if canonical not in canonical_names:
            print("Not saved: name is not an available DB/bootstrap/reviewed canonical.")
            return True
        row["review_decision"] = "map_existing"
        row["canonical_skill_name"] = canonical
        row["skill_category"] = ""
        row["split_skills"] = "[]"
    elif choice == "2":
        canonical = _choose_new_name(row)
        if not canonical:
            print("Not saved: choose a name option or enter a custom name.")
            return True
        if canonical.casefold() in {name.casefold() for name in canonical_names}:
            print("Not saved: this name already exists in the DB or bootstrap catalog; choose map-existing.")
            return True
        print("Categories: " + ", ".join(categories))
        default_category = row.get("suggested_skill_category", "").strip() or "other"
        category = input(f"Category [{default_category}]: ").strip() or default_category
        if category not in categories:
            print("Not saved: category must be one of the listed values.")
            return True
        row["review_decision"] = "create_new"
        row["canonical_skill_name"] = canonical
        row["skill_category"] = category
        row["split_skills"] = "[]"
    elif choice == "3":
        row["review_decision"] = "ignore"
        row["canonical_skill_name"] = ""
        row["skill_category"] = ""
        row["split_skills"] = "[]"
    elif choice == "4":
        while True:
            raw_count = input("How many skill components? (2–20, q=cancel): ").strip()
            if raw_count.casefold() == "q":
                print("Split cancelled; no decision was saved.")
                return True
            try:
                component_count = int(raw_count)
            except ValueError:
                print("Enter a whole number from 2 to 20, or q to cancel.")
                continue
            if 2 <= component_count <= 20:
                break
            print("A split needs between 2 and 20 skill components.")

        members: list[dict[str, str]] = []
        for component_index in range(1, component_count + 1):
            while True:
                print(
                    f"Component {component_index}/{component_count}: "
                    "1=map to existing, 2=create new, q=cancel split"
                )
                component_choice = input("Choice: ").strip().lower()
                if component_choice == "q":
                    print("Split cancelled; no decision was saved.")
                    return True
                if component_choice not in {"1", "2"}:
                    print("Choose 1, 2, or q.")
                    continue

                if component_choice == "1":
                    while True:
                        print("Type an exact canonical name, or enter ?text to search.")
                        skill_name = input("Existing canonical name: ").strip()
                        if skill_name.casefold() == "q":
                            print("Split cancelled; no decision was saved.")
                            return True
                        if skill_name.startswith("?"):
                            query = skill_name[1:].strip().casefold()
                            matches = [
                                name for name in canonical_names if query in name.casefold()
                            ]
                            print(
                                "Matches: "
                                + (", ".join(sorted(matches, key=str.casefold)[:40]) or "(none)")
                            )
                            continue
                        if skill_name not in canonical_names:
                            print("Not saved: choose an available DB/bootstrap canonical.")
                            continue
                        member = {"decision": "map_existing", "skill_name": skill_name}
                        break
                else:
                    skill_name = input("New canonical skill name (q=cancel): ").strip()
                    if skill_name.casefold() == "q":
                        print("Split cancelled; no decision was saved.")
                        return True
                    if not skill_name:
                        print("A new skill name cannot be empty.")
                        continue
                    if skill_name.casefold() in {
                        name.casefold() for name in canonical_names
                    }:
                        print("That canonical already exists; choose map-existing instead.")
                        continue
                    print("Categories: " + ", ".join(categories))
                    default_category = row.get("suggested_skill_category", "").strip() or "other"
                    category = input(f"Category [{default_category}]: ").strip() or default_category
                    if category not in categories:
                        print("Choose one of the listed categories.")
                        continue
                    member = {
                        "decision": "create_new",
                        "skill_name": skill_name,
                        "skill_category": category,
                    }

                member_key = skill_name_key(member["skill_name"])
                if any(skill_name_key(saved["skill_name"]) == member_key for saved in members):
                    print("That skill is already in this split; choose another component.")
                    continue
                members.append(member)
                break

        row["review_decision"] = "split_into_skills"
        row["canonical_skill_name"] = ""
        row["skill_category"] = ""
        row["split_skills"] = json.dumps(members, ensure_ascii=False)
    else:
        print("Not saved: choose 1, 2, 3, 4, Enter, or q.")
        return True
    print("Review decision saved to the CSV. No database data was changed.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--include-reviewed",
        action="store_true",
        help="Include rows with a saved CSV decision or a resolved DB review status",
    )
    parser.add_argument(
        "--include-ignored",
        action="store_true",
        help="Revisit ignored rows so their saved decision can be replaced",
    )
    parser.add_argument(
        "--all-candidates",
        action="store_true",
        help="Review every undecided row, including candidates still awaiting an LLM suggestion",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show remaining review counts without entering interactive review",
    )
    parser.add_argument(
        "--list-catalog",
        action="store_true",
        help="List canonical skills, categories, statuses, aliases, and bootstrap membership",
    )
    parser.add_argument(
        "--audit-catalog-names",
        action="store_true",
        help="Flag composite aliases and verified-acronym canonical duplicates without changing DB data",
    )
    parser.add_argument(
        "--list-saved-creations",
        action="store_true",
        help="List manual create-new decisions saved in the preview CSV and whether they are in DB",
    )
    arguments = parser.parse_args()
    # Posting evidence can exceed csv's small default field-size limit.
    csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

    if arguments.audit_catalog_names:
        try:
            _print_catalog_name_audit()
        except Exception as error:
            parser.error(f"Could not audit the current DB skill catalog: {error}")
        return

    try:
        catalog = load_skill_catalog()
    except Exception as error:
        parser.error(f"Could not read the current DB skill catalog: {error}")
    database_canonical_names = {
        str(item["skill_name"])
        for item in catalog.values()
        if item.get("match_method") == "exact_canonical"
    }
    bootstrap_catalog = load_bootstrap_catalog(PROJECT_ROOT / "config" / "skills.yaml")
    if arguments.list_catalog:
        _print_catalog(catalog, bootstrap_catalog)
        return
    if arguments.list_saved_creations:
        try:
            _print_saved_creations(arguments.report, catalog)
        except FileNotFoundError as error:
            parser.error(str(error))
        return

    if not arguments.report.is_file():
        parser.error(f"Preview CSV not found: {arguments.report}")
    with arguments.report.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows or "candidate_name" not in fieldnames:
        parser.error("Preview CSV is empty or missing candidate_name")
    for column in REVIEW_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)
        for row in rows:
            row.setdefault(column, "[]" if column == "split_skills" else "")
    add_database_catalog_comparison(rows, catalog)
    with get_database_connection() as connection:
        candidate_statuses = {
            str(result[0]): str(result[1])
            for result in connection.execute(
                """
                SELECT candidate_key, resolution_status
                FROM core.skill_candidate_reviews
                """
            ).fetchall()
        }

    def is_resolved_in_database(row: dict[str, str]) -> bool:
        status = candidate_statuses.get(skill_name_key(row.get("candidate_name", "")))
        return status is not None and status != "pending_review"

    def is_pending_in_database(row: dict[str, str]) -> bool:
        return (
            candidate_statuses.get(skill_name_key(row.get("candidate_name", "")))
            == "pending_review"
        )

    def is_ignored(row: dict[str, str]) -> bool:
        return (
            row.get("review_decision", "").strip() == "ignore"
            or candidate_statuses.get(
                skill_name_key(row.get("candidate_name", ""))
            )
            == "ignored"
        )

    canonical_names = set(database_canonical_names)
    bootstrap_canonical_names = {
        str(item["skill_name"])
        for item in bootstrap_catalog.values()
        if item.get("match_method") == "exact_canonical"
    }
    canonical_names.update(
        bootstrap_canonical_names
    )
    categories = sorted(
        {str(item["skill_category"]) for item in catalog.values() if item.get("skill_category")}
        | {
            str(item["skill_category"])
            for item in bootstrap_catalog.values()
            if item.get("skill_category")
        }
        | {"other"},
        key=str.casefold,
    )

    undecided = [row for row in rows if not row.get("review_decision", "").strip()]
    remaining = [row for row in undecided if not is_resolved_in_database(row)]
    resolved_db_count = sum(is_resolved_in_database(row) for row in undecided)
    manual_count = sum(row.get("preview_status") == "manual_review" for row in remaining)
    ready_count = sum(
        row.get("preview_status") == "ready_for_approval" for row in remaining
    )
    needs_llm_count = sum(
        row.get("preview_status") == "needs_llm_suggestion" for row in remaining
    )
    exact_db_count = sum(
        bool(row.get("existing_database_matches", "").strip()) for row in remaining
    )
    default_review_count = sum(
        is_pending_in_database(row)
        or row.get("preview_status") == "manual_review"
        or bool(row.get("existing_database_matches", "").strip())
        for row in remaining
    )
    if arguments.summary:
        ignored_count = sum(is_ignored(row) for row in rows)
        print(f"Preview candidates: {len(rows)}")
        print(f"Already reviewed: {len(rows) - len(undecided)}")
        print(f"Already resolved in DB: {resolved_db_count}")
        print(f"Ignored decisions available to revisit: {ignored_count}")
        print(f"Remaining, default reviewer: {default_review_count}")
        print(f"  Manual-review status: {manual_count}")
        print(f"  Exact current DB match: {exact_db_count}")
        print(f"  Ready for approval: {ready_count}")
        print(f"  Waiting for LLM suggestion: {needs_llm_count}")
        print(
            "Remaining, all unresolved candidates: "
            f"{len(remaining)} (includes ready and needs-LLM rows)"
        )
        print("No review CSV or database data was changed.")
        return

    pending = []
    for index, row in enumerate(rows, start=1):
        if arguments.include_ignored:
            if is_ignored(row):
                pending.append((index, row))
            continue
        if not arguments.include_reviewed and row.get("review_decision", "").strip():
            continue
        if not arguments.include_reviewed and is_resolved_in_database(row):
            continue
        if not (
            arguments.all_candidates
            or is_pending_in_database(row)
            or row.get("preview_status") == "manual_review"
            or row.get("existing_database_matches", "").strip()
        ):
            continue
        pending.append((index, row))
    print(f"Review file: {arguments.report}")
    print(
        f"Current DB catalog: {len(database_canonical_names)} canonical skills; "
        f"bootstrap catalog: {len(bootstrap_canonical_names)}; database access is read-only"
    )
    print(f"Rows to review: {len(pending)}")
    for index, row in pending:
        available_canonicals = set(canonical_names)
        for reviewed_row in rows:
            if reviewed_row.get("review_decision", "").strip() == "create_new":
                reviewed_name = reviewed_row.get("canonical_skill_name", "").strip()
                if reviewed_name:
                    available_canonicals.add(reviewed_name)
            elif reviewed_row.get("review_decision", "").strip() == "split_into_skills":
                members: object = reviewed_row.get("split_skills", "[]")
                while isinstance(members, str):
                    try:
                        members = json.loads(members)
                    except json.JSONDecodeError:
                        members = []
                        break
                if isinstance(members, list):
                    available_canonicals.update(
                        member["skill_name"].strip()
                        for member in members
                        if isinstance(member, dict)
                        and member.get("decision") == "create_new"
                        and isinstance(member.get("skill_name"), str)
                        and member["skill_name"].strip()
                    )
        if not _review_one(row, index, available_canonicals, categories):
            break
        _save_csv(arguments.report, fieldnames, rows)
    print(f"\nSaved review CSV: {arguments.report}")
    print("No database catalog, alias, job-skill, or checkpoint data was changed.")


if __name__ == "__main__":
    main()
