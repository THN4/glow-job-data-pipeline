"""Apply unapplied SQL migrations to the configured PostgreSQL database."""

from pathlib import Path

from src.load.database import get_database_connection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "migrations" / "versions"


def apply_migrations() -> list[str]:
    """Apply each pending migration once and return the applied file names."""
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        return []

    applied: list[str] = []
    with get_database_connection() as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS system")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS system.schema_migrations (
                version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        rows = connection.execute(
            "SELECT version FROM system.schema_migrations"
        ).fetchall()
        already_applied = {row[0] for row in rows}

        for migration_file in migration_files:
            version = migration_file.name
            if version in already_applied:
                continue

            sql = migration_file.read_text(encoding="utf-8")
            with connection.transaction():
                for statement in sql.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute(
                    "INSERT INTO system.schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            applied.append(version)

    return applied


def main() -> None:
    migrations = apply_migrations()
    if not migrations:
        print("Database schema is up to date.")
        return

    for migration in migrations:
        print(f"Applied migration: {migration}")


if __name__ == "__main__":
    main()
