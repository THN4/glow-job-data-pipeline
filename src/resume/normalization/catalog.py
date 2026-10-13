"""Resolve CV skill labels against the shared catalog without changing extraction."""

from __future__ import annotations

from typing import Any

from src.resume.schemas.cv_extraction import CatalogMatch, CvProfile
from src.shared.skill_normalization.normalizer import match_catalog_skill


def resolve_profile_catalog_matches(
    profile: CvProfile,
    catalog: dict[str, dict[str, object]],
) -> CvProfile:
    """Return a profile annotated with Market's deterministic catalog matches.

    The catalog is supplied by the caller, so this function is pure and has no
    database dependency. Raw CV labels and evidence are preserved. Only the
    profile's technical skills and tools are catalog candidates; soft skills
    and spoken languages are not mapped to the technical skill catalog.
    """

    def resolve_item(item: Any) -> Any:
        found = match_catalog_skill(getattr(item, "raw_name", None) or item.name, catalog)
        if found is None:
            match = CatalogMatch(status="unmatched")
        else:
            match = CatalogMatch(
                status="matched",
                skill_id=int(found["skill_id"]),
                canonical_name=str(found["skill_name"]),
                match_method=str(found["match_method"]),
            )
        return item.model_copy(
            update={
                "catalog_match": match,
                "needs_review": item.needs_review or match.status == "unmatched",
            }
        )

    return profile.model_copy(
        update={
            "technical_skills": [resolve_item(item) for item in profile.technical_skills],
            "tools": [resolve_item(item) for item in profile.tools],
        }
    )
