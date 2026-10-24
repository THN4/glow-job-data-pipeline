"""Normalize company names and suggest possible aliases for review."""

import re
import unicodedata
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALIAS_FILE = PROJECT_ROOT / "config" / "company_aliases.yaml"

# These suffixes are removed only at the end of a name. They are formatting
# clues, not proof that two different companies are the same.
_LEGAL_SUFFIXES = (
    "public company limited",
    "company limited",
    "co limited",
    "co ltd",
    "limited",
    "ltd",
    "public company",
    "p c l",
    "pcl",
    "incorporated",
    "inc",
    "corporation",
    "corp",
    "llc",
)


def normalize_company_key(value: object) -> str | None:
    """Return a conservative comparison key without changing source data."""
    if not isinstance(value, str):
        return None

    text = unicodedata.normalize("NFKC", value).casefold().strip()
    if not text:
        return None

    # Make punctuation and repeated whitespace consistent while retaining
    # letters from non-English company names.
    text = "".join(char if char.isalnum() else " " for char in text)
    text = re.sub(r"\s+", " ", text).strip()

    changed = True
    while changed and text:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if text == suffix:
                text = ""
                changed = True
                break
            if text.endswith(f" {suffix}"):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
                break

    return text or None


def _load_company_registry(alias_file: Path) -> dict[str, dict[str, object]]:
    with alias_file.open(encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file)

    if not isinstance(data, dict) or not isinstance(data.get("companies"), dict):
        raise ValueError(f"Expected a 'companies' mapping in {alias_file}")

    registry: dict[str, dict[str, object]] = {}
    for slug, entry in data["companies"].items():
        if not isinstance(slug, str) or not isinstance(entry, dict):
            raise ValueError(f"Invalid company alias entry in {alias_file}")
        canonical_name = entry.get("canonical_name")
        aliases = entry.get("aliases", [])
        if not isinstance(canonical_name, str) or not canonical_name.strip():
            raise ValueError(f"Company {slug} requires a canonical_name")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ValueError(f"Company {slug} aliases must be non-empty strings")

        names = [canonical_name, *aliases]
        for name in names:
            key = normalize_company_key(name)
            if key is None:
                continue
            existing = registry.get(key)
            if existing is not None and existing["canonical_name"] != canonical_name:
                raise ValueError(
                    f"Company alias {name!r} maps to multiple canonical companies"
                )
            registry[key] = {
                "slug": slug,
                "canonical_name": canonical_name.strip(),
            }

    return registry


def normalize_company(
    value: object,
    *,
    alias_file: Path = DEFAULT_ALIAS_FILE,
    candidate_limit: int = 3,
    candidate_score_cutoff: float = 90.0,
) -> dict[str, object]:
    """Return a normalized key, confirmed alias match, and review candidates.

    Fuzzy matches are suggestions only; they never select a canonical company.
    """
    return _normalize_company(
        value,
        _load_company_registry(alias_file),
        candidate_limit,
        candidate_score_cutoff,
    )


def _normalize_company(
    value: object,
    registry: dict[str, dict[str, object]],
    candidate_limit: int,
    candidate_score_cutoff: float,
) -> dict[str, object]:
    key = normalize_company_key(value)
    result: dict[str, object] = {
        "normalized_name": key,
        "canonical_name": None,
        "match_method": "unmatched",
        "candidates": [],
    }
    if key is None:
        result["match_method"] = "missing"
        return result

    exact = registry.get(key)
    if exact is not None:
        result["canonical_name"] = exact["canonical_name"]
        result["match_method"] = "confirmed_alias"
        return result

    # Compare against known aliases, then retain the best score per company.
    matches = process.extract(
        key,
        list(registry),
        scorer=fuzz.ratio,
        limit=max(candidate_limit * 3, candidate_limit),
        score_cutoff=candidate_score_cutoff,
    )
    best_by_company: dict[str, dict[str, object]] = {}
    for matched_alias, score, _ in matches:
        company = registry[matched_alias]
        canonical_name = str(company["canonical_name"])
        candidate = {
            "slug": company["slug"],
            "canonical_name": canonical_name,
            "matched_alias": matched_alias,
            "score": round(float(score), 1),
            "candidate_source": "configured_alias",
        }
        previous = best_by_company.get(canonical_name)
        if previous is None or candidate["score"] > previous["score"]:
            best_by_company[canonical_name] = candidate

    candidates = sorted(
        best_by_company.values(), key=lambda item: item["score"], reverse=True
    )[:candidate_limit]
    result["candidates"] = candidates
    result["match_method"] = "candidate_review" if candidates else "unmatched"
    return result


def normalize_job_companies(
    jobs: list[dict[str, object]], *, alias_file: Path = DEFAULT_ALIAS_FILE
) -> list[dict[str, object]]:
    """Copy job entries and annotate company names without replacing raw names."""
    registry = _load_company_registry(alias_file)
    observed_names: dict[str, str] = {}
    for entry in jobs:
        job = entry.get("job")
        if isinstance(job, dict):
            raw_name = job.get("employer_name")
            key = normalize_company_key(raw_name)
            if key is not None and isinstance(raw_name, str):
                observed_names.setdefault(key, raw_name.strip())

    normalized_jobs: list[dict[str, object]] = []
    for entry in jobs:
        normalized_entry = dict(entry)
        source_job = entry.get("job")
        if isinstance(source_job, dict):
            job = dict(source_job)
            normalization = _normalize_company(
                job.get("employer_name"),
                registry,
                candidate_limit=3,
                candidate_score_cutoff=90.0,
            )
            key = normalization["normalized_name"]
            if isinstance(key, str) and normalization["canonical_name"] is None:
                existing_candidates = normalization["candidates"]
                assert isinstance(existing_candidates, list)
                known_candidate_names = {
                    candidate.get("canonical_name")
                    for candidate in existing_candidates
                    if isinstance(candidate, dict)
                }
                observed_candidates = process.extract(
                    key,
                    [name_key for name_key in observed_names if name_key != key],
                    scorer=fuzz.ratio,
                    limit=3,
                    score_cutoff=90.0,
                )
                for matched_name, score, _ in observed_candidates:
                    candidate_name = observed_names[matched_name]
                    if candidate_name in known_candidate_names:
                        continue
                    existing_candidates.append(
                        {
                            "slug": None,
                            "canonical_name": candidate_name,
                            "matched_alias": matched_name,
                            "score": round(float(score), 1),
                            "candidate_source": "same_run",
                        }
                    )
                    known_candidate_names.add(candidate_name)
                if existing_candidates:
                    normalization["candidates"] = sorted(
                        existing_candidates,
                        key=lambda candidate: candidate["score"],
                        reverse=True,
                    )[:3]
                    normalization["match_method"] = "candidate_review"
            job["company_normalization"] = normalization
            normalized_entry["job"] = job
        normalized_jobs.append(normalized_entry)
    return normalized_jobs
