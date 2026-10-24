"""Persistence operations for market job postings and search provenance."""

from datetime import datetime

import psycopg


class JobPostingRepository:
    """Write structured job postings using an existing PostgreSQL connection."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def upsert_job_posting(
        self,
        *,
        provider_job_id: str | None,
        career_profile_id: int,
        job_title: str,
        company_id: int | None = None,
        normalized_job_title: str | None = None,
        job_description: str | None = None,
        location: str | None = None,
        city: str | None = None,
        state: str | None = None,
        country: str | None = None,
        employment_type: str | None = None,
        provider: str = "jsearch",
        publisher: str | None = None,
        source_url: str | None = None,
        posted_at: datetime | None = None,
        posted_at_status: str = "unknown",
        first_seen_at: datetime | None = None,
    ) -> int:
        """Insert a posting or refresh its fields when the provider ID already exists."""
        row = self._connection.execute(
            """
            INSERT INTO market.job_postings (
                provider_job_id, company_id, career_profile_id, job_title,
                normalized_job_title, job_description, location, city, state,
                country, employment_type, provider, publisher, source_url,
                posted_at, posted_at_status, first_seen_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, COALESCE(%s, now())
            )
            ON CONFLICT (provider, provider_job_id) DO UPDATE SET
                company_id = COALESCE(EXCLUDED.company_id, market.job_postings.company_id),
                career_profile_id = EXCLUDED.career_profile_id,
                job_title = EXCLUDED.job_title,
                normalized_job_title = COALESCE(
                    EXCLUDED.normalized_job_title,
                    market.job_postings.normalized_job_title
                ),
                job_description = COALESCE(
                    EXCLUDED.job_description,
                    market.job_postings.job_description
                ),
                location = COALESCE(EXCLUDED.location, market.job_postings.location),
                city = COALESCE(EXCLUDED.city, market.job_postings.city),
                state = COALESCE(EXCLUDED.state, market.job_postings.state),
                country = COALESCE(EXCLUDED.country, market.job_postings.country),
                employment_type = COALESCE(
                    EXCLUDED.employment_type,
                    market.job_postings.employment_type
                ),
                publisher = COALESCE(EXCLUDED.publisher, market.job_postings.publisher),
                source_url = COALESCE(EXCLUDED.source_url, market.job_postings.source_url),
                posted_at = COALESCE(EXCLUDED.posted_at, market.job_postings.posted_at),
                posted_at_status = CASE
                    WHEN EXCLUDED.posted_at IS NOT NULL
                        THEN EXCLUDED.posted_at_status
                    WHEN market.job_postings.posted_at IS NOT NULL
                        THEN market.job_postings.posted_at_status
                    ELSE EXCLUDED.posted_at_status
                END,
                first_seen_at = LEAST(
                    market.job_postings.first_seen_at,
                    EXCLUDED.first_seen_at
                ),
                collected_at = now(),
                updated_at = now()
            RETURNING job_id
            """,
            (
                provider_job_id,
                company_id,
                career_profile_id,
                job_title,
                normalized_job_title,
                job_description,
                location,
                city,
                state,
                country,
                employment_type,
                provider,
                publisher,
                source_url,
                posted_at,
                posted_at_status,
                first_seen_at,
            ),
        ).fetchone()
        return row[0]

    def record_search_match(
        self,
        *,
        job_id: int,
        run_id: int,
        career_profile_id: int,
        search_query: str,
    ) -> bool:
        """Record the query/run that found a job; return False if already recorded."""
        cursor = self._connection.execute(
            """
            INSERT INTO market.job_search_matches (
                job_id, run_id, career_profile_id, search_query
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (job_id, run_id, search_query) DO NOTHING
            """,
            (job_id, run_id, career_profile_id, search_query),
        )
        return cursor.rowcount == 1

    def mark_skill_extraction_completed(self, job_id: int) -> None:
        """Include this posting in career statistics, even if it has no skills."""
        self._connection.execute(
            """
            UPDATE market.job_postings
            SET skill_extraction_completed = true, updated_at = now()
            WHERE job_id = %s
            """,
            (job_id,),
        )
