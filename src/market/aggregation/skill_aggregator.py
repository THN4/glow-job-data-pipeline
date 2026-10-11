"""Calculate career-level skill demand from completed job extractions."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class CareerSkillStat:
    career_profile_id: int
    skill_id: int
    demand_count: int
    total_jobs: int
    demand_percentage: Decimal
    required_count: int
    preferred_count: int
    optional_count: int
    weighted_demand_score: Decimal
    target_level: str
    target_level_confidence: Decimal | None
    level_observation_count: int


def aggregate_career_skills(
    postings: list[tuple[int, int]],
    job_skills: list[tuple[int, int, str, str, Decimal]],
) -> list[CareerSkillStat]:
    """Count one observation per job and skill, including empty jobs in totals.

    `postings` contains only completed, dated, usable jobs in the window.
    Skill rows belong to those postings and are unique by (job_id, skill_id).
    """
    profile_by_job = dict(postings)
    if len(profile_by_job) != len(postings):
        raise ValueError("Duplicate job in aggregation cohort")
    totals = Counter(profile_by_job.values())
    groups: dict[tuple[int, int], list[tuple[str, str, Decimal]]] = defaultdict(list)
    seen_pairs: set[tuple[int, int]] = set()
    for job_id, skill_id, requirement, level, weight in job_skills:
        if job_id not in profile_by_job:
            raise ValueError(f"Skill belongs to a job outside the cohort: {job_id}")
        pair = (job_id, skill_id)
        if pair in seen_pairs:
            raise ValueError(f"Duplicate job-skill observation: {pair}")
        seen_pairs.add(pair)
        groups[(profile_by_job[job_id], skill_id)].append(
            (requirement, level, weight)
        )

    results = []
    for (profile_id, skill_id), observations in sorted(groups.items()):
        total_jobs = totals[profile_id]
        demand_count = len(observations)
        requirements = Counter(item[0] for item in observations)
        known_levels = Counter(
            level for _, level, _ in observations if level != "unknown"
        )
        level_count = sum(known_levels.values())
        target_level = "unknown"
        target_confidence = None
        if known_levels:
            highest_count = max(known_levels.values())
            winners = [
                level for level, count in known_levels.items() if count == highest_count
            ]
            if len(winners) == 1:
                target_level = winners[0]
                target_confidence = (
                    Decimal(highest_count) / Decimal(level_count)
                ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        results.append(
            CareerSkillStat(
                career_profile_id=profile_id,
                skill_id=skill_id,
                demand_count=demand_count,
                total_jobs=total_jobs,
                demand_percentage=(
                    Decimal(demand_count) * 100 / Decimal(total_jobs)
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                required_count=requirements["required"],
                preferred_count=requirements["preferred"],
                optional_count=requirements["optional"],
                weighted_demand_score=(
                    sum((weight for _, _, weight in observations), Decimal(0))
                    / Decimal(total_jobs)
                ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                target_level=target_level,
                target_level_confidence=target_confidence,
                level_observation_count=level_count,
            )
        )
    return results
