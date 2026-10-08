"""Load completed skill checkpoints into job postings and job-skill rows."""

from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from src.load.database import get_database_connection
from src.load.repositories.company_repository import CompanyRepository
from src.load.repositories.job_posting_repository import JobPostingRepository
from src.load.repositories.job_skill_repository import JobSkillRepository
from src.skills.confidence import score_job_skill
from src.skills.normalizer import load_skill_catalog, normalize_skills_for_jobs
from src.storage.skill_result_storage import load_skill_results
from src.transform.company_normalizer import normalize_company_key


DEFAULT_SKILL_OUTPUT_DIR = Path("data/processed/skill_extraction")
_REQUIREMENT_SCORE = {
    "required": Decimal("1.00"),
    "preferred": Decimal("0.60"),
    "optional": Decimal("0.30"),
    "unknown": Decimal("0.40"),
}
_PROFICIENCY_SCORE = {
    "expert": Decimal("1.00"),
    "advanced": Decimal("0.90"),
    "intermediate": Decimal("0.70"),
    "beginner": Decimal("0.50"),
    "unknown": Decimal("0.60"),
}
def importance_weight(requirement_type: str, proficiency_level: str) -> Decimal:
    """Apply the initial deterministic scoring rule from the skill spec."""
    return (
        Decimal("0.7") * _REQUIREMENT_SCORE[requirement_type]
        + Decimal("0.3") * _PROFICIENCY_SCORE[proficiency_level]
    ).quantize(Decimal("0.001"))


def _posted_at(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("posted_at must be an ISO timestamp in the checkpoint")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("posted_at must include a timezone")
    return parsed


def load_job_skills_from_run(
    run_id: str, *, output_dir: Path = DEFAULT_SKILL_OUTPUT_DIR
) -> dict[str, int]:
    """Upsert mapped postings and matched skills from one saved run.

    Failed extractions and jobs without a stable provider ID or mapped career
    remain in the checkpoint. They are not given invented database IDs.
    """
    entries = load_skill_results(run_id=run_id, output_dir=output_dir)
    if not entries:
        raise ValueError(f"No skill checkpoint entries found for run_id: {run_id}")
    entries = normalize_skills_for_jobs(entries, load_skill_catalog())
    counts: Counter[str] = Counter()

    with get_database_connection() as connection:
        with connection.transaction():
            profiles = dict(
                connection.execute(
                    "SELECT slug, career_profile_id FROM core.career_profiles"
                ).fetchall()
            )
            companies = CompanyRepository(connection)
            postings = JobPostingRepository(connection)
            job_skills = JobSkillRepository(connection)

            for entry in entries:
                if entry.get("extraction_status") != "completed":
                    counts["skipped_failed_extraction"] += 1
                    continue
                job = entry.get("job")
                if not isinstance(job, dict):
                    counts["skipped_missing_identity"] += 1
                    continue
                provider_id = job.get("job_id")
                title = job.get("job_title")
                profile_slug = job.get("career_profile_slug")
                if not all(
                    isinstance(value, str) and value.strip()
                    for value in (provider_id, title, profile_slug)
                ) or job.get("career_mapping_status") != "mapped":
                    counts["skipped_missing_identity"] += 1
                    continue
                profile_id = profiles.get(profile_slug)
                if profile_id is None:
                    raise ValueError(f"Career profile is not seeded: {profile_slug}")

                company_id = None
                raw_company = job.get("employer_name")
                company_info = job.get("company_normalization")
                confirmed_name = (
                    company_info.get("canonical_name")
                    if isinstance(company_info, dict)
                    and company_info.get("match_method") == "confirmed_alias"
                    else None
                )
                company_name = confirmed_name or raw_company
                if isinstance(company_name, str) and company_name.strip():
                    company_name = company_name.strip()
                    company_id = companies.get_or_create(
                        company_name, normalize_company_key(company_name)
                    )

                job_id = postings.upsert_job_posting(
                    provider_job_id=provider_id.strip(),
                    career_profile_id=profile_id,
                    job_title=title.strip(),
                    company_id=company_id,
                    normalized_job_title=job.get("normalized_job_title"),
                    job_description=job.get("job_description"),
                    location=job.get("job_location"),
                    city=job.get("job_city"),
                    state=job.get("job_state"),
                    country=job.get("job_country"),
                    employment_type=job.get("job_employment_type"),
                    publisher=job.get("job_publisher"),
                    source_url=job.get("job_apply_link"),
                    posted_at=_posted_at(job.get("posted_at")),
                )
                normalized = entry["normalized_skills"]
                job_description = job.get("job_description")
                if not isinstance(job_description, str):
                    raise ValueError("Completed extraction must have a job description")
                scored = []
                for skill in normalized:
                    confidence = score_job_skill(skill, job_description)
                    if confidence["skill_confidence"] is None:
                        counts["skipped_unverified_skills"] += 1
                        continue
                    if confidence["overall_confidence"] is None:
                        counts["skills_needing_review"] += 1
                    scored.append((skill, confidence))
                job_skills.remove_stale_skills(
                    job_id, [skill["skill_id"] for skill, _ in scored]
                )
                for skill, confidence in scored:
                    job_skills.upsert_job_skill(
                        job_id=job_id,
                        skill_id=skill["skill_id"],
                        raw_skill_name=skill["raw_skill_name"],
                        requirement_type=skill["requirement_type"],
                        proficiency_level=skill["proficiency_level"],
                        importance_weight=importance_weight(
                            skill["requirement_type"], skill["proficiency_level"]
                        ),
                        skill_confidence=confidence["skill_confidence"],
                        requirement_confidence=confidence["requirement_confidence"],
                        proficiency_confidence=confidence["proficiency_confidence"],
                        overall_confidence=confidence["overall_confidence"],
                        evidence_text=skill["evidence_text"],
                        extraction_method=skill["extraction_method"],
                    )
                postings.mark_skill_extraction_completed(job_id)
                counts["postings_loaded"] += 1
                counts["skills_loaded"] += len(scored)
                counts["unmatched_skills"] += len(entry["unmatched_skills"])
    return dict(counts)
