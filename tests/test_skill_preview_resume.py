import csv
import json

from scripts.preview_skill_catalog_rebuild import _resume_existing_rows


def test_resume_expands_saved_comma_split_decision_to_components(tmp_path):
    path = tmp_path / "preview.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "candidate_name",
                "observed_names",
                "review_decision",
                "split_skills",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "candidate_name": "Python, SQL",
                "observed_names": json.dumps(["Python, SQL"]),
                "review_decision": "split_into_skills",
                "split_skills": json.dumps(
                    [
                        {
                            "decision": "map_existing",
                            "skill_name": "Python",
                            "skill_category": "",
                        },
                        {
                            "decision": "create_new",
                            "skill_name": "SQL",
                            "skill_category": "query_language",
                        },
                    ]
                ),
            }
        )

    rows = [
        {
            "candidate_name": "Python",
            "observed_names": ["Python"],
            "review_decision": "",
            "canonical_skill_name": "",
            "skill_category": "",
            "split_skills": "[]",
            "possible_duplicate_candidates": "",
        },
        {
            "candidate_name": "SQL",
            "observed_names": ["SQL"],
            "review_decision": "",
            "canonical_skill_name": "",
            "skill_category": "",
            "split_skills": "[]",
            "possible_duplicate_candidates": "",
        },
    ]

    _resume_existing_rows(rows, path)

    assert rows[0]["review_decision"] == "map_existing"
    assert rows[0]["canonical_skill_name"] == "Python"
    assert rows[1]["review_decision"] == "create_new"
    assert rows[1]["canonical_skill_name"] == "SQL"
    assert rows[1]["skill_category"] == "query_language"
