"""Structured text chunk and source metadata for retrieval experiments."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DocumentChunk:
    """One heading-aware chunk with enough provenance for review and citation."""

    source_config_id: str
    source_url: str
    canonical_url: str | None
    page_title: str | None
    career_tracks: tuple[str, ...]
    skills: tuple[str, ...]
    chunk_index: int
    topic: str
    heading_path: tuple[str, ...]
    content: str
    word_count: int
    content_hash: str
    review_flags: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["career_tracks"] = list(self.career_tracks)
        record["skills"] = list(self.skills)
        record["heading_path"] = list(self.heading_path)
        record["review_flags"] = list(self.review_flags)
        return record
