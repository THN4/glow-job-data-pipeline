import pytest

from scripts.seed_skill_catalog import load_skill_records


def test_reviewed_catalog_contains_aliases_but_not_unconfirmed_etl_mapping():
    records = load_skill_records()
    by_name = {name: aliases for name, _, aliases in records}

    assert "Postgres" in by_name["PostgreSQL"]
    assert "Spark" in by_name["Apache Spark"]
    assert "ETL Pipeline" not in by_name["ETL"]


def test_catalog_rejects_alias_that_conflicts_with_another_skill(tmp_path):
    catalog = tmp_path / "skills.yaml"
    catalog.write_text(
        """skills:
  first:
    skill_name: PostgreSQL
    skill_category: database
    aliases: [Postgres]
  second:
    skill_name: Postgres
    skill_category: database
    aliases: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate skill name or alias"):
        load_skill_records(catalog)
