"""Apply unapplied SQL migrations to the configured PostgreSQL database."""

from pathlib import Path

from src.shared.db.database import get_database_connection

DATA_PIPELINE_ROOT = Path(__file__).resolve().parents[2]
HOST_REPOSITORY_ROOT = DATA_PIPELINE_ROOT.parent
MIGRATION_DIRECTORIES = [DATA_PIPELINE_ROOT / "migrations" / "versions"]
if (HOST_REPOSITORY_ROOT / "docs" / "schemas" / "glow-job.dbml").is_file():
    MIGRATION_DIRECTORIES.append(HOST_REPOSITORY_ROOT / "migrations" / "versions")


def _get_migration_files() -> list[Path]:
    """Load pipeline and host-repository migrations into one ordered history."""
    migration_files = sorted(
        migration_file
        for directory in MIGRATION_DIRECTORIES
        for migration_file in directory.glob("*.sql")
    )
    versions = [migration_file.name for migration_file in migration_files]
    if len(versions) != len(set(versions)):
        raise ValueError("Migration filenames must be unique across repositories")
    return migration_files


def apply_migrations() -> list[str]:
    """Apply each pending migration once and return the applied file names."""
    migration_files = _get_migration_files()
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
