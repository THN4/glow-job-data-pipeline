"""Split parsed sections into heading-aware chunks for retrieval experiments."""

from hashlib import sha256
import re
from typing import Any

from src.documents.schemas.document_chunk import DocumentChunk


_CODE_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'])")


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))


def _split_long_text(text: str, max_words: int) -> list[str]:
    """Split a long prose block at sentence boundaries, then word boundaries."""
    sentences = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(text) if part.strip()]
    if len(sentences) <= 1:
        words = text.split()
        return [" ".join(words[index:index + max_words]) for index in range(0, len(words), max_words)]

    pieces: list[str] = []
    current: list[str] = []
    current_words = 0
    for sentence in sentences:
        count = _word_count(sentence)
        if count > max_words:
            if current:
                pieces.append(" ".join(current))
                current, current_words = [], 0
            words = sentence.split()
            pieces.extend(" ".join(words[index:index + max_words]) for index in range(0, len(words), max_words))
        elif current and current_words + count > max_words:
            pieces.append(" ".join(current))
            current, current_words = [sentence], count
        else:
            current.append(sentence)
            current_words += count
    if current:
        pieces.append(" ".join(current))
    return pieces


def _split_section(text: str, max_words: int) -> list[tuple[str, tuple[str, ...]]]:
    """Pack paragraphs up to the target size while keeping fenced code intact."""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    if not blocks:
        return []

    atomic_blocks: list[tuple[str, bool]] = []
    for block in blocks:
        is_code = bool(_CODE_FENCE_RE.match(block))
        if not is_code and _word_count(block) > max_words:
            atomic_blocks.extend((piece, False) for piece in _split_long_text(block, max_words))
        else:
            atomic_blocks.append((block, is_code))

    chunks: list[tuple[str, tuple[str, ...]]] = []
    current: list[str] = []
    current_words = 0
    for block, is_code in atomic_blocks:
        count = _word_count(block)
        if current and current_words + count > max_words:
            chunks.append(("\n\n".join(current), ()))
            current, current_words = [], 0
        current.append(block)
        current_words += count
        if is_code and count > max_words:
            chunks.append(("\n\n".join(current), ("oversized_code_block",)))
            current, current_words = [], 0
    if current:
        chunks.append(("\n\n".join(current), ()))
    return chunks


def chunk_parsed_document(
    document: dict[str, Any], *, max_words: int = 400
) -> list[DocumentChunk]:
    """Chunk a parsed-page record, preserving section headings and provenance.

    Sections up to ``max_words`` remain intact. Longer prose is split at
    paragraph/sentence boundaries; fenced code blocks remain atomic and are
    flagged when they exceed the target size. No overlap is added in this
    experiment to avoid duplicating evidence before retrieval is evaluated.
    """
    if max_words < 1:
        raise ValueError("max_words must be a positive integer")

    results: list[DocumentChunk] = []
    for section in document.get("sections", []):
        heading_path = tuple(section.get("heading_path", []))
        body = str(section.get("text", "")).strip()
        if not body:
            continue
        topic = heading_path[-1] if heading_path else (document.get("title") or "Untitled section")
        prefix = " > ".join(heading_path) if heading_path else str(document.get("title") or "")
        for piece, flags in _split_section(body, max_words):
            content = f"{prefix}\n\n{piece}" if prefix else piece
            normalized = re.sub(r"\s+", " ", content).strip()
            results.append(DocumentChunk(
                source_config_id=str(document["source_config_id"]),
                source_url=str(document["url"]),
                canonical_url=document.get("canonical_url"),
                page_title=document.get("title"),
                career_tracks=tuple(document.get("career_tracks", [])),
                skills=tuple(document.get("skills", [])),
                chunk_index=len(results),
                topic=str(topic),
                heading_path=heading_path,
                content=content,
                word_count=_word_count(content),
                content_hash=sha256(normalized.encode("utf-8")).hexdigest(),
                review_flags=flags,
            ))
    return results
