"""Store companies by their exact, case-insensitive source name."""

import psycopg


class CompanyRepository:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def get_or_create(self, name: str, normalized_name: str | None) -> int:
        row = self._connection.execute(
            """
            INSERT INTO core.companies (company_name, normalized_name)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            RETURNING company_id
            """,
            (name, normalized_name),
        ).fetchone()
        if row is None:
            row = self._connection.execute(
                "SELECT company_id FROM core.companies WHERE lower(company_name) = lower(%s)",
                (name,),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"Unable to resolve company: {name}")
        return row[0]
