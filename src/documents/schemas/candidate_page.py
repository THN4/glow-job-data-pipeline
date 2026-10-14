"""Candidate-page records produced during bounded source discovery."""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class FetchStatus(str, Enum):
    """Outcome of fetching and inspecting a discovered page."""

    FETCHED = "fetched"
    FAILED = "failed"
    BLOCKED_BY_ROBOTS = "blocked_by_robots"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"


class ReviewStatus(str, Enum):
    """Human review state before a page can enter the knowledge corpus."""

    PENDING = "pending"
    APPROVED = "approved"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class CandidatePage:
    """One discovered page and the metadata needed to review it."""

    source_config_id: str
    url: str
    crawl_depth: int
    career_tracks: tuple[str, ...]
    skills: tuple[str, ...]
    fetch_status: FetchStatus
    review_status: ReviewStatus = ReviewStatus.PENDING
    canonical_url: str | None = None
    title: str | None = None
    publisher: str | None = None
    source_type: str | None = None
    content_type: str | None = None
    headings: tuple[str, ...] = ()
    content_hash: str | None = None
    http_status: int | None = None
    error_message: str | None = None

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-serializable record for the crawl manifest."""
        record = asdict(self)
        record["fetch_status"] = self.fetch_status.value
        record["review_status"] = self.review_status.value
        record["career_tracks"] = list(self.career_tracks)
        record["skills"] = list(self.skills)
        record["headings"] = list(self.headings)
        return record