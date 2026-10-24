"""Persistence operations for skills belonging to a job posting."""

from decimal import Decimal

import psycopg


class JobSkillRepository:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def remove_stale_skills(self, job_id: int, current_skill_ids: list[int]) -> None:
        """Keep the database set aligned with a completed extraction."""
        self._connection.execute(
            "DELETE FROM market.job_skills WHERE job_id = %s AND NOT (skill_id = ANY(%s))",
            (job_id, current_skill_ids),
        )

    def upsert_job_skill(
        self,
        *,
        job_id: int,
        skill_id: int,
        raw_skill_name: str,
        requirement_type: str,
        proficiency_level: str,
        importance_weight: Decimal,
        skill_confidence: Decimal | None,
        requirement_confidence: Decimal | None,
        proficiency_confidence: Decimal | None,
        overall_confidence: Decimal | None,
        evidence_text: str,
        extraction_method: str,
    ) -> None:
        """Update a known job-skill pair without inserting another row."""
        self._connection.execute(
            """
            INSERT INTO market.job_skills (
                job_id, skill_id, raw_skill_name, requirement_type,
                proficiency_level, importance_weight, skill_confidence,
                requirement_confidence, proficiency_confidence, overall_confidence,
                evidence_text, extraction_method
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_id, skill_id) DO UPDATE SET
                raw_skill_name = EXCLUDED.raw_skill_name,
                requirement_type = EXCLUDED.requirement_type,
                proficiency_level = EXCLUDED.proficiency_level,
                importance_weight = EXCLUDED.importance_weight,
                skill_confidence = EXCLUDED.skill_confidence,
                requirement_confidence = EXCLUDED.requirement_confidence,
                proficiency_confidence = EXCLUDED.proficiency_confidence,
                overall_confidence = EXCLUDED.overall_confidence,
                evidence_text = EXCLUDED.evidence_text,
                extraction_method = EXCLUDED.extraction_method,
                updated_at = now()
            """,
            (
                job_id, skill_id, raw_skill_name, requirement_type,
                proficiency_level, importance_weight, skill_confidence,
                requirement_confidence, proficiency_confidence, overall_confidence,
                evidence_text, extraction_method,
            ),
        )
