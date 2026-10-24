# Learning documents domain

`src.documents` contains the document ingestion, preparation, storage,
embedding, and retrieval workflow for skill-learning documents. For the
current reviewed demo corpus, bounded HTML discovery, candidate review,
approved-page parsing, heading-aware chunking, database loading, Nova
Multimodal Embeddings vectors in PostgreSQL/pgvector, embedding checks, and a semantic
search prototype are implemented. The user-facing RAG answer flow is not yet
implemented.

See the [document extraction flow](../../docs/documents/document-extraction-flow.md)
for the end-to-end commands and review points, and the [skill knowledge and RAG
specification](../../docs/documents/skill-knowledge-rag-spec.md) for scope,
current status, and existing-schema constraints.
The [dependency review guide](../../docs/documents/skill-dependency-review-guide.md)
documents the proposal/checkpoint/explicit-apply workflow, including CMD commands.
The current dependency workflow reads every prepared active document chunk in
resumable batches, prepares cited proposals with explicit/inferred basis, and uses
one-key approve/reject plus an approved-only AI handoff export. It does not generate
dependencies across the entire catalog from general model knowledge.
The [learning graph flow](../../docs/documents/learning-graph-flow.md) describes
the broader learning graph design.

| Package | Responsibility and status |
|---|---|
| `ingestion` | Implemented for bounded HTML crawling from YAML source configurations, with candidate-page manifests and explicit review decisions. |
| `parsing` | Implemented for approved HTML pages, extracting heading-path sections and removing common boilerplate. Other input formats remain future work. |
| `chunking` | Implemented as heading-aware chunks with provenance and topic metadata. Review generated chunk artifacts before loading them. |
| `extraction` | Bounded document-backed dependency proposals, local human review, cycle checks and verified lookup are implemented. Structured learning-topic extraction remains future work. |
| `embeddings` | Implemented for the demo with Amazon Nova Multimodal Embeddings and PostgreSQL/pgvector. |
| `schemas` | Source, candidate-page, chunk and dependency proposal/review contracts. |
| Retrieval | A command-line semantic-search prototype is implemented with optional canonical-skill filtering and a configurable result limit. Retrieval evaluation and the application RAG flow remain future work. |

`retrieval/skill_context.py` adds a bounded knowledge-Context preview: approved
canonical filters, active-source coverage, complete-chunk budgets, shared Gemini
text review, exact quote/citation validation and scoped foundation/related mentions.
It separates teaching passages from topic outlines and reports unavailable content
without generating a lesson. The host-facing CLI and [usage guide](../../../docs/rag/skill-knowledge-context-guide.md)
are in the glow-job parent repository; no HTTP RAG endpoint or Roadmap Agent is added.

Keep a traceable source ID, canonical skill ID, section/page reference, and
evidence text with extracted knowledge. Prerequisite claims should be treated
as reviewable evidence, not inferred only from co-occurrence in job postings.
Reuse the canonical skill vocabulary and provider adapters from `src.shared`.

The embedding CLI defaults to Gemini Embedding 2 with 768 dimensions and updates the existing `embedding` column used by retrieval. Pass `--provider nova` to use the optional Amazon Nova Multimodal Embeddings path (1,024 dimensions) in the separate `embedding_nova` column.

Migrations `014`/`015` add reviewed dependencies with scope/conditions, exact
chunk provenance and reviewer metadata. Verified general ordering edges are
separate from document-specific/conditional Context; verification does not
establish that a condition applies to a particular learner.

For a new or updated corpus, preview the reviewed combined chunk file with `python -m scripts.documents.load_chunks`. Apply it only after the preview has no unmatched skill labels and the database migrations are complete. Loading stores source/chunk text and metadata; embeddings are generated separately. Preview pending vectors with `python -m scripts.documents.embed_chunks` (Gemini default). Add `--apply` to generate Gemini vectors in committed batches so a later run can resume. Pass `--provider nova` to use Bedrock and store vectors in the separate Nova column. Run `python -m scripts.documents.check_embeddings` for a read-only check of both vector sets.

Try semantic retrieval with `python -m scripts.documents.search_chunks --query "..."`; add `--skill "..."` to filter by a canonical skill or alias, and `--limit` to change the number of returned chunks (default 5, maximum 50). The current search command returns ranked excerpts; it does not apply a relevance threshold, assemble a context window, or call a language model to generate a cited answer. Dependency proposals and human review use the separate workflow above. Remaining work includes representative-query evaluation, retrieval/context selection policy, source refresh and deduplication policy, dependency expansion/level policies, and the application RAG endpoint.
