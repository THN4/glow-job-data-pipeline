from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..schemas.cv_extraction import CvExtraction

__all__ = ["Extractor", "ExtractorOutput", "PageImage", "PreparedCv", "Usage"]


@dataclass
class PageImage:
    b64: str
    mime: str = "image/jpeg"


@dataclass
class PreparedCv:
    """Model input: extracted text (preferred) or page images (scans / photos)."""

    kind: Literal["text", "images"]
    page_count: int
    text: str = ""
    images: list[PageImage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ExtractorOutput:
    extraction: CvExtraction
    usage: Usage | None = None


class Extractor(Protocol):
    """Everything model-specific lives behind this interface."""

    #: Model name reported in result metadata, e.g. "qwen3-vl:8b" or "mock".
    name: str
    #: False for the mock: its fixture data has nothing to do with the uploaded file.
    groundable: bool

    async def extract(self, prepared: PreparedCv) -> ExtractorOutput: ...
