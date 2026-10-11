# Test index

Tests mirror implemented code domains so new work can add focused coverage
without mixing unrelated fixtures and behavior.

| Package | Coverage |
|---|---|
| `tests.market` | JSearch ingestion, job cleaning and normalization, skill extraction/catalog review, loading, and aggregation. |
| `tests.shared` | Reusable LLM client and skill-normalization behavior. |
| `tests.resume` | Resume parsing, extraction-provider contracts, schema validation, and post-processing. |
| `tests.documents` | Add when document ingestion, chunking, extraction, or embeddings are implemented. |

Run the full suite from the repository root with:

```powershell
python -m pytest
```

Pytest discovers tests recursively under `tests/`. Use a focused path while
working on a domain, for example `python -m pytest tests/market`.
For resume processing, run `python -m pytest tests/resume`.
