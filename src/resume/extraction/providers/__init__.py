"""Resume extraction provider implementations and their shared factory."""

from __future__ import annotations

from ...config import ResumeModelSettings
from ..contracts import Extractor, ExtractorOutput, PageImage, PreparedCv, Usage
from .mock import MockExtractor
from .ollama import OllamaExtractor
from .openai_compatible import OpenAiCompatibleExtractor


def create_extractor(cfg: ResumeModelSettings) -> Extractor:
    """Build a provider from any settings object exposing the resume model fields."""
    if cfg.EXTRACTOR == "ollama":
        return OllamaExtractor(
            base_url=cfg.LLM_BASE_URL or "",
            model=cfg.LLM_MODEL or "",
            timeout_ms=cfg.LLM_TIMEOUT_MS,
            vision=cfg.LLM_VISION,
            num_ctx=cfg.LLM_NUM_CTX,
            think=cfg.LLM_THINK,
        )
    if cfg.EXTRACTOR == "openai-compatible":
        return OpenAiCompatibleExtractor(
            base_url=cfg.LLM_BASE_URL or "",
            model=cfg.LLM_MODEL or "",
            api_key=cfg.LLM_API_KEY,
            timeout_ms=cfg.LLM_TIMEOUT_MS,
            vision=cfg.LLM_VISION,
        )
    return MockExtractor(cfg.MOCK_DELAY_MS)


__all__ = [
    "Extractor",
    "ExtractorOutput",
    "PageImage",
    "PreparedCv",
    "Usage",
    "MockExtractor",
    "OllamaExtractor",
    "OpenAiCompatibleExtractor",
    "create_extractor",
]
