from src.market.normalization.company_normalizer import (
    normalize_company,
    normalize_company_key,
    normalize_job_companies,
)


def test_normalize_company_key_removes_formatting_and_trailing_legal_suffix() -> None:
    assert (
        normalize_company_key("  The Siam Commercial Bank, P.C.L.  ")
        == "the siam commercial bank"
    )


def test_normalize_company_resolves_confirmed_alias() -> None:
    result = normalize_company("SCB")

    assert result == {
        "normalized_name": "scb",
        "canonical_name": "Siam Commercial Bank",
        "match_method": "confirmed_alias",
        "candidates": [],
    }


def test_normalize_company_suggests_fuzzy_candidate_without_auto_resolving() -> None:
    result = normalize_company("Siam Commercial Ban")

    assert result["canonical_name"] is None
    assert result["match_method"] == "candidate_review"
    candidates = result["candidates"]
    assert isinstance(candidates, list)
    assert candidates[0]["canonical_name"] == "Siam Commercial Bank"
    assert candidates[0]["score"] >= 85


def test_normalize_company_leaves_unrelated_name_unmatched() -> None:
    result = normalize_company("Quantum Zzz Corporation")

    assert result["canonical_name"] is None
    assert result["match_method"] == "unmatched"
    assert result["candidates"] == []


def test_normalize_company_does_not_suggest_unrelated_banks() -> None:
    result = normalize_company(
        "TMBThanachart Bank or ttb / ทีเอ็มบีธนชาต หรือ ทีทีบี"
    )

    assert result["canonical_name"] is None
    assert result["match_method"] == "unmatched"
    assert result["candidates"] == []


def test_normalize_company_handles_missing_name() -> None:
    assert normalize_company(None) == {
        "normalized_name": None,
        "canonical_name": None,
        "match_method": "missing",
        "candidates": [],
    }


def test_normalize_job_companies_preserves_original_name_and_input() -> None:
    entry = {"job": {"employer_name": "SCB"}, "metadata": {"query": "engineer"}}

    result = normalize_job_companies([entry])

    assert result[0]["job"]["employer_name"] == "SCB"
    assert result[0]["job"]["company_normalization"]["canonical_name"] == (
        "Siam Commercial Bank"
    )
    assert "company_normalization" not in entry["job"]


def test_normalize_job_companies_suggests_similar_names_seen_in_same_batch() -> None:
    jobs = [
        {"job": {"employer_name": "Acme Data Technologies"}},
        {"job": {"employer_name": "Acme Data Technologis"}},
    ]

    normalized = normalize_job_companies(jobs)

    first_result = normalized[0]["job"]["company_normalization"]
    assert first_result["canonical_name"] is None
    assert first_result["match_method"] == "candidate_review"
    candidate = first_result["candidates"][0]
    assert candidate["canonical_name"] == "Acme Data Technologis"
    assert candidate["candidate_source"] == "same_run"
