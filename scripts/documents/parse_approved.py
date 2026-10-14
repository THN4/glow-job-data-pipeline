"""Parse approved HTML candidates into a heading-based JSONL review artifact."""

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from src.documents.ingestion.crawler import BoundedHTMLCrawler, _decode_html
from src.documents.parsing.html_document import parse_html_document
from src.documents.schemas.candidate_page import FetchStatus, ReviewStatus
from src.documents.schemas.source_config import load_document_sources, select_document_source

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "document_sources.yaml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "documents" / "parsed-pages" / "by-source"


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_records(rows: list[dict[str, object]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as output:
            temp_path = Path(output.name)
            for row in rows:
                output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temp_path, destination)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--reviewed-manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--request-interval", type=float, default=1.0)
    args = parser.parse_args()
    try:
        source = select_document_source(load_document_sources(args.config), args.source_id)
        candidates = [
            row for row in _records(args.reviewed_manifest)
            if row.get("source_config_id") == args.source_id
            and row.get("review_status") == ReviewStatus.APPROVED.value
        ]
        if not candidates:
            raise ValueError(f"No approved pages found for source {args.source_id!r}")
        crawler = BoundedHTMLCrawler(request_interval_seconds=args.request_interval)
        parsed_rows: list[dict[str, object]] = []
        try:
            for candidate in candidates:
                url = str(candidate["url"])
                fetched, body, content_type_header = crawler.fetch_approved_page(url, source)
                if fetched.fetch_status != FetchStatus.FETCHED or body is None:
                    raise ValueError(f"Could not fetch approved URL {url}: {fetched.error_message or fetched.fetch_status.value}")
                actual_hash = sha256(body).hexdigest()
                if candidate.get("content_hash") and candidate["content_hash"] != actual_hash:
                    raise ValueError(f"Page changed after review; recrawl and review again: {url}")
                html = _decode_html(body, content_type_header or fetched.content_type or "text/html")
                document = parse_html_document(html)
                parsed_rows.append({
                    "source_config_id": args.source_id,
                    "url": url,
                    "canonical_url": fetched.canonical_url,
                    "title": fetched.title or document.title or candidate.get("title"),
                    "publisher": candidate.get("publisher") or source.publisher,
                    "career_tracks": candidate.get("career_tracks", list(source.career_tracks)),
                    "skills": candidate.get("skills", list(source.skills)),
                    "content_type": fetched.content_type,
                    "content_hash": actual_hash,
                    "review_status": ReviewStatus.APPROVED.value,
                    "sections": document.to_record()["sections"],
                })
        finally:
            crawler.close()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = args.output or DEFAULT_OUTPUT_DIR / f"{args.source_id}-{timestamp}.jsonl"
        _write_records(parsed_rows, output)
        print(json.dumps({"source_id": args.source_id, "parsed_output": str(output), "approved_pages": len(parsed_rows), "section_count": sum(len(row["sections"]) for row in parsed_rows)}, ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
