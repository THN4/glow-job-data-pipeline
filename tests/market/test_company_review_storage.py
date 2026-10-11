import csv

import pytest

from src.market.normalization.company_review_storage import save_company_match_candidates


def test_save_company_match_candidates_writes_reviewable_rows(tmp_path) -> None:
    jobs = [
        {
            "job": {
                "job_id": "job-123",
                "job_title": "Data Engineer",
                "employer_name": "Siam Commercial Ban",
                "employer_website": "https://scb.example",
                "job_publisher": "LinkedIn",
                "job_url": "https://linkedin.example/jobs/123",
                "company_normalization": {
                    "normalized_name": "siam commercial ban",
                    "candidates": [
                        {
                            "canonical_name": "Siam Commercial Bank",
                            "matched_alias": "siam commercial bank",
                            "score": 97.1,
                            "candidate_source": "configured_alias",
                        }
                    ],
                },
            },
            "matches": [
                {"query_number": 1},
                {"query_number": 3},
            ],
        }
    ]

    report_path = save_company_match_candidates(
        jobs, run_id="run-001", output_dir=tmp_path
    )

    assert report_path == tmp_path / "run-001.csv"
    with report_path.open(encoding="utf-8-sig", newline="") as report_file:
        rows = list(csv.DictReader(report_file))

    assert rows == [
        {
            "run_id": "run-001",
            "query_numbers": "1,3",
            "job_id": "job-123",
            "job_title": "Data Engineer",
            "employer_name": "Siam Commercial Ban",
            "employer_website": "https://scb.example",
            "normalized_company_name": "siam commercial ban",
            "candidate_company": "Siam Commercial Bank",
            "candidate_matched_alias": "siam commercial bank",
            "candidate_score": "97.1",
            "candidate_source": "configured_alias",
            "publisher": "LinkedIn",
            "source_url": "https://linkedin.example/jobs/123",
            "review_decision": "",
            "confirmed_company_name": "",
        }
    ]


def test_save_company_match_candidates_writes_header_when_no_candidates(tmp_path) -> None:
    report_path = save_company_match_candidates(
        [{"job": {"company_normalization": {"candidates": []}}}],
        run_id="run-001",
        output_dir=tmp_path,
    )

    assert report_path == tmp_path / "run-001.csv"
    with report_path.open(encoding="utf-8-sig", newline="") as report_file:
        assert list(csv.DictReader(report_file)) == []


def test_save_company_match_candidates_rejects_unsafe_run_id(tmp_path) -> None:
    with pytest.raises(ValueError, match="run_id may contain only"):
        save_company_match_candidates(
            [], run_id="../outside", output_dir=tmp_path
        )
