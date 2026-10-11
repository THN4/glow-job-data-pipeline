"""Load configured careers and their general profiles into PostgreSQL."""

from pathlib import Path

import yaml

from src.shared.db.database import PROJECT_ROOT, get_database_connection

CAREERS_FILE = PROJECT_ROOT / "config" / "careers.yaml"


def load_career_records() -> list[tuple[str, str]]:
    """Read and validate the career slug/name pairs from careers.yaml."""
    with CAREERS_FILE.open(encoding="utf-8") as careers_file:
        data = yaml.safe_load(careers_file)

    if not isinstance(data, dict) or not isinstance(data.get("careers"), dict):
        raise ValueError("config/careers.yaml must contain a careers mapping")

    records = []
    for slug, entry in data["careers"].items():
        if not isinstance(slug, str) or not slug.strip() or not isinstance(entry, dict):
            raise ValueError("Each career must have a non-empty slug and a mapping")

        career_name = entry.get("career_name")
        if not isinstance(career_name, str) or not career_name.strip():
            raise ValueError(f"Career {slug} must have a non-empty career_name")

        records.append((slug, career_name.strip()))

    if not records:
        raise ValueError("config/careers.yaml must define at least one career")

    return records


def seed_reference_data() -> list[str]:
    """Upsert each configured career and its general career profile."""
    records = load_career_records()
    seeded_slugs = []

    with get_database_connection() as connection:
        with connection.transaction():
            for career_slug, career_name in records:
                career_row = connection.execute(
                    """
                    INSERT INTO core.careers (slug, career_name)
                    VALUES (%s, %s)
                    ON CONFLICT (slug) DO UPDATE
                    SET career_name = EXCLUDED.career_name,
                        updated_at = now()
                    RETURNING career_id
                    """,
                    (career_slug, career_name),
                ).fetchone()
                career_id = career_row[0]

                profile_slug = f"{career_slug}_general"
                connection.execute(
                    """
                    INSERT INTO core.career_profiles (
                        career_id, slug, profile_name, seniority_level
                    )
                    VALUES (%s, %s, %s, 'general')
                    ON CONFLICT (slug) DO UPDATE
                    SET career_id = EXCLUDED.career_id,
                        profile_name = EXCLUDED.profile_name,
                        seniority_level = EXCLUDED.seniority_level,
                        updated_at = now()
                    """,
                    (career_id, profile_slug, career_name),
                )
                seeded_slugs.append(career_slug)

    return seeded_slugs


def main() -> None:
    careers = seed_reference_data()
    for slug in careers:
        print(f"Seeded career and general profile: {slug}")


if __name__ == "__main__":
    main()
