"""Apply reviewed unmatched-skill decisions without rebuilding the catalog."""

import argparse
import csv
import json
import shutil
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from src.load.career_skill_aggregator import refresh_career_skill_stats
from src.load.database import get_database_connection
from src.load.job_skill_loader import load_job_skills_from_run
from src.skills.normalizer import (
    build_skill_catalog,
    load_skill_catalog,
    normalize_skills_for_jobs,
    skill_name_key,
    split_composite_skill_name,
)
from src.storage.skill_result_storage import load_skill_results, save_skill_results


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    PROJECT_ROOT / "data" / "processed" / "skill_candidates"
    / "unmatched_job_skill_occurrences_after_rebuild.csv"
)
DEFAULT_DECISIONS = (
    PROJECT_ROOT / "data" / "processed" / "skill_candidates"
    / "unmatched_job_skill_reviews.csv"
)
DEFAULT_CHECKPOINT_DIR = PROJECT_ROOT / "data" / "processed" / "skill_extraction"
DEFAULT_BACKUP_ROOT = (
    PROJECT_ROOT / "data" / "processed" / "unmatched_skill_review_backups"
)


def _set_csv_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    _set_csv_limit()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader.fieldnames or []), list(reader)


def _json_default(value: object) -> str:
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


def _backup_database(folder: Path) -> list[tuple[date, date, str]]:
    folder.mkdir(parents=True, exist_ok=True)
    tables = {
        "core.skills": "skills.json",
        "core.skill_aliases": "skill_aliases.json",
        "market.job_skills": "job_skills.json",
        "market.career_skill_stats": "career_skill_stats.json",
    }
    with get_database_connection() as connection:
        windows = connection.execute(
            """SELECT DISTINCT analysis_start_date, analysis_end_date,
                      analysis_date_basis
               FROM market.career_skill_stats
               ORDER BY analysis_start_date, analysis_end_date, analysis_date_basis"""
        ).fetchall()
        counts = {}
        for table, filename in tables.items():
            rows = [row[0] for row in connection.execute(
                f"SELECT to_jsonb(t) FROM {table} AS t"
            ).fetchall()]
            with (folder / filename).open("w", encoding="utf-8") as output:
                json.dump(rows, output, ensure_ascii=False, indent=2, default=_json_default)
            counts[table] = len(rows)
        with (folder / "manifest.json").open("w", encoding="utf-8") as output:
            json.dump(
                {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                 "row_counts": counts, "tables": tables, "stats_windows": windows},
                output, ensure_ascii=False, indent=2, default=_json_default,
            )
    return [(start, end, basis) for start, end, basis in windows]


def _read_catalog_records() -> tuple[list[tuple[int, str, str | None, str]], list[tuple[int, str]]]:
    with get_database_connection() as connection:
        skills = connection.execute(
            "SELECT skill_id, skill_name, skill_category, catalog_status "
            "FROM core.skills ORDER BY skill_id"
        ).fetchall()
        aliases = connection.execute(
            "SELECT skill_id, alias FROM core.skill_aliases ORDER BY alias_id"
        ).fetchall()
    return skills, aliases


def _parse_split(value: str, name: str) -> list[dict[str, str]]:
    try:
        members = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid split JSON for {name!r}") from error
    if not isinstance(members, list) or len(members) < 2:
        raise ValueError(f"Split for {name!r} needs at least two components")
    parsed = []
    for member in members:
        if not isinstance(member, dict):
            raise ValueError(f"Invalid split component for {name!r}")
        decision = member.get("decision")
        skill_name = member.get("skill_name")
        category = member.get("skill_category", "")
        if decision not in {"map_existing", "create_new"} or not isinstance(skill_name, str) or not skill_name.strip():
            raise ValueError(f"Invalid split component for {name!r}")
        parsed.append({"decision": decision, "skill_name": skill_name.strip(),
                       "skill_category": str(category).strip()})
    if len({skill_name_key(member["skill_name"]) for member in parsed}) != len(parsed):
        raise ValueError(f"Duplicate split components for {name!r}")
    return parsed


def _load_decisions(path: Path) -> dict[str, dict[str, object]]:
    _, rows = _read_csv(path)
    decisions = {}
    for row in rows:
        name = row.get("unmatched_skill_name", "").strip()
        action = row.get("review_decision", "").strip()
        if not name or action not in {"map_existing", "create_new", "split_into_skills", "ignore"}:
            raise ValueError(f"Incomplete review decision row: {row}")
        key = skill_name_key(name)
        if key in decisions:
            raise ValueError(f"Duplicate review decision for {name!r}")
        item: dict[str, object] = {**row, "key": key, "name": name, "action": action}
        if action == "split_into_skills":
            item["members"] = _parse_split(row.get("split_skills", ""), name)
        decisions[key] = item
    return decisions


def _mark_decisions_applied(path: Path) -> None:
    fieldnames, rows = _read_csv(path)
    for field in ("review_status", "applied_at"):
        if field not in fieldnames:
            fieldnames.append(field)
    timestamp = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("review_decision"):
            row["review_status"] = "applied"
            row["applied_at"] = timestamp
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _prepare_catalog(
    decisions: dict[str, dict[str, object]],
    skills: list[tuple[int, str, str | None, str]],
    aliases: list[tuple[int, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    canonicals = {skill_name_key(row[1]): row for row in skills}
    alias_targets = {skill_name_key(alias): skill_id for skill_id, alias in aliases}
    new_skills: dict[str, tuple[str, str]] = {}
    new_aliases: dict[str, str] = {}

    def add_new(name: str, category: str) -> None:
        key = skill_name_key(name)
        if key in canonicals:
            return
        prior = new_skills.get(key)
        if prior and prior[1] != category:
            raise ValueError(f"Conflicting categories for new skill {name!r}")
        if key in alias_targets:
            raise ValueError(f"New canonical {name!r} conflicts with an existing alias")
        new_skills[key] = (name, category)

    def map_alias(alias: str, canonical: str) -> None:
        alias_key = skill_name_key(alias)
        canonical_key = skill_name_key(canonical)
        if canonical_key not in canonicals and canonical_key not in new_skills:
            raise ValueError(f"Map target {canonical!r} is not in the DB catalog")
        if alias_key == canonical_key:
            return
        target_id = canonicals.get(canonical_key, (None,))[0]
        if alias_key in canonicals:
            if alias_key != canonical_key:
                raise ValueError(f"Alias {alias!r} conflicts with a canonical skill")
            return
        if alias_key in alias_targets:
            existing_id = alias_targets[alias_key]
            if target_id is not None and existing_id != target_id:
                raise ValueError(f"Alias {alias!r} already points to another skill")
            return
        prior = new_aliases.get(alias_key)
        if prior and skill_name_key(prior) != canonical_key:
            raise ValueError(f"Alias {alias!r} has conflicting targets")
        new_aliases[alias_key] = canonical

    for item in decisions.values():
        action = item["action"]
        if action == "map_existing":
            map_alias(str(item["name"]), str(item.get("canonical_skill_name", "")))
        elif action == "create_new":
            name = str(item.get("canonical_skill_name", "")).strip()
            category = str(item.get("skill_category", "")).strip()
            if not name or not category:
                raise ValueError(f"New skill decision for {item['name']!r} needs name and category")
            add_new(name, category)
            map_alias(str(item["name"]), name)
        elif action == "split_into_skills":
            for member in item["members"]:
                if member["decision"] == "create_new":
                    if not member["skill_category"]:
                        raise ValueError(f"New split skill {member['skill_name']!r} needs a category")
                    add_new(member["skill_name"], member["skill_category"])
                elif skill_name_key(member["skill_name"]) not in canonicals:
                    raise ValueError(f"Split target {member['skill_name']!r} is not in the DB catalog")

    new_skill_rows = list(new_skills.values())
    # Confirm the proposed names and aliases do not create lookup collisions.
    prospective = [*skills, *((-index, name, category, "approved") for index, (name, category) in enumerate(new_skill_rows, 1))]
    prospective_aliases = [*aliases]
    skill_ids_by_key = {skill_name_key(row[1]): row[0] for row in prospective}
    prospective_aliases.extend(
        (skill_ids_by_key[skill_name_key(canonical)], alias)
        for alias_key, canonical in new_aliases.items()
        for alias in [next(str(item["name"]) for item in decisions.values() if skill_name_key(str(item["name"])) == alias_key)]
    )
    build_skill_catalog(prospective, prospective_aliases)
    return new_skill_rows, [(alias, canonical) for alias, canonical in (
        (next(str(item["name"]) for item in decisions.values() if skill_name_key(str(item["name"])) == key), target)
        for key, target in new_aliases.items()
    )]


def _transform_entries(
    entries: list[dict[str, object]], decisions: dict[str, dict[str, object]]
) -> tuple[list[dict[str, object]], int, int]:
    transformed: list[dict[str, object]] = []
    split_count = 0
    ignored_count = 0
    for entry in entries:
        result = dict(entry)
        if entry.get("extraction_status") != "completed":
            transformed.append(result)
            continue
        raw_skills = entry.get("skills")
        if not isinstance(raw_skills, list):
            raise ValueError("Completed checkpoint entry is missing a skills list")
        new_raw_skills: list[dict[str, object]] = []
        changed = False
        for raw in raw_skills:
            if not isinstance(raw, dict) or not isinstance(raw.get("raw_skill_name"), str):
                raise ValueError("Checkpoint contains a malformed skill")
            name = raw["raw_skill_name"].strip()
            evidence = raw.get("evidence_text")
            evidence_text = evidence if isinstance(evidence, str) else ""
            components = split_composite_skill_name(name, evidence_text)
            replacements: list[str] = []
            had_decision = False
            for component in components:
                item = decisions.get(skill_name_key(component))
                if item is None:
                    replacements.append(component)
                    continue
                had_decision = True
                action = item["action"]
                if action == "ignore":
                    ignored_count += 1
                elif action == "split_into_skills":
                    replacements.extend(member["skill_name"] for member in item["members"])
                    split_count += 1
                else:
                    replacements.append(component)
            if not had_decision:
                new_raw_skills.append(raw)
                continue
            changed = True
            for replacement in replacements:
                if not replacement:
                    continue
                updated = dict(raw)
                updated["raw_skill_name"] = replacement
                new_raw_skills.append(updated)
        if changed:
            result["skills"] = new_raw_skills
            result["unmatched_review_applied_at"] = datetime.now(timezone.utc).isoformat()
        transformed.append(result)
    return transformed, split_count, ignored_count


def _actual_unmatched_counter(
    run_id: str, entries: list[dict[str, object]], catalog: dict[str, dict[str, object]]
) -> Counter[tuple[str, str, str, str, str]]:
    counts: Counter[tuple[str, str, str, str, str]] = Counter()
    for entry in normalize_skills_for_jobs(entries, catalog):
        job = entry.get("job") if isinstance(entry.get("job"), dict) else {}
        for skill in entry.get("unmatched_skills", []):
            counts[(
                run_id,
                str(job.get("job_id", "")),
                str(skill.get("raw_skill_name", "")),
                str(skill.get("source_raw_skill_name", "")),
                str(skill.get("evidence_text", "")),
            )] += 1
    return counts


def _resolve_checkpoint_dir(
    explicit_dir: Path | None,
    run_ids: list[str],
    report_rows: list[dict[str, str]],
    catalog: dict[str, dict[str, object]],
) -> Path:
    expected: Counter[tuple[str, str, str, str, str]] = Counter(
        (
            row.get("run_id", ""),
            row.get("provider_job_id", ""),
            row.get("unmatched_skill_name", ""),
            row.get("source_raw_skill_name", ""),
            row.get("evidence_text", ""),
        )
        for row in report_rows
    )
    if explicit_dir is not None:
        return explicit_dir

    candidates = [DEFAULT_CHECKPOINT_DIR]
    backup_root = PROJECT_ROOT / "data" / "processed" / "skill_catalog_backups"
    if backup_root.is_dir():
        candidates.extend(
            sorted(
                backup_root.glob("*/split_applied_checkpoints"),
                key=lambda path: path.parent.name,
                reverse=True,
            )
        )
    matching = []
    for folder in candidates:
        if not all((folder / f"{run_id}.json").is_file() for run_id in run_ids):
            continue
        actual: Counter[tuple[str, str, str, str, str]] = Counter()
        try:
            for run_id in run_ids:
                entries = load_skill_results(run_id=run_id, output_dir=folder)
                actual.update(_actual_unmatched_counter(run_id, entries, catalog))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if actual == expected:
            matching.append(folder)
    if not matching:
        raise ValueError(
            "Could not find checkpoints matching the unmatched report exactly. "
            "Pass --checkpoint-dir with the checkpoint set used to create the report."
        )
    return matching[0]


def _write_remaining_report(
    path: Path,
    runs: list[tuple[str, list[dict[str, object]]]],
) -> int:
    fields = ["run_id", "provider_job_id", "job_title", "unmatched_skill_name",
              "source_raw_skill_name", "evidence_text"]
    rows = []
    for run_id, entries in runs:
        normalized = normalize_skills_for_jobs(entries, load_skill_catalog())
        for entry in normalized:
            job = entry.get("job") if isinstance(entry.get("job"), dict) else {}
            for skill in entry.get("unmatched_skills", []):
                rows.append({
                    "run_id": run_id,
                    "provider_job_id": str(job.get("job_id", "")),
                    "job_title": str(job.get("job_title", "")),
                    "unmatched_skill_name": str(skill.get("raw_skill_name", "")),
                    "source_raw_skill_name": str(skill.get("source_raw_skill_name", "")),
                    "evidence_text": str(skill.get("evidence_text", "")),
                })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help="Checkpoint set used for the unmatched report (auto-detected by default)",
    )
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--apply", action="store_true", help="Write approved decisions to DB/checkpoints")
    arguments = parser.parse_args()

    if not arguments.report.is_file() or not arguments.decisions.is_file():
        parser.error("Both unmatched report and review decision CSV must exist")
    _, report_rows = _read_csv(arguments.report)
    report_names = {skill_name_key(row.get("unmatched_skill_name", "")) for row in report_rows}
    decisions = _load_decisions(arguments.decisions)
    missing = sorted(report_names - set(decisions))
    if missing:
        parser.error(f"{len(missing)} unmatched names have no review decision; run the reviewer first")

    run_ids = sorted({row.get("run_id", "").strip() for row in report_rows if row.get("run_id", "").strip()})
    if not run_ids:
        parser.error("Unmatched report does not contain run_id values")
    skills, aliases = _read_catalog_records()
    current_catalog = build_skill_catalog(skills, aliases)
    try:
        checkpoint_dir = _resolve_checkpoint_dir(
            arguments.checkpoint_dir,
            run_ids,
            report_rows,
            current_catalog,
        )
    except ValueError as error:
        parser.error(str(error))
    new_skills, new_aliases = _prepare_catalog(decisions, skills, aliases)

    prepared_runs = []
    split_count = ignored_count = changed_jobs = 0
    for run_id in run_ids:
        entries = load_skill_results(run_id=run_id, output_dir=checkpoint_dir)
        if not entries:
            parser.error(f"No checkpoint entries found for run {run_id}")
        updated, run_splits, run_ignored = _transform_entries(entries, decisions)
        changed_jobs += sum(
            bool(entry.get("unmatched_review_applied_at"))
            and entry.get("unmatched_review_applied_at") != old.get("unmatched_review_applied_at")
            for entry, old in zip(updated, entries, strict=True)
        )
        split_count += run_splits
        ignored_count += run_ignored
        prepared_runs.append((run_id, entries, updated))

    # Build an in-memory catalog to ensure the decisions will resolve before any writes.
    proposed_skills = list(skills)
    fake_ids = -1
    for name, category in new_skills:
        proposed_skills.append((fake_ids, name, category, "approved"))
        fake_ids -= 1
    proposed_aliases = list(aliases)
    ids_by_name = {skill_name_key(row[1]): row[0] for row in proposed_skills}
    proposed_aliases.extend((ids_by_name[skill_name_key(canonical)], alias) for alias, canonical in new_aliases)
    catalog = build_skill_catalog(proposed_skills, proposed_aliases)
    unresolved_after = []
    transformed_counts = {}
    for run_id, _, updated in prepared_runs:
        normalized = normalize_skills_for_jobs(updated, catalog)
        left = [skill for entry in normalized for skill in entry.get("unmatched_skills", [])]
        unresolved_after.extend(left)
        transformed_counts[run_id] = {
            "jobs": len(updated),
            "unmatched_after_decisions": len(left),
        }

    summary = {
        "reviewed_names": len(decisions),
        "source_checkpoint_dir": str(checkpoint_dir),
        "decisions": dict(Counter(str(item["action"]) for item in decisions.values())),
        "new_canonical_skills": [name for name, _ in new_skills],
        "new_aliases": new_aliases,
        "checkpoint_jobs_to_rewrite": changed_jobs,
        "split_occurrences": split_count,
        "ignored_occurrences_removed": ignored_count,
        "runs": transformed_counts,
        "unmatched_after_decisions": len(unresolved_after),
        "unmatched_after_decisions_sample": [
            str(skill.get("raw_skill_name", "")) for skill in unresolved_after[:30]
        ],
        "mode": "apply" if arguments.apply else "dry_run",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not arguments.apply:
        print("Dry run only. No database or checkpoint data was changed.")
        return

    backup_dir = arguments.backup_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_backup = backup_dir / "checkpoints"
    checkpoint_backup.mkdir()
    for run_id, _, _ in prepared_runs:
        source = checkpoint_dir / f"{run_id}.json"
        shutil.copy2(source, checkpoint_backup / source.name)
    windows = _backup_database(backup_dir / "database")
    reviewed_checkpoint_dir = backup_dir / "reviewed_checkpoints"

    try:
        # Preserve the selected source checkpoints; write transformed copies in the backup folder.
        for run_id, _, updated in prepared_runs:
            save_skill_results(updated, run_id=run_id, output_dir=reviewed_checkpoint_dir)
        with get_database_connection() as connection:
            with connection.transaction():
                for name, category in new_skills:
                    connection.execute(
                        """INSERT INTO core.skills (skill_name, skill_category, catalog_status)
                           VALUES (%s, %s, 'approved')
                           ON CONFLICT (skill_name) DO NOTHING""",
                        (name, category),
                    )
                for alias, canonical in new_aliases:
                    connection.execute(
                        """INSERT INTO core.skill_aliases (skill_id, alias)
                           SELECT skill_id, %s FROM core.skills
                           WHERE lower(skill_name) = lower(%s)
                           ON CONFLICT (alias) DO NOTHING""",
                        (alias, canonical),
                    )
        loaded = {}
        for run_id, _, _ in prepared_runs:
            loaded[run_id] = load_job_skills_from_run(run_id, output_dir=reviewed_checkpoint_dir)
        aggregates = [
            {"start": start, "end": end, "basis": basis,
             **refresh_career_skill_stats(start, end, date_basis=basis)}
            for start, end, basis in windows
        ]
        after_report = arguments.report.with_name("unmatched_job_skill_occurrences_after_review.csv")
        unmatched_rows = _write_remaining_report(
            after_report,
            [(run_id, load_skill_results(run_id=run_id, output_dir=reviewed_checkpoint_dir))
             for run_id in run_ids],
        )
        _mark_decisions_applied(arguments.decisions)
        print(json.dumps({"backup_dir": str(backup_dir),
                          "reviewed_checkpoint_dir": str(reviewed_checkpoint_dir),
                          "loaded_by_run": loaded,
                          "aggregates": aggregates, "remaining_unmatched_occurrences": unmatched_rows,
                          "remaining_unmatched_report": str(after_report)},
                         ensure_ascii=False, indent=2, default=_json_default))
    except Exception:
        print(f"Apply encountered an error. Backups are available at {backup_dir}")
        print("If needed, restore the checkpoint JSON files from the backup before retrying.")
        raise


if __name__ == "__main__":
    main()
