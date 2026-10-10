"""Create an offline preview for a clean skill-catalog rebuild."""

import argparse
import csv
import json
from pathlib import Path
import sys
import time

from src.skills.candidate_suggester import suggest_skill_candidates
from src.skills.catalog_rebuild_preview import (
    build_catalog_rebuild_preview,
    finalize_preview_suggestions,
    load_bootstrap_catalog,
    load_skill_checkpoints,
    scan_suggested_duplicates,
    save_catalog_rebuild_preview,
)
from src.skills.gemini_client import gemini_generate
from src.skills.normalizer import (
    load_skill_catalog,
    skill_name_key,
    split_composite_skill_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKPOINT_DIR = PROJECT_ROOT / "data" / "processed" / "skill_extraction"
DEFAULT_SEED_FILE = PROJECT_ROOT / "config" / "skills.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "skill_candidates" / "catalog_rebuild_preview.csv"
SUGGESTION_FORMAT_MAX_ATTEMPTS = 3


def _resume_existing_rows(rows: list[dict[str, object]], output_path: Path) -> None:
    """Keep prior suggestions and manual decisions when the preview is unchanged."""
    if not output_path.exists():
        return
    # Evidence payloads can exceed csv's small default field-size limit.
    csv.field_size_limit(min(sys.maxsize, 2_147_483_647))
    with output_path.open(encoding="utf-8-sig", newline="") as source:
        prior_rows = list(csv.DictReader(source))
    prior_by_key: dict[tuple[str, tuple[str, ...]], dict[str, str]] = {}
    for prior in prior_rows:
        try:
            names = tuple(json.loads(prior.get("observed_names", "[]")))
        except (TypeError, json.JSONDecodeError):
            continue
        prior_by_key[(prior.get("candidate_name", ""), names)] = prior
    split_reviews: list[dict[str, str]] = []
    for prior in prior_rows:
        if prior.get("review_decision", "").strip() != "split_into_skills":
            continue
        try:
            observed_names = json.loads(prior.get("observed_names", "[]"))
            members: object = prior.get("split_skills", "[]")
            while isinstance(members, str):
                members = json.loads(members)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(observed_names, list) or not isinstance(members, list):
            continue
        for source_name in observed_names:
            if not isinstance(source_name, str):
                continue
            parts = split_composite_skill_name(source_name, source_name)
            if len(parts) != len(members):
                continue
            for part, member in zip(parts, members, strict=True):
                if not isinstance(member, dict):
                    continue
                if member.get("decision") not in {"map_existing", "create_new"}:
                    continue
                split_reviews.append(
                    {
                        "component_key": skill_name_key(part),
                        "decision": str(member["decision"]),
                        "canonical_skill_name": str(member.get("skill_name", "")),
                        "skill_category": str(member.get("skill_category", "")),
                    }
                )

    for row in rows:
        key = (str(row["candidate_name"]), tuple(row["observed_names"]))
        prior = prior_by_key.get(key)
        if prior is None:
            continue
        for column in (
            "suggestion_decision",
            "suggested_skill_name",
            "suggested_skill_category",
            "confidence_level",
            "suggestion_reason",
            "review_decision",
            "canonical_skill_name",
            "skill_category",
            "split_skills",
        ):
            # Old decisions that mapped a comma/semicolon list as one skill are
            # unsafe under component matching. Saved split decisions are handled
            # separately below and expanded to their individual components.
            is_composite = len(
                split_composite_skill_name(
                    str(prior.get("candidate_name", "")),
                    str(prior.get("candidate_name", "")),
                )
            ) > 1
            if is_composite and prior.get("review_decision") != "split_into_skills":
                if column in {
                    "review_decision",
                    "canonical_skill_name",
                    "skill_category",
                    "split_skills",
                }:
                    continue
            if prior.get(column):
                row[column] = prior[column]
        duplicate_names = {
            value.strip()
            for value in str(row.get("possible_duplicate_candidates", "")).split(";")
            if value.strip()
        }
        duplicate_names.update(
            value.strip()
            for value in prior.get("possible_duplicate_candidates", "").split(";")
            if value.strip()
        )
        row["possible_duplicate_candidates"] = "; ".join(
            sorted(duplicate_names, key=str.casefold)
        )

    rows_by_component: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        names = [str(row.get("candidate_name", ""))]
        observed = row.get("observed_names", [])
        if isinstance(observed, list):
            names.extend(str(name) for name in observed)
        for name in names:
            rows_by_component.setdefault(skill_name_key(name), []).append(row)
    for saved in split_reviews:
        if not saved["canonical_skill_name"]:
            continue
        for row in rows_by_component.get(saved["component_key"], []):
            if row.get("review_decision"):
                continue
            row["review_decision"] = saved["decision"]
            row["canonical_skill_name"] = saved["canonical_skill_name"]
            row["skill_category"] = saved["skill_category"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Legacy no-op: prior suggestions/manual decisions are now preserved by default",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Start a new preview without carrying suggestions/manual decisions from the output CSV",
    )
    parser.add_argument(
        "--skip-duplicate-scan",
        action="store_true",
        help="Skip the additional Gemini pass that flags possible duplicate proposals",
    )
    parser.add_argument(
        "--compare-database-catalog",
        action="store_true",
        help="Add read-only exact/near matches from the current PostgreSQL skill catalog",
    )
    parser.add_argument(
        "--suggest-limit",
        type=int,
        default=0,
        metavar="N",
        help="Ask Gemini to suggest outcomes for the top N candidate groups (default: 0)",
    )
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--request-interval", type=float, default=10.0)
    arguments = parser.parse_args()

    try:
        if arguments.suggest_limit < 0:
            raise ValueError("--suggest-limit must be zero or greater")
        if arguments.batch_size < 1:
            raise ValueError("--batch-size must be at least 1")
        if arguments.request_interval < 0:
            raise ValueError("--request-interval must be zero or greater")
        catalog = load_bootstrap_catalog(arguments.seed_file)
        checkpoints = load_skill_checkpoints(arguments.checkpoint_dir)
        rows, summary = build_catalog_rebuild_preview(checkpoints, catalog)
        if arguments.compare_database_catalog:
            from src.skills.catalog_rebuild_preview import add_database_catalog_comparison

            add_database_catalog_comparison(rows, load_skill_catalog())
        if not arguments.fresh:
            _resume_existing_rows(rows, arguments.output)
        finalize_preview_suggestions(rows)
        save_catalog_rebuild_preview(rows, arguments.output)

        request_count = 0
        suggestion_limit = min(arguments.suggest_limit, len(rows))
        candidate_pool = [str(row["candidate_name"]) for row in rows[:200]]
        to_suggest = [
            row for row in rows[:suggestion_limit] if not row["suggestion_decision"]
        ]
        for start in range(0, len(to_suggest), arguments.batch_size):
            if request_count:
                time.sleep(arguments.request_interval)
            batch = to_suggest[start : start + arguments.batch_size]
            for attempt in range(1, SUGGESTION_FORMAT_MAX_ATTEMPTS + 1):
                try:
                    suggestions = suggest_skill_candidates(
                        batch,
                        catalog,
                        generate=gemini_generate,
                        include_candidate_ids=False,
                        candidate_pool=candidate_pool,
                    )
                    break
                except ValueError as error:
                    if attempt == SUGGESTION_FORMAT_MAX_ATTEMPTS:
                        raise RuntimeError(
                            "Gemini returned an invalid candidate response after "
                            f"{SUGGESTION_FORMAT_MAX_ATTEMPTS} attempts; no database "
                            f"or checkpoint data was changed: {error}"
                        ) from error
                    if arguments.request_interval:
                        time.sleep(arguments.request_interval * attempt)
            for row, suggestion in zip(batch, suggestions, strict=True):
                row.update(suggestion)
            request_count += 1
            finalize_preview_suggestions(rows)
            save_catalog_rebuild_preview(rows, arguments.output)
        duplicate_scan_count = 0
        if not arguments.skip_duplicate_scan and suggestion_limit > 1:
            for attempt in range(1, SUGGESTION_FORMAT_MAX_ATTEMPTS + 1):
                try:
                    duplicate_scan_count = scan_suggested_duplicates(
                        rows[:suggestion_limit], generate=gemini_generate
                    )
                    break
                except ValueError as error:
                    if attempt == SUGGESTION_FORMAT_MAX_ATTEMPTS:
                        raise RuntimeError(
                            "Gemini duplicate scan returned an invalid response after "
                            f"{SUGGESTION_FORMAT_MAX_ATTEMPTS} attempts: {error}"
                        ) from error
                    if arguments.request_interval:
                        time.sleep(arguments.request_interval * attempt)
        finalize_preview_suggestions(rows)
        report_path = save_catalog_rebuild_preview(rows, arguments.output)
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        parser.error(str(error))

    ready = sum(row["preview_status"] == "ready_for_approval" for row in rows)
    manual = sum(row["preview_status"] == "manual_review" for row in rows)
    waiting = sum(row["preview_status"] == "needs_llm_suggestion" for row in rows)
    duplicate_rows = sum(bool(row["possible_duplicate_candidates"]) for row in rows)
    print(
        f"Offline skill-catalog preview written: {report_path} "
        f"({summary}, ready_for_approval={ready}, manual_review={manual}, "
        f"needs_llm_suggestion={waiting}, suggestion_requests={request_count}, "
        f"duplicate_scan_candidates={duplicate_rows})"
    )
    print("No database or skill-checkpoint data was changed.")


if __name__ == "__main__":
    main()
