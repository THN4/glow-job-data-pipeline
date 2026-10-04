from pathlib import Path

import pytest

from src.config.settings import load_settings


def test_default_configuration_loads() -> None:
    settings = load_settings()

    assert settings.search.country == "TH"
    assert settings.search.max_pages == 1
    assert settings.search.date_posted == "all"
    assert settings.validation.time_window_days == 90
    assert settings.validation.minimum_description_length == 100
    assert settings.careers["data_engineer"].queries
    assert "Cloud Data Engineer" in settings.careers["data_engineer"].title_aliases


def test_careers_can_be_added_without_code_changes(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text(
        "search:\n  country: TH\n  max_pages: 2\n  date_posted: month\n"
        "validation:\n  time_window_days: 30\n"
        "  minimum_description_length: 50\n",
        encoding="utf-8",
    )
    (tmp_path / "careers.yaml").write_text(
        "careers:\n  security_analyst:\n    career_name: Security Analyst\n"
        "    queries: [Security Analyst]\n",
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)

    assert settings.careers["security_analyst"].queries == ("Security Analyst",)
    assert settings.search.max_pages == 2
    assert settings.validation.time_window_days == 30


def test_invalid_validation_limit_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text(
        "search:\n  country: TH\n  max_pages: 1\n  date_posted: all\n"
        "validation:\n  time_window_days: 0\n"
        "  minimum_description_length: 50\n",
        encoding="utf-8",
    )
    (tmp_path / "careers.yaml").write_text(
        "careers:\n  analyst:\n    career_name: Analyst\n    queries: [Analyst]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Validation limits must be positive integers"):
        load_settings(tmp_path)


def test_unsupported_date_posted_filter_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text(
        "search:\n  country: TH\n  max_pages: 1\n  date_posted: 90days\n"
        "validation:\n  time_window_days: 90\n"
        "  minimum_description_length: 50\n",
        encoding="utf-8",
    )
    (tmp_path / "careers.yaml").write_text(
        "careers:\n  analyst:\n    career_name: Analyst\n    queries: [Analyst]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Search date_posted must be one of"):
        load_settings(tmp_path)
