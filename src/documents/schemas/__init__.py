"""Data contracts for source documents, crawl candidates, and chunks."""

from src.documents.schemas.candidate_page import (
    CandidatePage,
    FetchStatus,
    ReviewStatus,
)
from src.documents.schemas.document_chunk import DocumentChunk
from src.documents.schemas.source_config import (
    DocumentSourcesConfig,
    SourceConfig,
    load_document_sources,
    select_document_source,
)

__all__ = [
    "CandidatePage",
    "DocumentSourcesConfig",
    "DocumentChunk",
    "FetchStatus",
    "ReviewStatus",
    "SourceConfig",
    "load_document_sources",
    "select_document_source",
]
