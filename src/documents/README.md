# Learning documents domain

`src.documents` is the planned ingestion and preparation pipeline for
skill-learning documents. It is currently a package scaffold; fetching,
parsing, extraction, embedding, and vector-store behavior are not implemented.

| Package | Planned responsibility |
|---|---|
| `ingestion` | Fetch documents from approved sources and record source identity/version. |
| `parsing` | Parse HTML/PDF and clean text while retaining useful structure. |
| `chunking` | Split content by sections or size and attach chunk metadata. |
| `extraction` | Classify topics and extract learning topics or prerequisite claims with evidence. |
| `embeddings` | Create embeddings and write/read chunks through a vector-store adapter. |
| `schemas` | Define document and chunk contracts shared by the document stages. |

Keep a traceable source ID, canonical skill ID, section/page reference, and
evidence text with extracted knowledge. Prerequisite claims should be treated
as reviewable evidence, not inferred only from co-occurrence in job postings.
Reuse the canonical skill vocabulary and provider adapters from `src.shared`.

Implementation decisions still needed include approved source types, refresh
and deduplication policy, chunk size/overlap, embedding provider, and vector
store. The package does not currently expose a RAG endpoint.
