"""Seed reviewed canonical skills and aliases into PostgreSQL."""

import re
import unicodedata
from pathlib import Path

import yaml

from src.load.database import PROJECT_ROOT, get_database_connection


SKILLS_FILE = PROJECT_ROOT / "config" / "skills.yaml"


def _comparison_key(name: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name).casefold()).strip()


def load_skill_records(
    skills_file: Path = SKILLS_FILE,
) -> list[tuple[str, str, list[str]]]:
    """Validate reviewed skill names before any database writes."""
    with skills_file.open(encoding="utf-8") as source:
        data = yaml.safe_load(source)
    if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
        raise ValueError("Skill catalog must contain a skills mapping")

    records: list[tuple[str, str, list[str]]] = []
    seen_names: set[str] = set()
    for slug, entry in data["skills"].items():
        if not isinstance(slug, str) or not slug.strip() or not isinstance(entry, dict):
            raise ValueError("Each skill needs a slug and a mapping")
        name = entry.get("skill_name")
        category = entry.get("skill_category")
        aliases = entry.get("aliases", [])
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Skill {slug} needs a skill_name")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"Skill {slug} needs a skill_category")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ValueError(f"Skill {slug} aliases must be non-empty strings")

        names = [name, *aliases]
        for value in names:
            key = _comparison_key(value)
            if key in seen_names:
                raise ValueError(f"Duplicate skill name or alias: {value}")
            seen_names.add(key)
        records.append((name.strip(), category.strip(), [alias.strip() for alias in aliases]))

    if not records:
        raise ValueError("Skill catalog must define at least one skill")
    return records


def seed_skill_catalog(skills_file: Path = SKILLS_FILE) -> list[str]:
    """Upsert canonical skills and add aliases without reassigning old aliases."""
    records = load_skill_records(skills_file)
    with get_database_connection() as connection:
        with connection.transaction():
            for name, category, aliases in records:
                row = connection.execute(
                    """
                    INSERT INTO core.skills (skill_name, skill_category)
                    VALUES (%s, %s)
                    ON CONFLICT (skill_name) DO UPDATE
                    SET skill_category = EXCLUDED.skill_category,
                        catalog_status = 'approved',
                        updated_at = now()
                    RETURNING skill_id
                    """,
                    (name, category),
                ).fetchone()
                skill_id = row[0]
                for alias in aliases:
                    connection.execute(
                        """
                        INSERT INTO core.skill_aliases (skill_id, alias)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (skill_id, alias),
                    )
                    existing = connection.execute(
                        "SELECT skill_id FROM core.skill_aliases WHERE lower(alias) = lower(%s)",
                        (alias,),
                    ).fetchone()
                    if existing[0] != skill_id:
                        raise ValueError(f"Alias already belongs to another skill: {alias}")
    return [name for name, _, _ in records]


def main() -> None:
    for name in seed_skill_catalog():
        print(f"Seeded skill: {name}")


if __name__ == "__main__":
    main()
