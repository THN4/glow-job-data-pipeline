"""Print canonical skill names selected for the next catalog rebuild.

The list combines saved manual create/split decisions and high-confidence
automatic approvals accepted by the rebuild
logic. Candidates still awaiting a manual decision are excluded. Pass
--manual-decisions-only to exclude automatic approvals. The preview is read
locally; this script does not query or change DB.

Examples:
    python -m scripts.market.list_skill_catalog_rebuild_names
    python -m scripts.market.list_skill_catalog_rebuild_names --output catalog_names.txt
    python -m scripts.market.list_skill_catalog_rebuild_names --search "machine learning"
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from scripts.market.rebuild_skill_catalog_from_checkpoints import (
    PREVIEW_FILE,
    _build_final_catalog,
)
from src.shared.skill_normalization.normalizer import skill_identity_key


PROJECT_ROOT = Path(__file__).resolve().parents[2]
def _decode_json(value: object, *, field: str, candidate: str) -> object:
    decoded = value
    while isinstance(decoded, str):
        try:
            decoded = json.loads(decoded)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid {field} JSON for {candidate!r}: {error}") from error
    return decoded


def _load_preview(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(f"Preview CSV not found: {path}")
    csv.field_size_limit(min(sys.maxsize, 2_147_483_647))
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        candidate = str(row.get("candidate_name", ""))
        observed = _decode_json(
            row.get("observed_names", "[]"),
            field="observed_names",
            candidate=candidate,
        )
        if not isinstance(observed, list):
            raise ValueError(f"observed_names for {candidate!r} must be a JSON list")
        row["observed_names"] = observed
    return rows


def _separate_map_targets(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], set[str]]:
    """Keep map decisions from blocking name listing; report absent targets separately."""
    build_rows: list[dict[str, object]] = []
    mapped_targets: set[str] = set()
    for row in rows:
        decision = str(row.get("review_decision", "")).strip()
        candidate = str(row.get("candidate_name", ""))
        if decision == "map_existing":
            target = str(row.get("canonical_skill_name", "")).strip()
            if target:
                mapped_targets.add(target)
            build_rows.append({**row, "review_decision": "ignore"})
            continue
        if decision == "split_into_skills":
            members = _decode_json(
                row.get("split_skills", "[]"),
                field="split_skills",
                candidate=candidate,
            )
            if not isinstance(members, list):
                raise ValueError(f"split_skills for {candidate!r} must be a JSON list")
            new_members: list[dict[str, object]] = []
            for index, member in enumerate(members, start=1):
                if not isinstance(member, dict):
                    raise ValueError(
                        f"Split component {index} for {candidate!r} must be an object"
                    )
                name = str(member.get("skill_name", "")).strip()
                if member.get("decision") == "map_existing":
                    if name:
                        mapped_targets.add(name)
                    continue
                if member.get("decision") == "create_new":
                    new_members.append(member)
            build_rows.append({**row, "review_decision": "ignore"})
            for index, member in enumerate(new_members, start=1):
                name = str(member.get("skill_name", "")).strip()
                build_rows.append(
                    {
                        "candidate_name": f"{candidate} [split {index}]",
                        "observed_names": [name],
                        "review_decision": "create_new",
                        "canonical_skill_name": name,
                        "skill_category": str(member.get("skill_category", "")).strip(),
                        "preview_status": "manual_review",
                        "suggestion_decision": "new_skill",
                        "confidence_level": "high",
                        "suggested_skill_name": name,
                        "suggested_skill_category": str(member.get("skill_category", "")).strip(),
                    }
                )
            continue
        build_rows.append(row)
    return build_rows, mapped_targets


def _get_catalog_names(
    preview_rows: list[dict[str, object]],
) -> tuple[list[str], list[str]]:
    build_rows, mapped_targets = _separate_map_targets(preview_rows)
    final_records, _ = _build_final_catalog(build_rows, [])
    names = sorted({name for name, _, _ in final_records}, key=lambda name: name.casefold())
    known_identities = {skill_identity_key(name) for name in names}
    missing_targets = sorted(
        {
            target
            for target in mapped_targets
            if skill_identity_key(target) not in known_identities
        },
        key=str.casefold,
    )
    return names, missing_targets


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--preview", type=Path, default=PREVIEW_FILE)
    parser.add_argument("--search", help="Case-insensitive substring of a canonical name")
    parser.add_argument(
        "--manual-decisions-only",
        action="store_true",
        help="Exclude undecided high-confidence suggestions accepted by the rebuild logic",
    )
    parser.add_argument("--output", type=Path, help="Write one canonical name per line")
    arguments = parser.parse_args()

    try:
        preview_rows = _load_preview(arguments.preview)
        if arguments.manual_decisions_only:
            # The apply builder also auto-accepts some high-confidence rows.
            # Keep the default list aligned with the user's manual-review
            # checkpoint: only saved human decisions count as reviewed.
            preview_rows = [
                row
                for row in preview_rows
                if str(row.get("review_decision", "")).strip()
            ]
        names, missing_targets = _get_catalog_names(preview_rows)
        if arguments.search:
            query = arguments.search.casefold()
            names = [name for name in names if query in name.casefold()]
    except (FileNotFoundError, OSError, ValueError) as error:
        parser.error(str(error))

    rendered = "\n".join(names) + ("\n" if names else "")
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8-sig")
        print(f"Wrote {len(names)} canonical names to {arguments.output}")
    else:
        sys.stdout.write(rendered)

    if missing_targets:
        print(
            "Map-existing targets absent from the proposed catalog (apply blockers): "
            + ", ".join(missing_targets),
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
