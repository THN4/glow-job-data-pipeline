"""Interactively review candidates for a clean skill-catalog rebuild."""

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

from src.market.skill_extraction.categories import SKILL_CATEGORIES
from src.shared.skill_normalization.normalizer import skill_name_key


PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
)


def _set_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


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
    return [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


def _split_members(row: dict[str, str]) -> list[dict[str, str]]:
    try:
        value: object = row.get("split_skills", "[]")
        while isinstance(value, str):
            value = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _proposed_catalog_rows(
    rows: list[dict[str, str]], *, exclude_index: int | None = None
) -> dict[str, tuple[str, str, str]]:
    proposed: dict[str, tuple[str, str, str]] = {}
    for index, row in enumerate(rows):
        if index == exclude_index:
            continue
        decision = row.get("review_decision", "").strip()
        if decision == "create_new":
            candidates = [(
                row.get("canonical_skill_name", "").strip(),
                row.get("skill_category", "").strip(),
                "manual review",
            )]
        elif decision == "split_into_skills":
            candidates = [
                (
                    member.get("skill_name", "").strip(),
                    member.get("skill_category", "").strip(),
                    "manual split",
                )
                for member in _split_members(row)
                if member.get("decision") == "create_new"
            ]
        elif (
            not decision
            and row.get("preview_status") == "ready_for_approval"
            and row.get("confidence_level") == "high"
            and row.get("suggestion_decision") == "new_skill"
        ):
            candidates = [(
                row.get("suggested_skill_name", "").strip(),
                row.get("suggested_skill_category", "").strip(),
                "high-confidence LLM proposal",
            )]
        else:
            candidates = []
        for name, category, source in candidates:
            key = skill_name_key(name)
            if key:
                proposed.setdefault(key, (name, category, source))
    return proposed


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Preview CSV not found: {path}")
    _set_csv_field_limit()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows or "candidate_name" not in fieldnames:
        raise ValueError("Preview CSV is empty or missing candidate_name")
    for column in REVIEW_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)
        for row in rows:
            row.setdefault(column, "[]" if column == "split_skills" else "")
    return fieldnames, rows


def _choose_canonical_name(row: dict[str, str]) -> str:
    candidate = row.get("candidate_name", "").strip()
    suggested = row.get("suggested_skill_name", "").strip()
    if suggested and suggested != candidate:
        print(f"1=use extracted name [{candidate}], 2=use LLM name [{suggested}], 3=type a name")
        choice = input("Name choice: ").strip()
        if choice == "1":
            return candidate
        if choice == "2":
            return suggested
        if choice == "3":
            return input("Canonical skill name: ").strip()
        return ""
    default = candidate or suggested
    print(f"1=use name [{default}], 2=type a name")
    choice = input("Name choice: ").strip()
    if choice == "1":
        return default
    if choice == "2":
        return input("Canonical skill name: ").strip()
    return ""


def _choose_category(suggested: str) -> str:
    print("Categories: " + ", ".join(SKILL_CATEGORIES))
    category = input(f"Category [{suggested or 'other'}]: ").strip() or suggested or "other"
    if category not in SKILL_CATEGORIES:
        print("Not saved: choose one of the listed categories.")
        return ""
    return category


def _review_one(
    row: dict[str, str],
    row_number: int,
    available_canonicals: set[str],
) -> bool:
    print("\n" + "=" * 88)
    print(f"Row {row_number}: {row.get('candidate_name', '')}")
    print(
        f"Observed: {row.get('observed_names', '')} | jobs={row.get('job_count', '')} | "
        f"occurrences={row.get('occurrence_count', '')}"
    )
    composites = _json_list(row.get("source_composite_names", ""))
    if composites:
        print(f"Source composite labels: {composites}")
    print(
        f"LLM: {row.get('suggestion_decision', '')} -> "
        f"{row.get('suggested_skill_name', '')} [{row.get('suggested_skill_category', '')}], "
        f"confidence={row.get('confidence_level', '')}"
    )
    print(f"Possible duplicates: {row.get('possible_duplicate_candidates', '') or '(none)'}")
    print(f"Reason: {row.get('suggestion_reason', '') or '(no LLM suggestion)'}")
    for index, (title, evidence) in enumerate(
        zip(
            _json_list(row.get("example_job_titles", "")),
            _json_list(row.get("example_evidence", "")),
        ),
        start=1,
    ):
        print(f"Evidence {index} — {title}: {evidence}")
    if row.get("review_decision"):
        print(
            f"Current decision: {row['review_decision']}; "
            f"canonical={row.get('canonical_skill_name', '')}"
        )
    print("\n1=map to proposed skill, 2=create new, 3=ignore, 4=split, Enter=skip, q=quit")
    choice = input("Decision: ").strip().lower()
    if choice == "q":
        return False
    if not choice:
        return True

    if choice == "1":
        names = sorted(available_canonicals, key=str.casefold)
        if not names:
            print("No other canonical skill is proposed yet. Create one first, then map to it.")
            return True
        print("Available: " + ", ".join(names[:50]))
        target = input("Canonical name (or ?text to search): ").strip()
        while target.startswith("?"):
            query = target[1:].strip().casefold()
            print("Matches: " + ", ".join(name for name in names if query in name.casefold())[:500])
            target = input("Canonical name: ").strip()
        match = next((name for name in names if skill_name_key(name) == skill_name_key(target)), None)
        if match is None:
            print("Not saved: choose a proposed canonical name from the list.")
            return True
        row.update(review_decision="map_existing", canonical_skill_name=match, skill_category="", split_skills="[]")
    elif choice == "2":
        name = _choose_canonical_name(row)
        if not name:
            print("Not saved: canonical name cannot be empty.")
            return True
        if skill_name_key(name) in {skill_name_key(value) for value in available_canonicals}:
            print("That name is already proposed; choose map-to-proposed instead.")
            return True
        category = _choose_category(row.get("suggested_skill_category", "").strip())
        if not category:
            return True
        row.update(review_decision="create_new", canonical_skill_name=name, skill_category=category, split_skills="[]")
    elif choice == "3":
        row.update(review_decision="ignore", canonical_skill_name="", skill_category="", split_skills="[]")
    elif choice == "4":
        raw_count = input("How many components? (2–20, q=cancel): ").strip()
        if raw_count.casefold() == "q":
            return True
        try:
            count = int(raw_count)
        except ValueError:
            print("Enter a number from 2 to 20.")
            return True
        if count < 2 or count > 20:
            print("A split needs between 2 and 20 components.")
            return True
        members: list[dict[str, str]] = []
        for component_index in range(1, count + 1):
            while True:
                print(f"Component {component_index}/{count}: 1=map proposed, 2=create new, q=cancel")
                subchoice = input("Choice: ").strip().lower()
                if subchoice == "q":
                    return True
                if subchoice == "1":
                    names = sorted(available_canonicals, key=str.casefold)
                    if not names:
                        print("No proposed canonical exists yet; choose create new.")
                        continue
                    print("Available: " + ", ".join(names[:50]))
                    name = input("Existing canonical name: ").strip()
                    match = next((item for item in names if skill_name_key(item) == skill_name_key(name)), None)
                    if match is None:
                        print("Choose a name from the proposed list.")
                        continue
                    member = {"decision": "map_existing", "skill_name": match}
                elif subchoice == "2":
                    name = input("New canonical skill name: ").strip()
                    if not name:
                        print("A new skill name cannot be empty.")
                        continue
                    category = _choose_category(row.get("suggested_skill_category", "").strip())
                    if not category:
                        continue
                    member = {"decision": "create_new", "skill_name": name, "skill_category": category}
                else:
                    print("Choose 1, 2, or q.")
                    continue
                if skill_name_key(member["skill_name"]) in {skill_name_key(item["skill_name"]) for item in members}:
                    print("That component is already in this split.")
                    continue
                members.append(member)
                if member["decision"] == "create_new":
                    available_canonicals.add(member["skill_name"])
                break
        row.update(review_decision="split_into_skills", canonical_skill_name="", skill_category="", split_skills=json.dumps(members, ensure_ascii=False))
    else:
        print("Choose 1, 2, 3, 4, Enter, or q.")
        return True
    print("Decision saved to the review CSV; the database is unchanged.")
    return True


def _print_catalog(rows: list[dict[str, str]]) -> None:
    proposed = _proposed_catalog_rows(rows)
    print(f"Proposed catalog waiting for apply: {len(proposed)} canonical skills")
    print("Canonical name | Category | Proposal source")
    for name, category, source in sorted(proposed.values(), key=lambda item: item[0].casefold()):
        print(f"{name} | {category} | {source}")


def _print_saved_creations(rows: list[dict[str, str]]) -> None:
    reviewed = [row for row in rows if row.get("review_decision", "").strip()]
    proposed = _proposed_catalog_rows(reviewed)
    print(f"Manual create-new/split decisions: {len(proposed)}")
    for name, category, _ in sorted(proposed.values(), key=lambda item: item[0].casefold()):
        print(f"{name} | {category}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--include-reviewed", action="store_true", help="Allow changing saved CSV decisions")
    parser.add_argument("--include-ignored", action="store_true", help="Review ignored rows so their decision can be replaced")
    parser.add_argument("--all-candidates", action="store_true", help="Review all undecided rows, including high-confidence proposals")
    parser.add_argument("--summary", action="store_true", help="Show review totals without entering review")
    parser.add_argument("--list-catalog", action="store_true", help="List proposed canonical names waiting for apply")
    parser.add_argument("--list-saved-creations", action="store_true", help="List manually created names in this preview")
    arguments = parser.parse_args()
    try:
        fieldnames, rows = _read_rows(arguments.report)
    except (FileNotFoundError, OSError, ValueError) as error:
        parser.error(str(error))

    if arguments.list_catalog:
        _print_catalog(rows)
        return
    if arguments.list_saved_creations:
        _print_saved_creations(rows)
        return

    undecided = [row for row in rows if not row.get("review_decision", "").strip()]
    manual = sum(row.get("preview_status") == "manual_review" for row in undecided)
    ready = sum(row.get("preview_status") == "ready_for_approval" for row in undecided)
    needs_llm = sum(row.get("preview_status") == "needs_llm_suggestion" for row in undecided)
    if arguments.summary:
        print(f"Preview candidates: {len(rows)}")
        print(f"Already reviewed in CSV: {len(rows) - len(undecided)}")
        print(f"Remaining manual review: {manual + needs_llm}")
        print(f"  Manual review: {manual}")
        print(f"  Waiting for LLM suggestion: {needs_llm}")
        print(f"  Ready for automatic approval: {ready}")
        print("The current database catalog is excluded from this clean rebuild.")
        return

    pending: list[tuple[int, dict[str, str]]] = []
    for index, row in enumerate(rows, start=1):
        decision = row.get("review_decision", "").strip()
        if arguments.include_ignored:
            if decision == "ignore":
                pending.append((index, row))
            continue
        if decision and not arguments.include_reviewed:
            continue
        if arguments.all_candidates or row.get("preview_status") in {"manual_review", "needs_llm_suggestion"}:
            pending.append((index, row))

    print(f"Review file: {arguments.report}")
    print("Clean rebuild review: old database skill names are excluded.")
    print(f"Rows to review: {len(pending)}")
    for index, row in pending:
        available = {
            name
            for name, _, _ in _proposed_catalog_rows(rows, exclude_index=index - 1).values()
        }
        if not _review_one(row, index, available):
            break
        _save_csv(arguments.report, fieldnames, rows)
    print(f"\nSaved review CSV: {arguments.report}")
    print("Only the review CSV changed. Database tables were not changed.")


if __name__ == "__main__":
    main()
