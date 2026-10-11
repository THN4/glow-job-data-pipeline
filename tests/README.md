# Test index

Tests mirror implemented code domains so new work can add focused coverage
without mixing unrelated fixtures and behavior.

| Package | Coverage |
|---|---|
| `tests.market` | JSearch ingestion, job cleaning and normalization, skill extraction/catalog review, loading, and aggregation. |
| `tests.shared` | Reusable LLM client and skill-normalization behavior. |
| `tests.resume` | Add when the resume package gains behavior. |
| `tests.documents` | Add when document ingestion, chunking, extraction, or embeddings are implemented. |

Run the full suite from the repository root with:

```powershell
python -m pytest
```

Pytest discovers tests recursively under `tests/`. Use a focused path while
working on a domain, for example `python -m pytest tests/market`.
