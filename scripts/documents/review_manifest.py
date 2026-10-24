"""Apply an explicit human review decision to crawl-manifest URLs."""

import argparse
import json
from pathlib import Path

from src.documents.schemas.candidate_page import FetchStatus, ReviewStatus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--approve-url", action="append", default=[])
    parser.add_argument("--exclude-url", action="append", default=[])
    args = parser.parse_args()
    approve = set(args.approve_url)
    exclude = set(args.exclude_url)
    if approve & exclude:
        parser.error("a URL cannot be both approved and excluded")
    try:
        records = [
            json.loads(line)
            for line in args.manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        found: set[str] = set()
        for record in records:
            url = record.get("url")
            if url in approve:
                if record.get("fetch_status") != FetchStatus.FETCHED.value:
                    raise ValueError(f"Cannot approve a page that was not fetched: {url}")
                record["review_status"] = ReviewStatus.APPROVED.value
                found.add(url)
            elif url in exclude:
                record["review_status"] = ReviewStatus.EXCLUDED.value
                found.add(url)
        missing = (approve | exclude) - found
        if missing:
            raise ValueError("URLs are not present in the manifest: " + ", ".join(sorted(missing)))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records),
            encoding="utf-8",
        )
        print(json.dumps({"reviewed_manifest": str(args.output), "approved": len(approve), "excluded": len(exclude), "total": len(records)}, ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
