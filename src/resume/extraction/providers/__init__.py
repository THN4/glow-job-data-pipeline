"""Resume extraction provider implementations and their shared factory."""

from __future__ import annotations

from ...config import ResumeModelSettings
from ..contracts import Extractor, ExtractorOutput, PageImage, PreparedCv, Usage
from .gemini import GeminiExtractor
from .mock import MockExtractor


def create_extractor(cfg: ResumeModelSettings) -> Extractor:
    """Build a provider from any settings object exposing the resume model fields."""
    if cfg.RESUME_EXTRACTOR == "bedrock_converse":
        from .bedrock import BedrockExtractor

        return BedrockExtractor(
            region=cfg.AWS_REGION or cfg.AWS_DEFAULT_REGION,
            model_id=cfg.BEDROCK_EXTRACTION_MODEL,
            timeout_ms=cfg.RESUME_BEDROCK_TIMEOUT_MS,
        )
    if cfg.RESUME_EXTRACTOR == "gemini":
        return GeminiExtractor(
            api_key=cfg.GEMINI_API_KEY or "",
            timeout_ms=cfg.RESUME_GEMINI_TIMEOUT_MS,
        )
    return MockExtractor(cfg.MOCK_DELAY_MS)


__all__ = [
    "Extractor",
    "ExtractorOutput",
    "PageImage",
    "PreparedCv",
    "Usage",
    "MockExtractor",
    "GeminiExtractor",
    "create_extractor",
]
