"""Match extracted skill names to the reviewed database catalog."""

import re
import unicodedata

from src.load.database import get_database_connection


_REQUIREMENT_RANK = {"unknown": 0, "optional": 1, "preferred": 2, "required": 3}


def _name_key(name: str) -> str:
    """Ignore case and repeated spaces, without guessing semantic equivalence."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name).casefold()).strip()


def build_skill_catalog(
    skills: list[tuple[int, str, str | None]], aliases: list[tuple[int, str]]
) -> dict[str, dict[str, object]]:
    """Build a lookup that prefers exact canonical names over confirmed aliases."""
    catalog: dict[str, dict[str, object]] = {}
    for skill_id, skill_name, skill_category in skills:
        key = _name_key(skill_name)
        if not key or key in catalog:
            raise ValueError(f"Invalid or duplicate canonical skill: {skill_name}")
        catalog[key] = {
            "skill_id": skill_id,
            "skill_name": skill_name,
            "skill_category": skill_category,
            "match_method": "exact_canonical",
        }

    canonical_by_id = {
        skill_id: (name, category) for skill_id, name, category in skills
    }
    for skill_id, alias in aliases:
        key = _name_key(alias)
        if skill_id not in canonical_by_id or not key or key in catalog:
            raise ValueError(f"Invalid or conflicting skill alias: {alias}")
        catalog[key] = {
            "skill_id": skill_id,
            "skill_name": canonical_by_id[skill_id][0],
            "skill_category": canonical_by_id[skill_id][1],
            "match_method": "exact_alias",
        }
    return catalog


def load_skill_catalog() -> dict[str, dict[str, object]]:
    """Read the seeded catalog once for a normalization batch."""
    with get_database_connection() as connection:
        skills = connection.execute(
            "SELECT skill_id, skill_name, skill_category FROM core.skills ORDER BY skill_id"
        ).fetchall()
        aliases = connection.execute(
            "SELECT skill_id, alias FROM core.skill_aliases ORDER BY alias_id"
        ).fetchall()
    if not skills:
        raise ValueError(
            "Skill catalog is empty; run python -m scripts.seed_skill_catalog"
        )
    return build_skill_catalog(skills, aliases)


def normalize_skills_for_jobs(
    jobs: list[dict[str, object]], catalog: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    """Add matched and unmatched results while preserving the raw extraction.

    A matched skill appears at most once per job. If the model mentions the
    same canonical skill more than once, the strongest requirement and its
    evidence win. Conflicting proficiency levels become unknown for review.
    """
    output: list[dict[str, object]] = []
    for entry in jobs:
        result = dict(entry)
        matched: dict[int, dict[str, object]] = {}
        unmatched: list[dict[str, str]] = []
        stated_levels: dict[int, set[str]] = {}
        if entry.get("extraction_status") == "completed":
            raw_skills = entry.get("skills")
            if not isinstance(raw_skills, list):
                raise ValueError("Completed extraction must contain a skills list")
            for raw in raw_skills:
                if not isinstance(raw, dict) or not isinstance(
                    raw.get("raw_skill_name"), str
                ):
                    raise ValueError("Extracted skill must have a raw_skill_name")
                name = raw["raw_skill_name"]
                found = catalog.get(_name_key(name))
                if found is None:
                    unmatched.append(dict(raw))
                    continue

                skill_id = found["skill_id"]
                assert isinstance(skill_id, int)
                level = raw["proficiency_level"]
                if level != "unknown":
                    stated_levels.setdefault(skill_id, set()).add(level)
                candidate = {
                    "skill_id": skill_id,
                    "skill_name": found["skill_name"],
                    "skill_category": found["skill_category"],
                    "raw_skill_name": name,
                    "match_method": found["match_method"],
                    "requirement_type": raw["requirement_type"],
                    "proficiency_level": raw["proficiency_level"],
                    "evidence_text": raw["evidence_text"],
                    "extraction_method": "llm",
                }
                existing = matched.get(skill_id)
                if existing is None:
                    matched[skill_id] = candidate
                    continue

                old_rank = _REQUIREMENT_RANK[existing["requirement_type"]]
                new_rank = _REQUIREMENT_RANK[candidate["requirement_type"]]
                if new_rank > old_rank:
                    matched[skill_id] = candidate

            for skill_id, normalized in matched.items():
                levels = stated_levels.get(skill_id, set())
                normalized["proficiency_level"] = (
                    next(iter(levels)) if len(levels) == 1 else "unknown"
                )

        result["normalized_skills"] = list(matched.values())
        result["unmatched_skills"] = unmatched
        output.append(result)
    return output
