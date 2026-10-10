"""Match extracted skill names to the reviewed database catalog."""

import re
import unicodedata

from src.load.database import get_database_connection


_REQUIREMENT_RANK = {"unknown": 0, "optional": 1, "preferred": 2, "required": 3}
_COMPOSITE_SEPARATOR = re.compile(r"[,;]")
_LEADING_CONJUNCTION = re.compile(r"^(?:and|or)\s+", re.IGNORECASE)
_PARENTHETICAL_ABBREVIATION = re.compile(r"^(?P<base>.+?)\s+\((?P<abbr>[A-Za-z][A-Za-z0-9.+#-]*)\)$")


def skill_name_key(name: str) -> str:
    """Ignore case and repeated spaces, without guessing semantic equivalence."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name).casefold()).strip()


def skill_identity_key(name: str) -> str:
    """Also equate a name with a verified acronym suffix, such as ``(ML)``."""
    match = _PARENTHETICAL_ABBREVIATION.fullmatch(name.strip())
    if match is None:
        return skill_name_key(name)
    base = match.group("base").strip()
    abbreviation = re.sub(r"[^A-Za-z0-9]", "", match.group("abbr")).casefold()
    words = re.findall(r"[^\W_]+", base, flags=re.UNICODE)
    initials = "".join(word[0] for word in words).casefold()
    if not initials or abbreviation != initials:
        return skill_name_key(name)
    return skill_name_key(base)


def split_composite_skill_name(name: str, evidence: str) -> list[str]:
    """Split a comma/semicolon list only when every component is in its evidence."""
    parts = [part.strip() for part in _COMPOSITE_SEPARATOR.split(name)]
    if len(parts) < 2 or any(not part for part in parts):
        return [name.strip()]
    keys = [skill_name_key(part) for part in parts]
    if any(not key for key in keys) or len(set(keys)) != len(keys):
        return [name.strip()]

    for part in parts:
        words = part.split()
        pattern = (
            r"(?<!\w)"
            + r"[\s\-\u2010-\u2015]+".join(re.escape(word) for word in words)
            + r"(?!\w)"
        )
        if not words or re.search(pattern, evidence, re.IGNORECASE) is None:
            return [name.strip()]
    return parts


def match_catalog_skill(
    name: str, catalog: dict[str, dict[str, object]]
) -> dict[str, object] | None:
    """Match exact names/aliases, then a verified acronym form of a canonical."""
    key = skill_name_key(name)
    identity = skill_identity_key(name)
    exact = catalog.get(key)
    if _COMPOSITE_SEPARATOR.search(name):
        # A composite label must never be normalized as one skill, including
        # when a stale alias or canonical row exists in the catalog.
        return None

    # Extraction sometimes attaches a leading conjunction from surrounding
    # prose to a single skill (for example, "and code review"). Only use this
    # cleanup when the remaining full label matches a known catalog entry; do
    # not remove conjunctions from the middle of a legitimate skill name.
    without_conjunction = _LEADING_CONJUNCTION.sub("", name, count=1).strip()
    if without_conjunction != name.strip():
        cleaned = catalog.get(skill_name_key(without_conjunction))
        if cleaned is not None:
            return {**cleaned, "match_method": "exact_alias"}

    # If the raw label is a verified acronym form and the base canonical exists,
    # prefer that base even when an older duplicate canonical row also exists.
    if identity != key:
        base = catalog.get(identity)
        if base is not None and base.get("match_method") == "exact_canonical":
            return {**base, "match_method": "exact_alias"}
    if exact is not None:
        return exact

    matches = [
        item
        for item in catalog.values()
        if item.get("match_method") == "exact_canonical"
        and skill_identity_key(str(item.get("skill_name", ""))) == identity
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda item: (
            skill_name_key(str(item.get("skill_name", ""))) != identity,
            int(item.get("skill_id", 0)),
        )
    )
    return {**matches[0], "match_method": "exact_alias"}


def build_skill_catalog(
    skills: list[
        tuple[int, str, str | None] | tuple[int, str, str | None, str]
    ],
    aliases: list[tuple[int, str]],
) -> dict[str, dict[str, object]]:
    """Build a lookup that prefers exact canonical names over confirmed aliases."""
    catalog: dict[str, dict[str, object]] = {}
    canonical_by_id = {}
    for record in skills:
        skill_id, skill_name, skill_category = record[:3]
        catalog_status = record[3] if len(record) == 4 else "approved"
        key = skill_name_key(skill_name)
        if not key or key in catalog:
            raise ValueError(f"Invalid or duplicate canonical skill: {skill_name}")
        canonical_by_id[skill_id] = (skill_name, skill_category, catalog_status)
        catalog[key] = {
            "skill_id": skill_id,
            "skill_name": skill_name,
            "skill_category": skill_category,
            "catalog_status": catalog_status,
            "match_method": "exact_canonical",
        }

    for skill_id, alias in aliases:
        key = skill_name_key(alias)
        if skill_id not in canonical_by_id or not key or key in catalog:
            raise ValueError(f"Invalid or conflicting skill alias: {alias}")
        catalog[key] = {
            "skill_id": skill_id,
            "skill_name": canonical_by_id[skill_id][0],
            "skill_category": canonical_by_id[skill_id][1],
            "catalog_status": canonical_by_id[skill_id][2],
            "match_method": "exact_alias",
        }
    return catalog


def load_skill_catalog() -> dict[str, dict[str, object]]:
    """Read the seeded catalog once for a normalization batch."""
    with get_database_connection() as connection:
        skills = connection.execute(
            """
            SELECT skill_id, skill_name, skill_category, catalog_status
            FROM core.skills ORDER BY skill_id
            """
        ).fetchall()
        aliases = connection.execute(
            "SELECT skill_id, alias FROM core.skill_aliases ORDER BY alias_id"
        ).fetchall()
    if not skills:
        raise ValueError(
            "Skill catalog is empty; complete the clean catalog rebuild before loading skills"
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
                evidence = raw.get("evidence_text")
                evidence_text = evidence if isinstance(evidence, str) else ""
                components = split_composite_skill_name(name, evidence_text)
                for component in components:
                    found = match_catalog_skill(component, catalog)
                    if found is None:
                        unmatched_skill = dict(raw)
                        unmatched_skill["raw_skill_name"] = component
                        if len(components) > 1:
                            unmatched_skill["source_raw_skill_name"] = name
                        unmatched.append(unmatched_skill)
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
                        "catalog_status": found["catalog_status"],
                        "raw_skill_name": component,
                        "match_method": found["match_method"],
                        "requirement_type": raw["requirement_type"],
                        "proficiency_level": raw["proficiency_level"],
                        "evidence_text": raw["evidence_text"],
                        "extraction_method": "llm",
                    }
                    if len(components) > 1:
                        candidate["source_raw_skill_name"] = name
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
