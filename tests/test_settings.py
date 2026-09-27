"""Tests for user-editable pipeline configuration."""

from pathlib import Path
import pytest
from src.config.settings import load_settings


def test_default_configuration_loads() -> None:
    settings = load_settings()
    assert settings.pipeline.country == "TH"
    assert settings.pipeline.time_window_days == 90
    assert settings.careers["data_engineer"].queries


def test_careers_can_be_added_without_code_changes(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text(
        "country: TH\ntime_window_days: 30\nresults_per_query: 10\n"
        "max_pages: 2\nminimum_description_length: 50\n",
        encoding="utf-8",
    )
    (tmp_path / "careers.yaml").write_text(
        "careers:\n  security_analyst:\n    career_name: Security Analyst\n"
        "    queries: [Security Analyst]\n",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path)
    assert settings.careers["security_analyst"].queries == ("Security Analyst",)


def test_invalid_pipeline_limit_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text(
        "country: TH\ntime_window_days: 0\nresults_per_query: 10\n"
        "max_pages: 2\nminimum_description_length: 50\n",
        encoding="utf-8",
    )
    (tmp_path / "careers.yaml").write_text(
        "careers:\n  analyst:\n    career_name: Analyst\n    queries: [Analyst]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="positive integers"):
        load_settings(tmp_path)
