"""Back up and rebuild the skill catalog from saved extraction checkpoints."""

import argparse
import csv
import json
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.load.career_skill_aggregator import refresh_career_skill_stats
from src.load.database import get_database_connection
from src.load.job_skill_loader import load_job_skills_from_run
from src.skills.catalog_rebuild_preview import (
    build_catalog_rebuild_preview,
    finalize_preview_suggestions,
    load_bootstrap_catalog,
    load_skill_checkpoints,
    save_catalog_rebuild_preview,
)
from src.skills.extractor import extract_skills_for_jobs
from src.skills.candidate_suggester import suggest_skill_candidates
from src.skills.gemini_client import gemini_generate
from src.skills.normalizer import (
    skill_identity_key,
    skill_name_key,
    split_composite_skill_name,
)
from src.storage.skill_result_storage import save_skill_results
from scripts.preview_skill_catalog_rebuild import _resume_existing_rows
from scripts.seed_skill_catalog import load_skill_records


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_DIR = PROJECT_ROOT / "data" / "processed" / "skill_extraction"
PREVIEW_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "skill_candidates"
    / "catalog_rebuild_preview.csv"
)
BACKUP_ROOT = PROJECT_ROOT / "data" / "processed" / "skill_catalog_backups"
TABLES_TO_BACK_UP = {
    "core.skills": "skills.json",
    "core.skill_aliases": "skill_aliases.json",
    "core.skill_candidate_reviews": "skill_candidate_reviews.json",
    "market.job_skills": "job_skills.json",
    "market.career_skill_stats": "career_skill_stats.json",
}


def _json_default(value: object) -> str:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def _write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, default=_json_default)


def _backup_checkpoints(
    checkpoints: list[tuple[str, list[dict[str, object]]]],
    folder: Path,
    source_dir: Path,
) -> None:
    checkpoint_backup = folder / "checkpoints"
    checkpoint_backup.mkdir(parents=True, exist_ok=True)
    for run_id, _ in checkpoints:
        source = source_dir / f"{run_id}.json"
        shutil.copy2(source, checkpoint_backup / source.name)


def _backup_database(folder: Path) -> list[tuple[object, object, str]]:
    folder.mkdir(parents=True, exist_ok=True)
    with get_database_connection() as connection:
        windows = connection.execute(
            """
            SELECT DISTINCT analysis_start_date, analysis_end_date, analysis_date_basis
            FROM market.career_skill_stats
            ORDER BY analysis_start_date, analysis_end_date, analysis_date_basis
            """
        ).fetchall()
        counts: dict[str, int] = {}
        for table, filename in TABLES_TO_BACK_UP.items():
            rows = connection.execute(f"SELECT to_jsonb(t) FROM {table} AS t").fetchall()
            payload = [row[0] for row in rows]
            _write_json(folder / filename, payload)
            counts[table] = len(payload)
        _write_json(
            folder / "manifest.json",
            {
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "row_counts": counts,
                "career_skill_stat_windows": windows,
                "tables": TABLES_TO_BACK_UP,
            },
        )
    return [(start, end, basis) for start, end, basis in windows]


def _reextract_checkpoints(
    checkpoints: list[tuple[str, list[dict[str, object]]]],
    *,
    request_interval: float,
    force_all: bool,
    output_dir: Path,
) -> tuple[list[tuple[str, list[dict[str, object]]]], int, int]:
    updated: list[tuple[str, list[dict[str, object]]]] = []
    extracted_count = 0
    fallback_count = 0
    for run_id, entries in checkpoints:
        for index, entry in enumerate(entries):
            if entry.get("catalog_rebuild_extracted_at") and not force_all:
                continue
            if extracted_count and request_interval:
                time.sleep(request_interval)
            previous_result = entry
            result = extract_skills_for_jobs([entry])[0]
            if result.get("extraction_status") == "completed":
                result["catalog_rebuild_extracted_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
            elif (
                previous_result.get("extraction_status") == "completed"
                and "evidence_text must be an exact quote" in str(
                    result.get("extraction_error", "")
                )
            ):
                # A malformed quote should not erase a previously valid job
                # extraction or block the full catalog rebuild.
                result = dict(previous_result)
                result["catalog_rebuild_extracted_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
                result["catalog_rebuild_extraction_fallback"] = (
                    "Reused prior completed extraction because Gemini returned "
                    "evidence that was not an exact quote."
                )
                fallback_count += 1
            entries[index] = result
            save_skill_results(entries, run_id=run_id, output_dir=output_dir)
            extracted_count += 1
            if result.get("extraction_status") != "completed":
                raise RuntimeError(
                    f"Skill extraction failed for run {run_id}, job {index + 1}; "
                    "database reset was not started. Fix the reported issue and rerun; "
                    "completed jobs are checkpointed and will be skipped."
                )
        failed = [
            index + 1
            for index, entry in enumerate(entries)
            if entry.get("extraction_status") != "completed"
        ]
        if failed:
            raise RuntimeError(
                f"Extraction for run {run_id} is incomplete at jobs {failed[:10]}; "
                "database reset was not started. Rerun this command to retry failed jobs."
            )
        updated.append((run_id, entries))
    return updated, extracted_count, fallback_count


def _read_prior_preview() -> tuple[list[str], list[dict[str, str]]]:
    if not PREVIEW_FILE.is_file():
        return [], []
    # Preview rows can contain long evidence text. Python's default CSV field
    # limit (131072) is too small for some postings, and sys.maxsize may not
    # fit the C long used by csv.field_size_limit on Windows, so reduce until
    # the platform accepts the value.
    field_limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(field_limit)
            break
        except OverflowError:
            field_limit //= 10
    with PREVIEW_FILE.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader.fieldnames or []), list(reader)


def _suggest_candidates(
    rows: list[dict[str, object]],
    bootstrap_catalog: dict[str, dict[str, object]],
    *,
    limit: int,
    batch_size: int,
    request_interval: float,
) -> int:
    suggestion_limit = min(limit, len(rows))
    candidate_pool = [str(row["candidate_name"]) for row in rows[:200]]
    pending = [
        row
        for row in rows[:suggestion_limit]
        if not row.get("suggestion_decision")
    ]
    request_count = 0
    for start in range(0, len(pending), batch_size):
        if request_count and request_interval:
            time.sleep(request_interval)
        batch = pending[start : start + batch_size]
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                suggestions = suggest_skill_candidates(
                    batch,
                    bootstrap_catalog,
                    generate=gemini_generate,
                    include_candidate_ids=False,
                    candidate_pool=candidate_pool,
                )
                last_error = None
                break
            except (RuntimeError, ValueError) as error:
                last_error = error
                if attempt < 3 and request_interval:
                    time.sleep(request_interval * attempt)
        if last_error is not None:
            raise RuntimeError(
                f"Candidate suggestions stopped before database reset; "
                f"resume this command after addressing the LLM response error: {last_error}"
            ) from last_error
        for row, suggestion in zip(batch, suggestions, strict=True):
            row.update(suggestion)
        request_count += 1
        finalize_preview_suggestions(rows)
        save_catalog_rebuild_preview(rows, PREVIEW_FILE)
    return request_count


def _parse_split_members(row: dict[str, object]) -> list[dict[str, str]]:
    raw_members = row.get("split_skills", [])
    members = raw_members
    # Some older CSV saves wrapped the JSON array in multiple JSON-string
    # layers. Unwrap until we reach the array so saved decisions remain valid.
    while isinstance(members, str):
        try:
            members = json.loads(members)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Split review for {row.get('candidate_name')!r} is not valid JSON"
            ) from error
    if not isinstance(members, list) or len(members) < 2:
        raise ValueError(
            f"Split review for {row.get('candidate_name')!r} needs at least two components"
        )

    parsed: list[dict[str, str]] = []
    keys: set[str] = set()
    for index, member in enumerate(members, start=1):
        if not isinstance(member, dict):
            raise ValueError(
                f"Split component {index} for {row.get('candidate_name')!r} must be an object"
            )
        decision = str(member.get("decision", "")).strip()
        name = str(member.get("skill_name", "")).strip()
        category = str(member.get("skill_category", "")).strip()
        if decision not in {"map_existing", "create_new"} or not name:
            raise ValueError(
                f"Split component {index} for {row.get('candidate_name')!r} "
                "needs map_existing/create_new and a skill_name"
            )
        if decision == "create_new" and not category:
            raise ValueError(
                f"New split component {name!r} needs a skill_category"
            )
        key = skill_name_key(name)
        if key in keys:
            raise ValueError(
                f"Split review for {row.get('candidate_name')!r} repeats component {name!r}"
            )
        keys.add(key)
        parsed.append(
            {"decision": decision, "skill_name": name, "skill_category": category}
        )
    return parsed


def _build_final_catalog(
    rows: list[dict[str, object]], seed_records: list[tuple[str, str, list[str]]]
) -> tuple[list[tuple[str, str, list[str]]], dict[str, dict[str, str]]]:
    records: dict[str, dict[str, object]] = {}
    alias_targets: dict[str, str] = {}
    seed_by_identity: dict[str, str] = {}
    for name, category, aliases in seed_records:
        key = skill_name_key(name)
        identity = skill_identity_key(name)
        existing_key = seed_by_identity.get(identity)
        if existing_key is not None:
            existing = records[existing_key]
            if existing["category"] != category:
                raise ValueError(
                    f"Conflicting bootstrap categories for equivalent skill: {name}"
                )
            canonical = str(existing["name"])
            if key != skill_name_key(canonical):
                prior_target = alias_targets.get(key)
                if prior_target and skill_identity_key(prior_target) != identity:
                    raise ValueError(f"Duplicate bootstrap skill/alias: {name}")
                alias_targets[key] = canonical
                existing["aliases"].add(name)
            canonical_key = skill_name_key(canonical)
            for alias in aliases:
                alias_key = skill_name_key(alias)
                if not alias_key or alias_key == canonical_key:
                    continue
                if alias_key in records and skill_identity_key(alias) != identity:
                    raise ValueError(f"Duplicate bootstrap skill/alias: {alias}")
                prior_target = alias_targets.get(alias_key)
                if prior_target and skill_identity_key(prior_target) != identity:
                    raise ValueError(f"Duplicate bootstrap skill/alias: {alias}")
                alias_targets[alias_key] = canonical
                existing["aliases"].add(alias)
            continue

        records[key] = {"name": name, "category": category, "aliases": set()}
        seed_by_identity[identity] = key
        for alias in aliases:
            alias_key = skill_name_key(alias)
            if alias_key in alias_targets or alias_key in records:
                raise ValueError(f"Duplicate bootstrap skill/alias: {alias}")
            alias_targets[alias_key] = name
            records[key]["aliases"].add(alias)

    def record_key_for(name: str) -> str | None:
        exact = skill_name_key(name)
        if exact in records:
            return exact
        identity = skill_identity_key(name)
        matches = [
            key for key, item in records.items()
            if skill_identity_key(str(item["name"])) == identity
        ]
        if not matches:
            return None
        return min(
            matches,
            key=lambda key: (
                skill_name_key(str(records[key]["name"])) != identity,
                str(records[key]["name"]).casefold(),
            ),
        )

    decisions: dict[str, dict[str, str]] = {}

    auto_new_categories: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("review_decision"):
            continue
        if (
            row.get("preview_status") == "ready_for_approval"
            and row.get("confidence_level") == "high"
            and row.get("suggestion_decision") == "new_skill"
        ):
            canonical = str(row.get("suggested_skill_name", "")).strip()
            category = str(row.get("suggested_skill_category", "")).strip()
            key = skill_identity_key(canonical)
            if key and category:
                auto_new_categories[key].add(category)
    conflicting_auto_new = {
        key
        for key, categories in auto_new_categories.items()
        if len(categories) > 1
        or (
            key in {skill_identity_key(str(item["name"])) for item in records.values()}
            and any(
                category
                != next(
                    item["category"]
                    for item in records.values()
                    if skill_identity_key(str(item["name"])) == key
                )
                for category in categories
            )
        )
    }

    def add_skill(name: str, category: str) -> str:
        key = skill_name_key(name)
        if not key:
            raise ValueError("A proposed canonical skill name cannot be empty")
        identity = skill_identity_key(name)
        if key in alias_targets and skill_identity_key(alias_targets[key]) != identity:
            raise ValueError(f"Proposed canonical name conflicts with an alias: {name}")
        existing_key = record_key_for(name)
        existing = records.get(existing_key) if existing_key is not None else None
        if existing is None:
            records[key] = {"name": name, "category": category, "aliases": set()}
            return name
        if existing["category"] != category and category:
            raise ValueError(f"Conflicting categories for canonical skill: {name}")
        canonical = str(existing["name"])
        canonical_key = skill_name_key(canonical)
        if key != canonical_key:
            alias_targets[key] = canonical
            existing["aliases"].add(name)
        return canonical

    def add_alias(alias: str, canonical: str) -> None:
        # Extraction can leave a leading conjunction attached to a single
        # skill (for example, ``and code review``). Keep the raw observation in
        # the review record, but persist the cleaned phrase as the alias.
        for connector in ("and", "or"):
            prefix = f"{connector} "
            if alias.casefold().startswith(prefix):
                alias = alias[len(prefix) :].strip()
                break
        alias_key = skill_name_key(alias)
        canonical_key = skill_name_key(canonical)
        if not alias_key or alias_key == canonical_key:
            return
        if len(split_composite_skill_name(alias, alias)) > 1:
            raise ValueError(
                f"Composite list {alias!r} cannot be stored as a single-skill alias; "
                "split it into individual skill components first"
            )
        if alias_key in records and alias_key != canonical_key:
            raise ValueError(f"Alias {alias!r} conflicts with a canonical skill")
        target = alias_targets.get(alias_key)
        if target and skill_name_key(target) != canonical_key:
            raise ValueError(f"Alias {alias!r} maps to more than one skill")
        if target and skill_name_key(target) == canonical_key:
            return
        if canonical_key not in records:
            raise ValueError(f"Target canonical skill is not in the rebuilt catalog: {canonical}")
        alias_targets[alias_key] = canonical
        records[canonical_key]["aliases"].add(alias)

    # Register manual canonicals first so map-existing rows can point to a
    # create-new decision that appears later in candidate order.
    for row in rows:
        decision = str(row.get("review_decision", "")).strip()
        if decision == "split_into_skills":
            for member in _parse_split_members(row):
                if member["decision"] == "create_new":
                    add_skill(member["skill_name"], member["skill_category"])
            continue
        if decision != "create_new":
            continue
        name = str(row.get("canonical_skill_name", "")).strip()
        category = str(row.get("skill_category", "")).strip()
        if not name or not category:
            raise ValueError(
                f"New-skill decision for {row.get('candidate_name')!r} lacks name/category"
            )
        add_skill(name, category)

    # Apply reviewed aliases before automatic high-confidence additions. A
    # manual mapping is stronger evidence than an automatic new-skill name;
    # this also lets that automatic candidate reuse the reviewed target below.
    for row in rows:
        decision = str(row.get("review_decision", "")).strip()
        if decision not in {"map_existing", "create_new"}:
            continue
        candidate = str(row.get("candidate_name", "")).strip()
        canonical = str(row.get("canonical_skill_name", "")).strip()
        if not canonical:
            raise ValueError(f"{decision} review for {candidate!r} lacks canonical name")
        canonical_key = record_key_for(canonical)
        if canonical_key is None:
            raise ValueError(
                f"Review for {candidate!r} points to unknown canonical {canonical!r}"
            )
        canonical = str(records[canonical_key]["name"])
        observed_names = row.get("observed_names", [candidate])
        if not isinstance(observed_names, list):
            observed_names = [candidate]
        for observed in observed_names:
            add_alias(str(observed), canonical)

    # Register confident automatic new skills after manual aliases. If the LLM
    # proposes a name that a reviewer explicitly mapped as an alias, the manual
    # mapping wins and the proposal is resolved to that reviewed canonical.
    for row in rows:
        if row.get("review_decision"):
            continue
        if not (
            row.get("preview_status") == "ready_for_approval"
            and row.get("confidence_level") == "high"
            and row.get("suggestion_decision") == "new_skill"
        ):
            continue
        name = str(row.get("suggested_skill_name", "")).strip()
        category = str(row.get("suggested_skill_category", "")).strip()
        if not name or not category:
            raise ValueError(
                f"Ready new-skill suggestion for {row.get('candidate_name')!r} is incomplete"
            )
        if skill_identity_key(name) in conflicting_auto_new:
            continue
        reviewed_target = alias_targets.get(skill_name_key(name))
        if reviewed_target and skill_identity_key(reviewed_target) != skill_identity_key(name):
            continue
        add_skill(name, category)

    for row in rows:
        candidate = str(row["candidate_name"]).strip()
        observed_names = row.get("observed_names", [])
        if not isinstance(observed_names, list):
            observed_names = [candidate]
        observed_names = [str(name).strip() for name in observed_names if str(name).strip()]
        if not observed_names:
            observed_names = [candidate]
        review_decision = str(row.get("review_decision", "")).strip()
        method = "human" if review_decision else "automatic"
        if review_decision == "split_into_skills":
            members = _parse_split_members(row)
            canonical_components: list[str] = []
            for member in members:
                component_key = record_key_for(member["skill_name"])
                if member["decision"] == "map_existing":
                    if component_key is None:
                        raise ValueError(
                            f"Split component {member['skill_name']!r} for {candidate!r} "
                            "is not an existing canonical in the rebuilt catalog"
                        )
                else:
                    add_skill(member["skill_name"], member["skill_category"])
                    component_key = record_key_for(member["skill_name"])
                assert component_key is not None
                canonical_components.append(str(records[component_key]["name"]))

            decisions[skill_name_key(candidate)] = {
                "resolution_status": "split_applied",
                "resolution_method": method,
                "suggestion_decision": str(row.get("suggestion_decision") or "uncertain"),
                "confidence_level": str(row.get("confidence_level") or "low"),
                "suggested_skill_name": "",
                "suggested_skill_category": "",
                "suggestion_reason": (
                    "Applied manual split into: "
                    + ", ".join(canonical_components)
                ),
            }
            continue
        if review_decision == "create_new":
            canonical = str(row.get("canonical_skill_name", "")).strip()
            category = str(row.get("skill_category", "")).strip()
            if not canonical or not category:
                raise ValueError(f"Create-new review for {candidate!r} lacks name/category")
            canonical = add_skill(canonical, category)
            category = str(records[skill_name_key(canonical)]["category"])
            for observed in observed_names:
                add_alias(observed, canonical)
            decisions[skill_name_key(candidate)] = {
                "resolution_status": "created_approved",
                "resolution_method": method,
                "suggestion_decision": "new_skill",
                "confidence_level": "high",
                "suggested_skill_name": canonical,
                "suggested_skill_category": category,
                "suggestion_reason": "Applied from saved manual review decision.",
            }
            continue
        if review_decision == "map_existing":
            canonical = str(row.get("canonical_skill_name", "")).strip()
            if not canonical:
                raise ValueError(f"Map-existing review for {candidate!r} lacks canonical name")
            canonical_key = record_key_for(canonical)
            if canonical_key is None:
                raise ValueError(
                    f"Map-existing review for {candidate!r} points to unknown canonical {canonical!r}"
                )
            canonical = str(records[canonical_key]["name"])
            decisions[skill_name_key(candidate)] = {
                "resolution_status": "mapped_existing",
                "resolution_method": method,
                "suggestion_decision": "existing_skill",
                "confidence_level": "high",
                "suggested_skill_name": canonical,
                "suggested_skill_category": "",
                "suggestion_reason": "Applied from saved manual review decision.",
            }
            for observed in observed_names:
                add_alias(observed, canonical)
            continue
        if review_decision == "ignore":
            decisions[skill_name_key(candidate)] = {
                "resolution_status": "ignored",
                "resolution_method": method,
                "suggestion_decision": "not_skill",
                "confidence_level": "high",
                "suggested_skill_name": "",
                "suggested_skill_category": "",
                "suggestion_reason": "Ignored by manual review.",
            }
            continue

        preview_status = str(row.get("preview_status", ""))
        suggestion_decision = str(row.get("suggestion_decision", ""))
        confidence = str(row.get("confidence_level", ""))
        suggested_name = str(row.get("suggested_skill_name", "")).strip()
        category = str(row.get("suggested_skill_category", "")).strip()
        auto_accepted = preview_status == "ready_for_approval" and confidence == "high"
        if (
            auto_accepted
            and suggestion_decision == "new_skill"
            and skill_identity_key(suggested_name) in conflicting_auto_new
        ):
            auto_accepted = False
        if auto_accepted and suggestion_decision == "existing_skill":
            canonical_key = record_key_for(suggested_name)
            if canonical_key is None:
                reviewed_target = alias_targets.get(skill_name_key(suggested_name))
                if reviewed_target:
                    canonical_key = record_key_for(reviewed_target)
            if canonical_key is None:
                raise ValueError(
                    f"Suggested existing skill {suggested_name!r} is absent from the rebuilt catalog"
                )
            suggested_name = str(records[canonical_key]["name"])
            for observed in observed_names:
                add_alias(observed, suggested_name)
            decisions[skill_name_key(candidate)] = {
                "resolution_status": "mapped_existing",
                "resolution_method": "automatic",
                "suggestion_decision": "existing_skill",
                "confidence_level": confidence,
                "suggested_skill_name": suggested_name,
                "suggested_skill_category": "",
                "suggestion_reason": str(row.get("suggestion_reason", "")),
            }
        elif auto_accepted and suggestion_decision == "new_skill":
            if not suggested_name or not category:
                raise ValueError(f"Ready new-skill suggestion for {candidate!r} is incomplete")
            reviewed_target = alias_targets.get(skill_name_key(suggested_name))
            if reviewed_target:
                canonical_key = record_key_for(reviewed_target)
                if canonical_key is None:
                    raise ValueError(
                        f"Reviewed alias target {reviewed_target!r} is absent from the rebuilt catalog"
                    )
                suggested_name = str(records[canonical_key]["name"])
                for observed in observed_names:
                    add_alias(observed, suggested_name)
                decisions[skill_name_key(candidate)] = {
                    "resolution_status": "mapped_existing",
                    "resolution_method": "automatic",
                    "suggestion_decision": "existing_skill",
                    "confidence_level": confidence,
                    "suggested_skill_name": suggested_name,
                    "suggested_skill_category": "",
                    "suggestion_reason": (
                        "Mapped to a canonical selected by a manual review because "
                        "the suggested new name is already a reviewed alias."
                    ),
                }
                continue
            suggested_name = add_skill(suggested_name, category)
            category = str(records[skill_name_key(suggested_name)]["category"])
            for observed in observed_names:
                add_alias(observed, suggested_name)
            decisions[skill_name_key(candidate)] = {
                "resolution_status": "created_approved",
                "resolution_method": "automatic",
                "suggestion_decision": "new_skill",
                "confidence_level": confidence,
                "suggested_skill_name": suggested_name,
                "suggested_skill_category": category,
                "suggestion_reason": str(row.get("suggestion_reason", "")),
            }
        else:
            decisions[skill_name_key(candidate)] = {
                "resolution_status": "pending_review",
                "resolution_method": "automatic",
                "suggestion_decision": suggestion_decision or "uncertain",
                "confidence_level": confidence or "low",
                "suggested_skill_name": suggested_name,
                "suggested_skill_category": category,
                "suggestion_reason": str(row.get("suggestion_reason", ""))
                or "Not confidently resolved; awaiting manual review.",
            }

    final_records = [
        (str(item["name"]), str(item["category"]), sorted(item["aliases"], key=str.casefold))
        for item in records.values()
    ]
    return final_records, decisions


def _load_reviewed_database_targets(
    rows: list[dict[str, object]],
    seed_records: list[tuple[str, str, list[str]]],
) -> list[tuple[str, str, list[str]]]:
    """Keep explicitly selected legacy DB canonicals in the rebuilt catalog.

    Review allows mapping to a canonical from the current database, but a clean
    rebuild starts from the bootstrap file. Bring back only DB skills explicitly
    selected by a map-existing decision (including split components), rather
    than carrying the entire old catalog into the new one.
    """
    selected: dict[str, str] = {}
    seed_identities = {skill_identity_key(name) for name, _, _ in seed_records}
    for row in rows:
        decision = str(row.get("review_decision", "")).strip()
        if decision == "map_existing":
            name = str(row.get("canonical_skill_name", "")).strip()
            if name and skill_identity_key(name) not in seed_identities:
                selected[skill_name_key(name)] = name
        elif decision == "split_into_skills":
            for member in _parse_split_members(row):
                name = member["skill_name"]
                if (
                    member["decision"] == "map_existing"
                    and skill_identity_key(name) not in seed_identities
                ):
                    selected[skill_name_key(name)] = name

    if not selected:
        return []

    with get_database_connection() as connection:
        database_rows = connection.execute(
            "SELECT skill_name, skill_category FROM core.skills"
        ).fetchall()
    database_by_key = {
        skill_name_key(str(name)): (str(name), str(category or "other"))
        for name, category in database_rows
    }
    records: list[tuple[str, str, list[str]]] = []
    for key in selected:
        existing = database_by_key.get(key)
        if existing is not None:
            name, category = existing
            records.append((name, category, []))
        # If the target is neither in the bootstrap nor the old DB, leave it
        # absent so _build_final_catalog raises its usual actionable error.
    return records


def _queue_rows(
    rows: list[dict[str, object]], decisions: dict[str, dict[str, str]]
) -> list[dict[str, object]]:
    return [
        {
            **row,
            **decisions[skill_name_key(str(row["candidate_name"]))],
        }
        for row in rows
        if skill_name_key(str(row["candidate_name"])) in decisions
    ]


def _write_split_checkpoints(
    checkpoints: list[tuple[str, list[dict[str, object]]]],
    rows: list[dict[str, object]],
    output_dir: Path,
) -> tuple[Path | None, int]:
    """Write transformed copies for loading; preserve the raw extraction checkpoints."""
    replacement_by_name: dict[str, list[str]] = {}
    for row in rows:
        if str(row.get("review_decision", "")).strip() != "split_into_skills":
            continue
        components = [
            member["skill_name"] for member in _parse_split_members(row)
        ]
        observed_names = row.get("observed_names", [])
        if not isinstance(observed_names, list):
            observed_names = [str(row.get("candidate_name", ""))]
        if not observed_names:
            observed_names = [str(row.get("candidate_name", ""))]
        for observed in observed_names:
            key = skill_name_key(str(observed))
            previous = replacement_by_name.get(key)
            if previous is not None and previous != components:
                raise ValueError(
                    f"The extracted name {observed!r} has conflicting split decisions"
                )
            replacement_by_name[key] = components

    if not replacement_by_name:
        return None, 0

    replacements = 0
    for run_id, entries in checkpoints:
        transformed_entries: list[dict[str, object]] = []
        for entry in entries:
            transformed_entry = dict(entry)
            extracted_skills = entry.get("skills")
            if not isinstance(extracted_skills, list):
                raise ValueError(
                    f"Checkpoint {run_id} has no skills list while applying split decisions"
                )
            transformed_skills: list[dict[str, object]] = []
            for extracted in extracted_skills:
                if not isinstance(extracted, dict):
                    raise ValueError(f"Checkpoint {run_id} contains a malformed skill")
                raw_name = str(extracted.get("raw_skill_name", ""))
                components = replacement_by_name.get(skill_name_key(raw_name))
                if components is None:
                    transformed_skills.append(dict(extracted))
                    continue
                replacements += 1
                for component in components:
                    transformed_skill = dict(extracted)
                    transformed_skill["raw_skill_name"] = component
                    transformed_skills.append(transformed_skill)
            transformed_entry["skills"] = transformed_skills
            transformed_entries.append(transformed_entry)
        save_skill_results(
            transformed_entries, run_id=run_id, output_dir=output_dir
        )

    if replacements == 0:
        raise ValueError(
            "Split decisions did not match any raw skill in the saved checkpoints; "
            "database reset was not started."
        )
    return output_dir, replacements


def _reset_seed_and_record_candidates(
    records: list[tuple[str, str, list[str]]],
    queue_rows: list[dict[str, object]],
) -> tuple[int, int, int]:
    with get_database_connection() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM market.career_skill_stats")
            connection.execute("DELETE FROM market.job_skills")
            connection.execute("DELETE FROM core.skill_candidate_reviews")
            connection.execute("DELETE FROM core.skill_aliases")
            connection.execute("DELETE FROM core.skills")

            skill_ids: dict[str, int] = {}
            aliases_to_add: list[tuple[int, str]] = []
            for name, category, aliases in records:
                skill_id = connection.execute(
                    """
                    INSERT INTO core.skills (skill_name, skill_category, catalog_status)
                    VALUES (%s, %s, 'approved') RETURNING skill_id
                    """,
                    (name, category),
                ).fetchone()[0]
                skill_ids[skill_name_key(name)] = skill_id
                aliases_to_add.extend((skill_id, alias) for alias in aliases)
            for skill_id, alias in aliases_to_add:
                connection.execute(
                    "INSERT INTO core.skill_aliases (skill_id, alias) VALUES (%s, %s)",
                    (skill_id, alias),
                )

            for row in queue_rows:
                candidate_name = str(row["candidate_name"])
                suggestion_name = str(row.get("suggested_skill_name", ""))
                resolved_id = (
                    skill_ids.get(skill_name_key(suggestion_name))
                    if row["resolution_status"] in {"mapped_existing", "created_approved"}
                    else None
                )
                examples = [
                    {"job_title": title, "evidence": evidence}
                    for title, evidence in zip(
                        row.get("example_job_titles", []),
                        row.get("example_evidence", []),
                        strict=False,
                    )
                ]
                connection.execute(
                    """
                    INSERT INTO core.skill_candidate_reviews (
                        candidate_key, candidate_name, observed_names,
                        resolution_status, resolution_method, suggestion_decision,
                        confidence_level, suggested_skill_name, suggested_skill_category,
                        resolved_skill_id, occurrence_count, job_count, examples,
                        rationale, last_seen_run_id
                    ) VALUES (
                        %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s, %s
                    )
                    """,
                    (
                        skill_name_key(candidate_name),
                        candidate_name,
                        json.dumps(row.get("observed_names", [candidate_name]), ensure_ascii=False),
                        row["resolution_status"],
                        row["resolution_method"],
                        row["suggestion_decision"],
                        row["confidence_level"],
                        suggestion_name or None,
                        row.get("suggested_skill_category") or None,
                        resolved_id,
                        int(row.get("occurrence_count", 0)),
                        int(row.get("job_count", 0)),
                        json.dumps(examples, ensure_ascii=False),
                        str(row.get("suggestion_reason", "")),
                        (row.get("source_runs") or [None])[-1],
                    ),
                )

    pending_count = sum(row["resolution_status"] == "pending_review" for row in queue_rows)
    created_count = sum(row["resolution_status"] == "created_approved" for row in queue_rows)
    mapped_count = sum(row["resolution_status"] == "mapped_existing" for row in queue_rows)
    return len(records), pending_count, created_count + mapped_count


def _backup_and_validate_postings(
    checkpoints: list[tuple[str, list[dict[str, object]]]], folder: Path
) -> list[tuple[object, object, str]]:
    windows = _backup_database(folder / "database")
    _validate_posting_coverage(checkpoints)
    return windows


def _validate_posting_coverage(
    checkpoints: list[tuple[str, list[dict[str, object]]]],
) -> None:
    checkpoint_job_ids = {
        str(job.get("job_id"))
        for _, entries in checkpoints
        for entry in entries
        if isinstance((job := entry.get("job")), dict)
        and isinstance(job.get("job_id"), str)
        and job.get("job_id", "").strip()
    }
    with get_database_connection() as connection:
        database_job_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT provider_job_id FROM market.job_postings"
            ).fetchall()
        }
    missing = database_job_ids - checkpoint_job_ids
    if missing:
        raise ValueError(
            f"Cannot rebuild all job-skill links: {len(missing)} database postings "
            "are absent from the available skill checkpoints. Database reset was not started."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", type=Path, default=CHECKPOINT_DIR)
    parser.add_argument("--seed-file", type=Path, default=PROJECT_ROOT / "config" / "skills.yaml")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--request-interval", type=float, default=10.0)
    parser.add_argument("--suggest-limit", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument(
        "--reextract",
        action="store_true",
        help="Explicitly re-run job-level extraction before rebuilding; default reuses saved checkpoints",
    )
    parser.add_argument("--force-all-extraction", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    if arguments.apply == arguments.dry_run:
        parser.error("Choose exactly one of --dry-run or --apply")
    if arguments.request_interval < 0:
        parser.error("--request-interval must be non-negative")
    if arguments.suggest_limit < 0 or arguments.batch_size < 1:
        parser.error("--suggest-limit must be non-negative and --batch-size positive")
    if arguments.force_all_extraction and not arguments.reextract:
        parser.error("--force-all-extraction requires --reextract")

    checkpoints = load_skill_checkpoints(arguments.checkpoint_dir)
    total_jobs = sum(len(entries) for _, entries in checkpoints)
    completed_before = sum(
        entry.get("extraction_status") == "completed"
        for _, entries in checkpoints
        for entry in entries
    )
    _, prior_preview = _read_prior_preview()
    prior_decisions = sum(bool(row.get("review_decision", "").strip()) for row in prior_preview)
    print(
        f"Checkpoint runs={len(checkpoints)}, jobs={total_jobs}, "
        f"currently_completed={completed_before}, prior_review_decisions={prior_decisions}"
    )
    if arguments.dry_run:
        bootstrap = load_bootstrap_catalog(arguments.seed_file)
        before_rows, before_summary = build_catalog_rebuild_preview(
            checkpoints, bootstrap, split_composites=False
        )
        after_rows, after_summary = build_catalog_rebuild_preview(
            checkpoints, bootstrap, split_composites=True
        )
        if PREVIEW_FILE.is_file():
            _resume_existing_rows(after_rows, PREVIEW_FILE)
        finalize_preview_suggestions(after_rows)
        dry_run_seed_records = load_skill_records(arguments.seed_file)
        dry_run_database_records = _load_reviewed_database_targets(
            after_rows, dry_run_seed_records
        )
        dry_run_catalog, _ = _build_final_catalog(
            after_rows, [*dry_run_seed_records, *dry_run_database_records]
        )
        before_composite_groups = sum(
            "," in str(row.get("candidate_name", ""))
            or ";" in str(row.get("candidate_name", ""))
            for row in before_rows
        )
        after_composite_groups = sum(
            "," in str(row.get("candidate_name", ""))
            or ";" in str(row.get("candidate_name", ""))
            for row in after_rows
        )
        current_unreviewed = [
            row for row in prior_preview if not row.get("review_decision", "").strip()
        ]
        print(
            json.dumps(
                {
                    "preview_only": True,
                    "job_level_extraction_requests": 0,
                    "database_writes": 0,
                    "before_composite_split": {
                        "candidate_groups": len(before_rows),
                        "candidate_occurrences": before_summary["candidate_occurrences"],
                        "comma_or_semicolon_groups": before_composite_groups,
                    },
                    "after_composite_split": {
                        "candidate_groups": len(after_rows),
                        "candidate_occurrences": after_summary["candidate_occurrences"],
                        "matched_component_occurrences": after_summary[
                            "seed_matched_occurrences"
                        ],
                        "composite_occurrences_split": after_summary[
                            "composite_occurrences_split"
                        ],
                        "components_created": after_summary[
                            "split_components_created"
                        ],
                        "split_components_matched": after_summary[
                            "split_components_matched"
                        ],
                        "split_components_still_unmatched": after_summary[
                            "split_components_unmatched"
                        ],
                        "comma_or_semicolon_groups": after_composite_groups,
                    },
                    "candidate_group_delta_after_split": len(after_rows)
                    - len(before_rows),
                    "saved_preview": {
                        "groups": len(prior_preview),
                        "unreviewed_groups": len(current_unreviewed),
                    },
                    "saved_review_decisions_validated": True,
                    "planned_catalog_skills": len(dry_run_catalog),
                    "final_manual_review_count": None,
                    "llm_candidate_suggestions": 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(
            "Dry run uses saved checkpoints and performs no Gemini calls, "
            "file writes, or database writes. It reads the current DB only to "
            "retain explicitly selected map-existing canonicals. Final review count requires "
            "candidate suggestions and is intentionally not estimated here."
        )
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = arguments.backup_dir or BACKUP_ROOT / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    _backup_checkpoints(checkpoints, backup_dir, arguments.checkpoint_dir)
    if PREVIEW_FILE.is_file():
        shutil.copy2(PREVIEW_FILE, backup_dir / "catalog_rebuild_preview_before.csv")

    try:
        _validate_posting_coverage(checkpoints)
        if arguments.reextract:
            updated_checkpoints, extracted_count, fallback_count = _reextract_checkpoints(
                checkpoints,
                request_interval=arguments.request_interval,
                force_all=arguments.force_all_extraction,
                output_dir=arguments.checkpoint_dir,
            )
        else:
            updated_checkpoints = checkpoints
            extracted_count = fallback_count = 0
            print("Reusing saved extraction checkpoints; job-level extraction was not run.")
    except Exception as error:
        print(
            f"Checkpoint preparation did not complete; database was not reset. "
            f"Checkpoint backup: {backup_dir / 'checkpoints'}; error: {error}"
        )
        raise

    bootstrap = load_bootstrap_catalog(arguments.seed_file)
    rows, summary = build_catalog_rebuild_preview(updated_checkpoints, bootstrap)
    if PREVIEW_FILE.exists():
        _resume_existing_rows(rows, PREVIEW_FILE)
    finalize_preview_suggestions(rows)
    save_catalog_rebuild_preview(rows, PREVIEW_FILE)
    suggestion_requests = _suggest_candidates(
        rows,
        bootstrap,
        limit=arguments.suggest_limit,
        batch_size=arguments.batch_size,
        request_interval=arguments.request_interval,
    )
    finalize_preview_suggestions(rows)
    save_catalog_rebuild_preview(rows, PREVIEW_FILE)

    seed_records = load_skill_records(arguments.seed_file)
    selected_database_records = _load_reviewed_database_targets(rows, seed_records)
    final_records, decisions = _build_final_catalog(
        rows, [*seed_records, *selected_database_records]
    )
    queue_rows = _queue_rows(rows, decisions)
    windows = _backup_and_validate_postings(updated_checkpoints, backup_dir)
    try:
        split_checkpoint_dir, split_occurrence_count = _write_split_checkpoints(
            updated_checkpoints,
            rows,
            backup_dir / "split_applied_checkpoints",
        )
    except Exception as error:
        print(f"Split validation failed; database reset was not started: {error}")
        raise

    try:
        catalog_count, pending_count, auto_resolved_count = _reset_seed_and_record_candidates(
            final_records, queue_rows
        )
    except Exception as error:
        print(f"Catalog transaction failed; database changes were rolled back: {error}")
        raise

    loaded_by_run: dict[str, dict[str, int]] = {}
    for run_id, _ in updated_checkpoints:
        loaded_by_run[run_id] = load_job_skills_from_run(
            run_id,
            output_dir=split_checkpoint_dir or arguments.checkpoint_dir,
        )

    aggregated: list[dict[str, object]] = []
    for start, end, basis in windows:
        result = refresh_career_skill_stats(start, end, date_basis=basis)
        aggregated.append({"start": start, "end": end, "basis": basis, **result})

    total_fallback_count = sum(
        bool(entry.get("catalog_rebuild_extraction_fallback"))
        for _, entries in updated_checkpoints
        for entry in entries
    )
    total_reextracted_count = sum(
        bool(entry.get("catalog_rebuild_extracted_at"))
        for _, entries in updated_checkpoints
        for entry in entries
    ) - total_fallback_count

    print(
        json.dumps(
            {
                "backup_dir": str(backup_dir),
                "runs": len(updated_checkpoints),
                "jobs_reextracted_this_run": extracted_count - fallback_count,
                "jobs_reextracted_total": total_reextracted_count,
                "jobs_reused_prior_extraction_after_quote_error_total": total_fallback_count,
                "suggestion_requests": suggestion_requests,
                "candidate_groups": summary["candidate_groups"],
                "catalog_skills": catalog_count,
                "auto_resolved_candidate_groups": auto_resolved_count,
                "pending_review_candidates": pending_count,
                "split_candidates_applied": sum(
                    row["resolution_status"] == "split_applied" for row in queue_rows
                ),
                "split_extracted_occurrences_replaced": split_occurrence_count,
                "loaded_by_run": loaded_by_run,
                "aggregates": aggregated,
                "database_reset_scope": [*TABLES_TO_BACK_UP],
            },
            ensure_ascii=False,
            default=_json_default,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
