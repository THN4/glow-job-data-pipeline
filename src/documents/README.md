# Learning documents domain

`src.documents` contains the document ingestion, preparation, storage,
embedding, and retrieval workflow for skill-learning documents. For the
current reviewed demo corpus, bounded HTML discovery, candidate review,
approved-page parsing, heading-aware chunking, database loading, Gemini
Embedding 2 vectors in PostgreSQL/pgvector, embedding checks, and a semantic
search prototype are implemented. The user-facing RAG answer flow is not yet
implemented.

See the [document extraction flow](../../docs/documents/document-extraction-flow.md)
for the end-to-end commands and review points, and the [skill knowledge and RAG
specification](../../docs/documents/skill-knowledge-rag-spec.md) for scope,
current status, and existing-schema constraints.
The [learning graph flow](../../docs/documents/learning-graph-flow.md) describes
the later evidence-backed dependency stage.

| Package | Responsibility and status |
|---|---|
| `ingestion` | Implemented for bounded HTML crawling from YAML source configurations, with candidate-page manifests and explicit review decisions. |
| `parsing` | Implemented for approved HTML pages, extracting heading-path sections and removing common boilerplate. Other input formats remain future work. |
| `chunking` | Implemented as heading-aware chunks with provenance and topic metadata. Review generated chunk artifacts before loading them. |
| `extraction` | Future work: propose evidence-backed prerequisite claims or structured learning topics for review. Current topic paths come from source headings. |
| `embeddings` | Implemented for the demo with Gemini Embedding 2 and PostgreSQL/pgvector. |
| `schemas` | Shared source, candidate-page, and chunk contracts are implemented for the current workflow. |
| Retrieval | A command-line semantic-search prototype is implemented with optional canonical-skill filtering and a configurable result limit. Retrieval evaluation and the application RAG flow remain future work. |

Keep a traceable source ID, canonical skill ID, section/page reference, and
evidence text with extracted knowledge. Prerequisite claims should be treated
as reviewable evidence, not inferred only from co-occurrence in job postings.
Reuse the canonical skill vocabulary and provider adapters from `src.shared`.

The demo uses Gemini Embedding 2 with 768 output dimensions and the existing PostgreSQL + pgvector database; it does not require a separate vector database. Migrations `010`–`013` enable pgvector, create the source/chunk tables, and map chunks to multiple skills.

For a new or updated corpus, preview the reviewed combined chunk file with `python -m scripts.documents.load_chunks`. Apply it only after the preview has no unmatched skill labels and the database migrations are complete. Loading stores source/chunk text and metadata; embeddings are generated separately. Preview pending vectors with `python -m scripts.documents.embed_chunks`. For a first run, generate and inspect a small sample before embedding the remaining chunks. Embeddings are saved in committed batches so a later run can resume. The command estimates request token volume and paces batches to its configured tokens-per-minute target; keep this below the active Gemini project quota. Run `python -m scripts.documents.check_embeddings` for a read-only check of completion, model name, and vector dimensions.

Try semantic retrieval with `python -m scripts.documents.search_chunks --query "..."`; add `--skill "..."` to filter by a canonical skill or alias, and `--limit` to change the number of returned chunks (default 5, maximum 50). The current search command returns ranked excerpts; it does not apply a relevance threshold, assemble a context window, or call a language model to generate a cited answer. Remaining work includes representative-query evaluation, retrieval/context selection policy, source refresh and deduplication policy, evidence-backed dependency proposals and review, and the application RAG endpoint.
