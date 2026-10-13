"""Environment-backed settings for reusable resume processing."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ResumeModelSettings(BaseSettings):
    """Settings shared by the resume CLI and backend model-provider factory."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    RESUME_EXTRACTOR: Literal["mock", "gemini"] = Field(
        default="mock", validation_alias=AliasChoices("RESUME_EXTRACTOR", "EXTRACTOR")
    )
    MOCK_DELAY_MS: int = 3000
    GEMINI_API_KEY: str | None = None
    RESUME_GEMINI_TIMEOUT_MS: int = 180_000
    MAX_PDF_PAGES: int = Field(default=10, ge=1)
    MAX_IMAGE_PAGES: int = Field(default=4, ge=1)
