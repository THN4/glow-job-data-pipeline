from src.market.skill_extraction.catalog_rebuild_preview import (
    audit_skill_catalog_names,
    build_catalog_rebuild_preview,
)
from src.shared.skill_normalization.normalizer import build_skill_catalog


def _checkpoint(raw_name: str, evidence: str):
    return [
        {
            "extraction_status": "completed",
            "job": {
                "job_id": "job-1",
                "job_title": "Data Engineer",
                "career_name": "data_engineer",
            },
            "skills": [
                {
                    "raw_skill_name": raw_name,
                    "requirement_type": "required",
                    "proficiency_level": "unknown",
                    "evidence_text": evidence,
                }
            ],
        }
    ]


def test_preview_splits_composite_and_matches_each_component():
    catalog = build_skill_catalog(
        [(1, "Python", "programming_language"), (2, "SQL", "query_language")],
        [],
    )

    rows, summary = build_catalog_rebuild_preview(
        [("run-1", _checkpoint("Python, SQL", "Experience with Python, SQL."))],
        catalog,
    )

    assert rows == []
    assert summary["composite_occurrences_split"] == 1
    assert summary["split_components_created"] == 2
    assert summary["catalog_matched_occurrences"] == 2


def test_preview_queues_only_unknown_component_of_composite():
    catalog = build_skill_catalog([(1, "Python", "programming_language")], [])

    rows, summary = build_catalog_rebuild_preview(
        [("run-1", _checkpoint("Python, Rust", "Experience with Python, Rust."))],
        catalog,
    )

    assert len(rows) == 1
    assert rows[0]["candidate_name"] == "Rust"
    assert rows[0]["observed_names"] == ["Rust"]
    assert rows[0]["source_composite_names"] == ["Python, Rust"]
    assert summary["catalog_matched_occurrences"] == 1
    assert summary["composite_occurrences_split"] == 1


def test_preview_matches_verified_acronym_to_seed_canonical():
    catalog = build_skill_catalog([(1, "Machine Learning", "machine_learning")], [])

    rows, summary = build_catalog_rebuild_preview(
        [
            (
                "run-1",
                _checkpoint(
                    "Machine Learning (ML)",
                    "Experience with Machine Learning (ML).",
                ),
            )
        ],
        catalog,
    )

    assert rows == []
    assert summary["catalog_matched_occurrences"] == 1


def test_catalog_audit_flags_composite_alias_and_acronym_duplicate():
    report = audit_skill_catalog_names(
        [
            (1, "Machine Learning", "machine_learning", 8),
            (2, "Machine Learning (ML)", "machine_learning", 2),
        ],
        [(1, "Python, SQL", "Python", 3), (2, "ML", "Machine Learning", 4)],
    )

    assert len(report["duplicate_canonical_groups"]) == 1
    assert report["duplicate_canonical_groups"][0]["identity_key"] == "machine learning"
    assert report["composite_aliases"] == [
        {
            "alias_id": 1,
            "alias": "Python, SQL",
            "canonical_skill_name": "Python",
            "job_count": 3,
        }
    ]


def test_preview_groups_verified_acronym_variant_with_base_name():
    checkpoint = _checkpoint(
        "Machine Learning", "Experience with Machine Learning and ML."
    )
    checkpoint[0]["skills"].append(
        {
            "raw_skill_name": "Machine Learning (ML)",
            "requirement_type": "required",
            "proficiency_level": "unknown",
            "evidence_text": "Experience with Machine Learning and ML.",
        }
    )

    rows, _ = build_catalog_rebuild_preview([("run-1", checkpoint)], {})

    assert len(rows) == 1
    assert set(rows[0]["observed_names"]) == {
        "Machine Learning",
        "Machine Learning (ML)",
    }
    assert rows[0]["grouping_method"] == "format_variant"

