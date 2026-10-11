"""Environment-backed settings for reusable resume processing."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ResumeModelSettings(BaseSettings):
    """Settings shared by the resume CLI and backend model-provider factory."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    EXTRACTOR: Literal["mock", "openai-compatible", "ollama"] = "mock"
    MOCK_DELAY_MS: int = 3000
    LLM_BASE_URL: str | None = None
    LLM_MODEL: str | None = None
    LLM_API_KEY: str = "not-needed"
    LLM_TIMEOUT_MS: int = 180_000
    LLM_VISION: bool = True
    LLM_NUM_CTX: int = 16384
    LLM_THINK: bool = False
    MAX_PDF_PAGES: int = 10
    MAX_IMAGE_PAGES: int = 4

    @model_validator(mode="after")
    def _check_llm(self) -> "ResumeModelSettings":
        if self.EXTRACTOR in ("openai-compatible", "ollama") and not (self.LLM_BASE_URL and self.LLM_MODEL):
            raise ValueError(f"EXTRACTOR={self.EXTRACTOR} requires LLM_BASE_URL and LLM_MODEL")
        return self
