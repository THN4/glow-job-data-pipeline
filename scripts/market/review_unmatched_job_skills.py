"""Review extracted skills that did not match the current catalog.

This tool only writes review decisions to a CSV file. It does not modify the
database, checkpoints, or the unmatched source report.
"""

import argparse
import csv
import difflib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from src.shared.skill_normalization.normalizer import load_skill_catalog, skill_name_key


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "skill_candidates"
    / "unmatched_job_skill_occurrences_after_rebuild.csv"
)
DEFAULT_DECISIONS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "skill_candidates"
    / "unmatched_job_skill_reviews.csv"
)

DECISION_FIELDS = [
    "decision_key",
    "unmatched_skill_name",
    "review_decision",
    "canonical_skill_name",
    "skill_category",
    "split_skills",
    "ignore_reason",
    "occurrence_count_at_review",
    "review_status",
    "applied_at",
]


def _set_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")
    _set_csv_field_limit()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader.fieldnames or []), list(reader)


def _write_decisions(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=DECISION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _catalog_records(catalog: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    records = [
        item
        for item in catalog.values()
        if item.get("match_method") == "exact_canonical"
    ]
    records.sort(key=lambda item: str(item["skill_name"]).casefold())
    return records


def _group_occurrences(
    occurrences: list[dict[str, str]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    display_names: dict[str, str] = {}
    for occurrence in occurrences:
        name = occurrence.get("unmatched_skill_name", "").strip()
        if not name:
            continue
        key = skill_name_key(name)
        grouped[key].append(occurrence)
        display_names.setdefault(key, name)

    result = [
        {
            "decision_key": key,
            "unmatched_skill_name": display_names[key],
            "occurrences": grouped[key],
        }
        for key in grouped
    ]
    result.sort(
        key=lambda item: (
            -len(item["occurrences"]),
            str(item["unmatched_skill_name"]).casefold(),
        )
    )
    return result


def _read_existing_decisions(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    _, rows = _read_csv(path)
    return {
        row.get("decision_key", "") or skill_name_key(row.get("unmatched_skill_name", "")): row
        for row in rows
        if row.get("decision_key") or row.get("unmatched_skill_name")
    }


def _similar_records(
    query: str, records: list[dict[str, object]], limit: int = 10
) -> list[tuple[float, dict[str, object]]]:
    query_key = skill_name_key(query)
    scored = [
        (
            difflib.SequenceMatcher(
                None, query_key, skill_name_key(str(record["skill_name"]))
            ).ratio(),
            record,
        )
        for record in records
    ]
    scored.sort(key=lambda pair: (-pair[0], str(pair[1]["skill_name"]).casefold()))
    return scored[:limit]


def _print_catalog(records: list[dict[str, object]], query: str = "") -> None:
    selected = records
    if query:
        key = skill_name_key(query)
        selected = [
            record
            for record in records
            if key in skill_name_key(str(record["skill_name"]))
        ]
    print(f"Catalog skills: {len(selected)}")
    for index, record in enumerate(selected, start=1):
        category = record.get("skill_category") or "other"
        print(f"  {index}. {record['skill_name']} [{category}]")


def _choose_canonical(
    prompt: str,
    records: list[dict[str, object]],
    *,
    query: str,
) -> str | None:
    current_query = query
    while True:
        matches = _similar_records(current_query, records)
        print("Catalog matches:")
        for index, (score, record) in enumerate(matches, start=1):
            print(
                f"  {index}. {record['skill_name']} "
                f"[{record.get('skill_category') or 'other'}] ({score:.0%})"
            )
        answer = input(
            f"{prompt} Enter number, exact canonical name, /search text, or x to cancel: "
        ).strip()
        if answer.casefold() == "x":
            return None
        if answer.startswith("/"):
            current_query = answer[1:].strip()
            if not current_query:
                print("Enter text to search for.")
                current_query = query
            else:
                _print_catalog(records, current_query)
            continue
        if answer.isdigit():
            selected = int(answer)
            if 1 <= selected <= len(matches):
                return str(matches[selected - 1][1]["skill_name"])
            print("That number is not in the suggestion list.")
            continue
        exact = next(
            (
                str(record["skill_name"])
                for record in records
                if skill_name_key(str(record["skill_name"])) == skill_name_key(answer)
            ),
            None,
        )
        if exact:
            return exact
        print("No exact canonical match. Search with /text or choose a suggestion.")


def _choose_category(categories: list[str]) -> str:
    print("Categories:")
    for index, category in enumerate(categories, start=1):
        print(f"  {index}. {category}")
    while True:
        answer = input("Category number or category name [other]: ").strip()
        if not answer:
            return "other"
        if answer.isdigit() and 1 <= int(answer) <= len(categories):
            return categories[int(answer) - 1]
        match = next((item for item in categories if item.casefold() == answer.casefold()), None)
        if match:
            return match
        print("Choose one of the listed categories.")


def _prompt_split(
    records: list[dict[str, object]], categories: list[str]
) -> list[dict[str, str]] | None:
    while True:
        answer = input("How many component skills? (at least 2; x to cancel): ").strip()
        if answer.casefold() == "x":
            return None
        if answer.isdigit() and int(answer) >= 2:
            count = int(answer)
            break
        print("Enter a number of 2 or more.")

    components: list[dict[str, str]] = []
    for index in range(1, count + 1):
        print(f"Component {index} of {count}")
        name = input("  Skill name: ").strip()
        if not name:
            print("  Skill name cannot be empty; restart the split decision.")
            return None
        action = input("  Use existing catalog skill (e) or create new (n)? [e/n]: ").strip().casefold()
        if action == "e":
            canonical = _choose_canonical(
                "  Existing skill", records, query=name
            )
            if canonical is None:
                return None
            components.append(
                {"decision": "map_existing", "skill_name": canonical, "skill_category": ""}
            )
        elif action == "n":
            canonical = input(f"  Canonical name [{name}]: ").strip() or name
            category = _choose_category(categories)
            components.append(
                {"decision": "create_new", "skill_name": canonical, "skill_category": category}
            )
        else:
            print("Choose e or n; restart the split decision.")
            return None
    return components


def _show_occurrences(group: dict[str, object]) -> None:
    occurrences = group["occurrences"]
    print(
        f"\n{group['unmatched_skill_name']} "
        f"| occurrences={len(occurrences)} "
        f"| postings={len({row.get('provider_job_id', '') for row in occurrences})}"
    )
    raw_names = sorted(
        {row.get("source_raw_skill_name", "").strip() for row in occurrences if row.get("source_raw_skill_name", "").strip()}
    )
    if raw_names:
        print(f"Source labels: {raw_names[:8]}")
    for index, occurrence in enumerate(occurrences[:5], start=1):
        print(
            f"  Evidence {index} — {occurrence.get('job_title', '(no title)')}: "
            f"{occurrence.get('evidence_text', '')[:700]}"
        )
    if len(occurrences) > 5:
        print(f"  ... and {len(occurrences) - 5} more occurrences")


def _review_one(
    group: dict[str, object],
    records: list[dict[str, object]],
    categories: list[str],
) -> dict[str, str] | None:
    _show_occurrences(group)
    for index, (score, record) in enumerate(
        _similar_records(str(group["unmatched_skill_name"]), records, limit=8), start=1
    ):
        print(
            f"  Similar {index}. {record['skill_name']} "
            f"[{record.get('skill_category') or 'other'}] ({score:.0%})"
        )

    while True:
        action = input(
            "1=map existing, 2=create new, 3=split, 4=ignore, Enter=skip, q=quit: "
        ).strip().casefold()
        if action == "q":
            return None
        if not action:
            return {}
        if action == "1":
            canonical = _choose_canonical(
                "Map to", records, query=str(group["unmatched_skill_name"])
            )
            if canonical is None:
                continue
            return {"review_decision": "map_existing", "canonical_skill_name": canonical}
        if action == "2":
            proposed = str(group["unmatched_skill_name"])
            canonical = input(f"Canonical skill name [{proposed}]: ").strip() or proposed
            category = _choose_category(categories)
            return {
                "review_decision": "create_new",
                "canonical_skill_name": canonical,
                "skill_category": category,
            }
        if action == "3":
            components = _prompt_split(records, categories)
            if components is not None:
                return {
                    "review_decision": "split_into_skills",
                    "split_skills": json.dumps(components, ensure_ascii=False),
                }
            continue
        if action == "4":
            reason = input("Reason to ignore (optional): ").strip()
            return {"review_decision": "ignore", "ignore_reason": reason}
        print("Choose 1, 2, 3, 4, Enter, or q.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--summary", action="store_true", help="Show counts without review")
    parser.add_argument("--list-catalog", action="store_true", help="List current DB canonical skills")
    parser.add_argument("--include-reviewed", action="store_true", help="Revisit saved decisions")
    arguments = parser.parse_args()

    try:
        fieldnames, occurrences = _read_csv(arguments.report)
    except (OSError, csv.Error) as error:
        parser.error(str(error))
    if not occurrences or "unmatched_skill_name" not in fieldnames:
        parser.error("Unmatched report is empty or missing unmatched_skill_name")

    try:
        catalog = load_skill_catalog()
    except Exception as error:
        parser.error(f"Could not read the current DB skill catalog: {error}")
    records = _catalog_records(catalog)
    categories = sorted(
        {str(item.get("skill_category") or "other") for item in records}
        | {"other"},
        key=str.casefold,
    )

    groups = _group_occurrences(occurrences)
    saved = _read_existing_decisions(arguments.decisions)
    reviewed_count = sum(group["decision_key"] in saved for group in groups)
    remaining = [group for group in groups if group["decision_key"] not in saved]

    if arguments.list_catalog:
        _print_catalog(records)
        return
    if arguments.summary:
        print(f"Unmatched occurrences: {len(occurrences)}")
        print(f"Unique unmatched names: {len(groups)}")
        print(f"Already reviewed: {reviewed_count}")
        print(f"Remaining: {len(remaining)}")
        print(f"Decision file: {arguments.decisions}")
        return

    if arguments.include_reviewed:
        remaining = groups

    print(f"Unmatched report: {arguments.report}")
    print(f"Occurrences: {len(occurrences)} | unique names: {len(groups)}")
    print(f"Catalog: {len(records)} canonical skills (read-only)")
    print(f"Rows to review: {len(remaining)}")
    decisions_by_key = dict(saved)

    for index, group in enumerate(remaining, start=1):
        print(f"\nReview {index}/{len(remaining)}")
        outcome = _review_one(group, records, categories)
        if outcome is None:
            break
        if not outcome:
            continue
        saved_row = {field: "" for field in DECISION_FIELDS}
        saved_row.update(
            {
                "decision_key": str(group["decision_key"]),
                "unmatched_skill_name": str(group["unmatched_skill_name"]),
                "occurrence_count_at_review": str(len(group["occurrences"])),
                "review_status": "reviewed",
            }
        )
        saved_row.update(outcome)
        decisions_by_key[str(group["decision_key"])] = saved_row
        _write_decisions(arguments.decisions, list(decisions_by_key.values()))

    print(f"\nSaved review decisions: {arguments.decisions}")
    print("Database and extraction checkpoints were not changed.")


if __name__ == "__main__":
    main()
