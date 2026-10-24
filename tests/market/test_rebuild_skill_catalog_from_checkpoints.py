import json

import pytest

from scripts.market.rebuild_skill_catalog_from_checkpoints import _build_final_catalog


def test_catalog_rebuild_deduplicates_verified_acronym_canonical_names():
    rows = [
        {
            "candidate_name": "Machine Learning (ML)",
            "observed_names": ["Machine Learning (ML)"],
            "review_decision": "",
            "preview_status": "ready_for_approval",
            "confidence_level": "high",
            "suggestion_decision": "new_skill",
            "suggested_skill_name": "Machine Learning (ML)",
            "suggested_skill_category": "machine_learning",
        },
        {
            "candidate_name": "Machine Learning",
            "observed_names": ["Machine Learning"],
            "review_decision": "",
            "preview_status": "ready_for_approval",
            "confidence_level": "high",
            "suggestion_decision": "new_skill",
            "suggested_skill_name": "Machine Learning",
            "suggested_skill_category": "machine_learning",
        },
    ]

    records, decisions = _build_final_catalog(rows, [])

    assert len(records) == 1
    assert set(records[0][2]) == {"Machine Learning"}
    assert len(decisions) == 2
    assert {
        decision["suggested_skill_name"] for decision in decisions.values()
    } == {records[0][0]}


def test_catalog_rebuild_refuses_composite_phrase_as_single_alias():
    row = {
        "candidate_name": "Python, SQL",
        "observed_names": ["Python, SQL"],
        "review_decision": "map_existing",
        "canonical_skill_name": "Python",
    }

    with pytest.raises(ValueError, match="cannot be stored as a single-skill alias"):
        _build_final_catalog([row], [("Python", "programming_language", [])])


def test_catalog_rebuild_deduplicates_verified_acronym_initial_records():
    records, decisions = _build_final_catalog(
        [],
        [
            ("Machine Learning", "machine_learning", []),
            ("Machine Learning (ML)", "machine_learning", []),
        ],
    )

    assert len(records) == 1
    assert records[0][0] == "Machine Learning"
    assert records[0][2] == ["Machine Learning (ML)"]
    assert decisions == {}


@pytest.mark.parametrize(
    ("canonical", "duplicate", "category"),
    [
        ("A/B testing", "A/B tests", "data_practice"),
        ("Google Analytics", "GA4", "other"),
    ],
)
def test_catalog_rebuild_maps_duplicate_candidate_to_canonical(
    canonical, duplicate, category
):
    rows = [
        {
            "candidate_name": canonical,
            "observed_names": [canonical],
            "review_decision": "",
            "preview_status": "ready_for_approval",
            "confidence_level": "high",
            "suggestion_decision": "new_skill",
            "suggested_skill_name": canonical,
            "suggested_skill_category": category,
        },
        {
            "candidate_name": duplicate,
            "observed_names": [duplicate],
            "review_decision": "map_existing",
            "canonical_skill_name": canonical,
        },
    ]

    records, decisions = _build_final_catalog(rows, [])

    assert len(records) == 1
    assert records[0][0] == canonical
    assert duplicate in records[0][2]
    assert decisions[duplicate.casefold()]["resolution_status"] == "mapped_existing"


def test_catalog_rebuild_applies_split_without_composite_alias():
    row = {
        "candidate_name": "Python, SQL",
        "observed_names": ["Python, SQL"],
        "review_decision": "split_into_skills",
        "split_skills": json.dumps(
            [
                {"decision": "map_existing", "skill_name": "Python"},
                {
                    "decision": "create_new",
                    "skill_name": "SQL",
                    "skill_category": "query_language",
                },
            ]
        ),
    }

    records, decisions = _build_final_catalog(
        [row], [("Python", "programming_language", [])]
    )

    assert {record[0] for record in records} == {"Python", "SQL"}
    assert all("Python, SQL" not in record[2] for record in records)
    assert decisions["python, sql"]["resolution_status"] == "split_applied"
