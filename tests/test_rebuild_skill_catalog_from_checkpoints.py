import pytest

from scripts.rebuild_skill_catalog_from_checkpoints import _build_final_catalog


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
