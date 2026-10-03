"""Persistence operations for tracking a pipeline ingestion run."""

import psycopg


class IngestionRunRepository:
    """Create and finish ingestion-run records using an existing connection."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def start_run(self, *, run_key: str, source: str = "jsearch") -> int:
        """Create a running record and return its database-generated run ID."""
        row = self._connection.execute(
            """
            INSERT INTO system.ingestion_runs (run_key, source, status)
            VALUES (%s, %s, 'running')
            RETURNING run_id
            """,
            (run_key, source),
        ).fetchone()
        return row[0]

    def finish_run(
        self,
        *,
        run_id: int,
        jobs_fetched: int,
        jobs_inserted: int,
        jobs_updated: int,
        jobs_failed: int = 0,
    ) -> None:
        """Mark a run complete and save its final job counts."""
        row = self._connection.execute(
            """
            UPDATE system.ingestion_runs
            SET status = 'completed',
                finished_at = now(),
                jobs_fetched = %s,
                jobs_inserted = %s,
                jobs_updated = %s,
                jobs_failed = %s
            WHERE run_id = %s
            RETURNING run_id
            """,
            (jobs_fetched, jobs_inserted, jobs_updated, jobs_failed, run_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Ingestion run not found: {run_id}")

    def fail_run(self, *, run_id: int, error_message: str) -> None:
        """Mark a run failed and store its error message."""
        row = self._connection.execute(
            """
            UPDATE system.ingestion_runs
            SET status = 'failed',
                finished_at = now(),
                error_message = %s
            WHERE run_id = %s
            RETURNING run_id
            """,
            (error_message, run_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Ingestion run not found: {run_id}")
