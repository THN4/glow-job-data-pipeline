"""Create an inspectable heading-aware chunk experiment from approved parse JSONL."""

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from src.documents.chunking.heading_chunker import chunk_parsed_document
from src.documents.schemas.candidate_page import ReviewStatus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHUNK_OUTPUT_ROOT = PROJECT_ROOT / "data" / "processed" / "documents" / "chunks"


def _read_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(rows: list[dict[str, Any]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temp_path, destination)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _write_markdown(rows: list[dict[str, Any]], destination: Path) -> None:
    parts = ["# Experimental document chunks", "", "Review this output for topic coherence, source traceability, code/list preservation, and chunk size. Oversized code blocks are kept whole and marked.", ""]
    for index, row in enumerate(rows, 1):
        parts.extend([
            f"## {index}. {row['topic']}",
            "",
            f"- Page: [{row.get('page_title') or row['source_url']}]({row['source_url']})",
            f"- Skill: {', '.join(row.get('skills', []))}",
            f"- Career: {', '.join(row.get('career_tracks', []))}",
            f"- Chunk index: {row['chunk_index']}",
            f"- Words: {row['word_count']}",
            f"- Review flags: {', '.join(row.get('review_flags', [])) or 'none'}",
            "",
            row["content"],
            "",
        ])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(parts), encoding="utf-8")


def _default_output_dir(input_path: Path) -> Path:
    """Keep chunk artifacts in a matching by-source or combined directory."""
    if input_path.parent.name == "combined":
        return CHUNK_OUTPUT_ROOT / "combined"
    return CHUNK_OUTPUT_ROOT / "by-source"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, help="Output folder; defaults to chunks/combined for combined input, otherwise chunks/by-source")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--max-words", type=int, default=400)
    args = parser.parse_args()
    try:
        documents = [row for row in _read_records(args.input) if row.get("review_status") == ReviewStatus.APPROVED.value]
        if not documents:
            raise ValueError("Input contains no approved parsed documents")
        chunk_records = [chunk.to_record() for document in documents for chunk in chunk_parsed_document(document, max_words=args.max_words)]
        output_dir = args.output_dir or _default_output_dir(args.input)
        jsonl_path = args.output or output_dir / f"{args.input.stem}-chunks.jsonl"
        markdown_path = args.markdown_output or output_dir / f"{args.input.stem}-chunks.md"
        _write_jsonl(chunk_records, jsonl_path)
        _write_markdown(chunk_records, markdown_path)
        print(json.dumps({
            "pages": len(documents),
            "chunks": len(chunk_records),
            "max_words": args.max_words,
            "oversized_code_chunks": sum("oversized_code_block" in row["review_flags"] for row in chunk_records),
            "jsonl_output": str(jsonl_path),
            "markdown_review": str(markdown_path),
        }, ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
