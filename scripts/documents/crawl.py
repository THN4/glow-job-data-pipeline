"""Run bounded document-page discovery and write a review manifest."""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.documents.ingestion.crawler import BoundedHTMLCrawler
from src.documents.ingestion.manifest import write_candidate_manifest
from src.documents.schemas.source_config import (
    load_document_sources,
    select_document_source,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "document_sources.yaml"
DEFAULT_MANIFEST_DIR = PROJECT_ROOT / "data" / "raw" / "documents" / "crawl-manifests"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--request-interval", type=float, default=1.0)
    arguments = parser.parse_args()

    try:
        config = load_document_sources(arguments.config)
        source = select_document_source(config, arguments.source_id)
        crawler = BoundedHTMLCrawler(
            request_interval_seconds=arguments.request_interval
        )
        try:
            pages = crawler.crawl(source)
        finally:
            crawler.close()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = arguments.output or (
            DEFAULT_MANIFEST_DIR / f"{source.id}-{timestamp}.jsonl"
        )
        row_count = write_candidate_manifest(pages, output)
        summary = {
            "source_id": source.id,
            "manifest_path": str(output),
            "candidate_count": row_count,
            "allowed_hosts": list(source.allowed_hosts),
            "allowed_path_prefixes": list(source.allowed_path_prefixes),
            "fetch_status_counts": dict(
                Counter(page.fetch_status.value for page in pages)
            ),
            "review_status_counts": dict(
                Counter(page.review_status.value for page in pages)
            ),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()