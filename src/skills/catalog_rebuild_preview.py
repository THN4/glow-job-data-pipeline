"""Build an offline, multi-run preview for rebuilding the skill catalog."""

import csv
from difflib import SequenceMatcher
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import yaml

from src.skills.normalizer import (
    build_skill_catalog,
    match_catalog_skill,
    skill_identity_key,
    skill_name_key,
    split_composite_skill_name,
)


_TOKEN = re.compile(r"[^\W_]+(?:[.+#][^\W_]+|[+#]+)*", re.UNICODE)
_COMPOSITE = re.compile(r"[,;]|\s+(?:and|or)\s+|\s+/\s+", re.IGNORECASE)
_GENERIC = re.compile(
    r"\b(?:tools?|tooling|frameworks?|ecosystems?|solutions?|platforms?|pipelines?|techniques?)\b",
    re.IGNORECASE,
)
_GENERIC_TOKENS = {
    "tool", "tools", "tooling", "framework", "frameworks", "ecosystem",
    "ecosystems", "solution", "solutions", "platform", "platforms",
    "pipeline", "pipelines", "technique", "techniques",
}
_REQUIRED_COLUMNS = (
    "candidate_name",
    "observed_names",
    "source_composite_names",
    "variant_count",
    "grouping_method",
    "occurrence_count",
    "job_count",
    "evidence_hit_jobs",
    "source_runs",
    "career_names",
    "possible_existing_skill",
    "existing_database_matches",
    "similar_database_skills",
    "possible_duplicate_candidates",
    "example_job_titles",
    "example_evidence",
    "suggestion_decision",
    "suggested_skill_name",
    "suggested_skill_category",
    "confidence_level",
    "suggestion_reason",
    "preview_status",
    "review_decision",
    "canonical_skill_name",
    "skill_category",
    "split_skills",
)
_JSON_COLUMNS = {
    "observed_names",
    "source_composite_names",
    "source_runs",
    "career_names",
    "example_job_titles",
    "example_evidence",
    "split_skills",
}


def load_bootstrap_catalog(seed_file: Path) -> dict[str, dict[str, object]]:
    """Read the initial approved catalog without opening a database connection."""
    with seed_file.open(encoding="utf-8") as source:
        payload = yaml.safe_load(source)
    if not isinstance(payload, dict) or not isinstance(payload.get("skills"), dict):
        raise ValueError("Bootstrap catalog must contain a skills mapping")

    skills: list[tuple[int, str, str | None, str]] = []
    aliases: list[tuple[int, str]] = []
    for skill_id, entry in enumerate(payload["skills"].values(), start=1):
        if not isinstance(entry, dict):
            raise ValueError("Each bootstrap skill must be a mapping")
        name = entry.get("skill_name")
        category = entry.get("skill_category")
        skill_aliases = entry.get("aliases", [])
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each bootstrap skill needs a skill_name")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"Bootstrap skill {name!r} needs a skill_category")
        if not isinstance(skill_aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in skill_aliases
        ):
            raise ValueError(f"Bootstrap skill {name!r} has invalid aliases")
        skills.append((skill_id, name.strip(), category.strip(), "approved"))
        aliases.extend((skill_id, alias.strip()) for alias in skill_aliases)
    if not skills:
        raise ValueError("Bootstrap catalog must define at least one skill")
    return build_skill_catalog(skills, aliases)


def _tokens(name: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return tuple(_TOKEN.findall(normalized))


def _family_key(name: str) -> tuple[str, ...]:
    identity = skill_identity_key(name)
    tokens = _tokens(identity)
    if len(tokens) > 1:
        return ("words", *sorted(tokens))
    return ("exact", identity)


def _contains_name(evidence: str, name: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", evidence, re.IGNORECASE) is not None


def load_skill_checkpoints(checkpoint_dir: Path) -> list[tuple[str, list[dict[str, Any]]]]:
    checkpoints: list[tuple[str, list[dict[str, Any]]]] = []
    for path in sorted(checkpoint_dir.glob("*.json")):
        with path.open(encoding="utf-8") as source:
            payload = json.load(source)
        run_id = path.stem
        if (
            not isinstance(payload, dict)
            or payload.get("run_id") != run_id
            or not isinstance(payload.get("jobs"), list)
            or any(not isinstance(entry, dict) for entry in payload["jobs"])
        ):
            raise ValueError(f"Invalid skill checkpoint: {path}")
        checkpoints.append((run_id, payload["jobs"]))
    if not checkpoints:
        raise FileNotFoundError(f"No skill checkpoints found in {checkpoint_dir}")
    return checkpoints


def _evidence_examples(observations: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    titles: list[str] = []
    evidence: list[str] = []
    for item in observations:
        if item["job_title"] not in titles:
            titles.append(item["job_title"])
            evidence.append(item["evidence"])
        if len(titles) == 5:
            break
    return titles, evidence


def _preview_status(row: dict[str, object]) -> str:
    decision = row.get("suggestion_decision")
    confidence = row.get("confidence_level")
    if not decision:
        return "needs_llm_suggestion"
    if confidence != "high" or decision == "uncertain":
        return "manual_review"
    if decision == "not_skill":
        return "manual_review"
    if row.get("possible_duplicate_candidates"):
        return "manual_review"
    if _COMPOSITE.search(str(row["candidate_name"])) or _GENERIC.search(
        str(row["candidate_name"])
    ):
        return "manual_review"
    minimum_jobs = 1
    minimum_evidence = 1
    if int(row["job_count"]) < minimum_jobs or int(row["evidence_hit_jobs"]) < minimum_evidence:
        return "manual_review"
    return "ready_for_approval"


def build_catalog_rebuild_preview(
    checkpoints: list[tuple[str, list[dict[str, Any]]]],
    catalog: dict[str, dict[str, object]],
    *,
    split_composites: bool = True,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Aggregate unique postings, collapse exact word-order variants, and propose review rows."""
    jobs: dict[str, dict[str, Any]] = {}
    failed_jobs: set[str] = set()
    seed_matched_occurrences = 0
    composite_occurrences_split = 0
    split_components_created = 0
    split_components_matched = 0
    split_components_unmatched = 0
    seed_names: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for key, item in catalog.items():
        seed_names[_family_key(key)].add(str(item["skill_name"]))

    for run_id, entries in checkpoints:
        for index, entry in enumerate(entries):
            status = entry.get("extraction_status")
            job = entry.get("job")
            job = job if isinstance(job, dict) else {}
            provider_id = job.get("job_id")
            job_key = (
                f"provider:{provider_id}"
                if isinstance(provider_id, str) and provider_id.strip()
                else f"checkpoint:{run_id}:{index}"
            )
            if status == "failed":
                failed_jobs.add(job_key)
                continue
            if status != "completed":
                raise ValueError(
                    f"Checkpoint {run_id} job {index + 1} has invalid extraction_status"
                )
            raw_skills = entry.get("skills")
            if not isinstance(raw_skills, list):
                raise ValueError(
                    f"Checkpoint {run_id} job {index + 1} has no skills list"
                )
            record = jobs.setdefault(
                job_key,
                {
                    "job_title": str(job.get("job_title") or "unknown"),
                    "career_names": set(),
                    "run_ids": set(),
                    "skills": {},
                },
            )
            record["run_ids"].add(run_id)
            metadata = entry.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            career = job.get("career_name") or metadata.get("career_name")
            if isinstance(career, str) and career.strip():
                record["career_names"].add(career.strip())
            for raw in raw_skills:
                if not isinstance(raw, dict):
                    raise ValueError(f"Checkpoint {run_id} contains a malformed skill")
                raw_name = raw.get("raw_skill_name")
                if not isinstance(raw_name, str) or not raw_name.strip():
                    raise ValueError(f"Checkpoint {run_id} contains a skill without a name")
                evidence = raw.get("evidence_text")
                evidence_text = evidence if isinstance(evidence, str) else ""
                source_name = raw_name.strip()
                components = (
                    split_composite_skill_name(source_name, evidence_text)
                    if split_composites
                    else [source_name]
                )
                if len(components) > 1:
                    composite_occurrences_split += 1
                    split_components_created += len(components)
                for name in components:
                    key = skill_name_key(name)
                    if match_catalog_skill(name, catalog) is not None:
                        seed_matched_occurrences += 1
                        if len(components) > 1:
                            split_components_matched += 1
                        continue
                    if len(components) > 1:
                        split_components_unmatched += 1
                    observation = {
                        "raw_name": name,
                        "source_raw_name": source_name,
                        "job_title": record["job_title"],
                        "career_name": next(iter(record["career_names"]), "unknown"),
                        "evidence": evidence_text,
                        "run_id": run_id,
                    }
                    # A posting appearing in multiple runs contributes one
                    # observation per distinct normalized component.
                    record["skills"].setdefault(key, observation)

    families: dict[tuple[str, ...], dict[str, Any]] = {}
    for job_key, job in jobs.items():
        for name_key, observation in job["skills"].items():
            family = _family_key(observation["raw_name"])
            item = families.setdefault(
                family,
                {
                    "jobs": set(),
                    "names": Counter(),
                    "observations": [],
                    "careers": set(),
                    "runs": set(),
                    "evidence_hit_jobs": set(),
                },
            )
            item["jobs"].add(job_key)
            item["names"][observation["raw_name"]] += 1
            item["observations"].append(observation)
            if observation["career_name"]:
                item["careers"].add(observation["career_name"])
            item["runs"].add(observation["run_id"])
            if _contains_name(observation["evidence"], observation["raw_name"]):
                item["evidence_hit_jobs"].add(job_key)

    rows: list[dict[str, object]] = []
    for family, data in families.items():
        names = sorted(
            data["names"], key=lambda value: (-data["names"][value], value.casefold(), value)
        )
        representative = names[0]
        observed_token_sequences = {
            _tokens(skill_identity_key(name)) for name in names
        }
        grouping_method = (
            "token_order_variant"
            if len(names) > 1 and len(observed_token_sequences) > 1
            else "format_variant"
            if len(names) > 1
            else "exact_name"
        )
        possible = sorted(seed_names.get(family, set()), key=str.casefold)
        titles, evidence = _evidence_examples(data["observations"])
        rows.append(
            {
                "candidate_name": representative,
                "observed_names": names,
                "source_composite_names": sorted(
                    {
                        observation["source_raw_name"]
                        for observation in data["observations"]
                        if observation["source_raw_name"] != observation["raw_name"]
                    },
                    key=str.casefold,
                ),
                "variant_count": len(names),
                "grouping_method": grouping_method,
                "occurrence_count": sum(data["names"].values()),
                "job_count": len(data["jobs"]),
                "evidence_hit_jobs": len(data["evidence_hit_jobs"]),
                "source_runs": sorted(data["runs"]),
                "career_names": sorted(data["careers"], key=str.casefold),
                "possible_existing_skill": "; ".join(possible),
                "existing_database_matches": "",
                "similar_database_skills": "",
                "possible_duplicate_candidates": "",
                "example_job_titles": titles,
                "example_evidence": evidence,
                "suggestion_decision": "",
                "suggested_skill_name": "",
                "suggested_skill_category": "",
                "confidence_level": "",
                "suggestion_reason": "",
                "preview_status": "needs_llm_suggestion",
                "review_decision": "",
                "canonical_skill_name": "",
                "skill_category": "",
                "split_skills": "[]",
            }
        )
    core_signatures: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        core_tokens = tuple(
            sorted(
                token
                for token in _tokens(skill_identity_key(str(row["candidate_name"])))
                if token not in _GENERIC_TOKENS
            )
        )
        if len(core_tokens) >= 2:
            core_signatures[core_tokens].append(row)
    for related_rows in core_signatures.values():
        if len(related_rows) < 2:
            continue
        names = sorted(str(row["candidate_name"]) for row in related_rows)
        for row in related_rows:
            row["possible_duplicate_candidates"] = "; ".join(
                name for name in names if name != row["candidate_name"]
            )
    rows.sort(
        key=lambda row: (
            -int(row["job_count"]),
            -int(row["occurrence_count"]),
            str(row["candidate_name"]).casefold(),
        )
    )
    summary = {
        "checkpoint_runs": len(checkpoints),
        "unique_completed_postings": len(jobs),
        "failed_postings": len(failed_jobs),
        "seed_matched_occurrences": seed_matched_occurrences,
        "composite_occurrences_split": composite_occurrences_split,
        "split_components_created": split_components_created,
        "split_components_matched": split_components_matched,
        "split_components_unmatched": split_components_unmatched,
        "candidate_groups": len(rows),
        "candidate_occurrences": sum(int(row["occurrence_count"]) for row in rows),
    }
    return rows, summary


def save_catalog_rebuild_preview(rows: list[dict[str, object]], output_path: Path) -> Path:
    """Write the review artifact only; this function never connects to PostgreSQL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=_REQUIRED_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(row[key], ensure_ascii=False, separators=(",", ":"))
                    if key in _JSON_COLUMNS
                    else row.get(key, "")
                    for key in _REQUIRED_COLUMNS
                }
            )
    return output_path


def add_database_catalog_comparison(
    rows: list[dict[str, object]], catalog: dict[str, dict[str, object]]
) -> None:
    """Annotate review rows with read-only exact and approximate DB catalog matches."""
    catalog_entries: dict[str, dict[str, object]] = {}
    for key, item in catalog.items():
        name = str(item["skill_name"])
        entry = catalog_entries.setdefault(
            name,
            {
                "name": name,
                "category": str(item.get("skill_category") or ""),
                "status": str(item.get("catalog_status") or "approved"),
                "aliases": set(),
                "keys": set(),
            },
        )
        entry["keys"].add(key)
        if item.get("match_method") == "exact_alias":
            entry["aliases"].add(key)

    for row in rows:
        raw_names = [str(row["candidate_name"])]
        observed_names = row.get("observed_names", [])
        if isinstance(observed_names, str):
            try:
                observed_names = json.loads(observed_names)
            except json.JSONDecodeError:
                observed_names = []
        if isinstance(observed_names, list):
            raw_names.extend(str(name) for name in observed_names)
        raw_keys = {skill_name_key(name) for name in raw_names}
        exact_matches = []
        for entry in catalog_entries.values():
            matched_keys = raw_keys.intersection(entry["keys"])
            if not matched_keys:
                continue
            match_type = "alias" if matched_keys.intersection(entry["aliases"]) else "canonical"
            exact_matches.append(
                f"{entry['name']} [{match_type}; {entry['status']}]"
            )
        row["existing_database_matches"] = "; ".join(
            sorted(set(exact_matches), key=str.casefold)
        )

        candidate = skill_name_key(str(row["candidate_name"]))
        candidate_tokens = set(candidate.split())
        similar: list[tuple[float, str]] = []
        for entry in catalog_entries.values():
            existing = skill_name_key(str(entry["name"]))
            existing_tokens = set(existing.split())
            sequence_score = SequenceMatcher(None, candidate, existing).ratio()
            overlap_score = (
                len(candidate_tokens & existing_tokens) / len(candidate_tokens | existing_tokens)
                if candidate_tokens | existing_tokens
                else 0.0
            )
            score = max(sequence_score, overlap_score)
            if score >= 0.55 and candidate != existing:
                similar.append((score, str(entry["name"])))
        similar.sort(key=lambda item: (-item[0], item[1].casefold()))
        row["similar_database_skills"] = "; ".join(
            f"{name} ({score:.0%}; {catalog_entries[name]['status']})"
            for score, name in similar[:5]
        )


def finalize_preview_suggestions(rows: list[dict[str, object]]) -> None:
    """Label proposals for approval; never converts them into database actions."""
    for row in rows:
        row["preview_status"] = _preview_status(row)


def audit_skill_catalog_names(
    skills: list[tuple[int, str, str | None, int]],
    aliases: list[tuple[int, str, str, int]],
) -> dict[str, list[dict[str, object]]]:
    """Flag likely canonical duplicates and composite aliases without changing data."""
    canonical_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for skill_id, name, category, job_count in skills:
        canonical_groups[skill_identity_key(name)].append(
            {
                "skill_id": skill_id,
                "skill_name": name,
                "skill_category": category,
                "job_count": job_count,
            }
        )
    duplicates = [
        {"identity_key": key, "skills": sorted(group, key=lambda item: str(item["skill_name"]).casefold())}
        for key, group in canonical_groups.items()
        if len(group) > 1
    ]
    composite_aliases = [
        {
            "alias_id": alias_id,
            "alias": alias,
            "canonical_skill_name": canonical,
            "job_count": job_count,
        }
        for alias_id, alias, canonical, job_count in aliases
        if _COMPOSITE.search(alias)
    ]
    return {
        "duplicate_canonical_groups": sorted(
            duplicates, key=lambda item: str(item["identity_key"])
        ),
        "composite_aliases": sorted(
            composite_aliases, key=lambda item: str(item["alias"]).casefold()
        ),
    }


def scan_suggested_duplicates(
    rows: list[dict[str, object]], *, generate: Callable[[str], str]
) -> int:
    """Ask Gemini to flag semantic duplicates for human review, never auto-merge."""
    suggested_rows = [
        row for row in rows if row.get("suggestion_decision") in {"existing_skill", "new_skill"}
    ]
    if len(suggested_rows) < 2:
        return 0
    known_names = {str(row["candidate_name"]) for row in suggested_rows}
    candidates = [
        {
            "candidate_name": row["candidate_name"],
            "suggested_canonical": row["suggested_skill_name"],
            "job_count": row["job_count"],
            "evidence": row["example_evidence"][:2],
        }
        for row in suggested_rows
    ]
    prompt = (
        "Find only candidate pairs/groups that refer to the same specific skill "
        "despite spelling, abbreviation, or wording variants. Do not group a "
        "broad category with a specific tool, a parent concept with a related "
        "technology, or a compound phrase with one component. Use the evidence "
        "and proposed canonical labels. Return only JSON in this shape: "
        '{"possible_duplicate_groups":[["candidate name A","candidate name B"]]}. '
        "Use exact candidate_name strings from the input, include at least two "
        "names per group, and omit candidates that are not clear duplicates. "
        f"Candidates: {json.dumps(candidates, ensure_ascii=False)}"
    )
    try:
        payload = json.loads(generate(prompt))
    except json.JSONDecodeError as error:
        raise ValueError("Gemini duplicate scan must return valid JSON") from error
    groups = payload.get("possible_duplicate_groups") if isinstance(payload, dict) else None
    if not isinstance(groups, list):
        raise ValueError("Gemini duplicate scan must contain possible_duplicate_groups")
    additions: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        if (
            not isinstance(group, list)
            or len(group) < 2
            or any(not isinstance(name, str) or name not in known_names for name in group)
            or len(set(group)) != len(group)
        ):
            raise ValueError("Gemini duplicate scan returned an invalid candidate group")
        for name in group:
            additions[name].update(other for other in group if other != name)
    for row in suggested_rows:
        name = str(row["candidate_name"])
        current = {
            value.strip()
            for value in str(row.get("possible_duplicate_candidates", "")).split(";")
            if value.strip()
        }
        current.update(additions.get(name, set()))
        row["possible_duplicate_candidates"] = "; ".join(sorted(current, key=str.casefold))
    return sum(bool(value) for value in additions.values())
