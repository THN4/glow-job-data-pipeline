# Skill Knowledge Ingestion and RAG Specification

## 1. Purpose and status

This document defines the MVP scope for collecting curated skill documents, preparing searchable chunks, and supplying cited context to Glow-Job's roadmap agent.

**Current status:** The current reviewed demo corpus has been crawled from bounded YAML sources, reviewed, parsed from approved HTML, chunked, loaded into the knowledge tables, and embedded with Gemini Embedding 2 (768 dimensions) in PostgreSQL/pgvector. A command-line semantic-search prototype is available with optional canonical-skill filtering and a configurable result limit. The current prototype does not yet evaluate retrieval quality systematically, apply a relevance threshold or reranker, assemble the final context window, or generate cited answers with an LLM. Those are the next RAG tasks. Evidence-backed dependency extraction and review, learning-module curation, and roadmap-agent integration also remain future work.

The MVP focuses on a small, reviewed corpus and retrieval quality. Source seeds and crawl boundaries are curated in YAML. A bounded crawler may discover pages inside those boundaries, but discovered pages must be reviewed before they are indexed. The MVP does not require a continuously running crawler or a complete prerequisite graph.

## 2. Goals

The knowledge layer should:

- Store source metadata and preserve a traceable path from each chunk to its source.
- Discover candidate HTML pages from curated YAML seed URLs using bounded crawl rules, then parse approved HTML, Markdown, text, and text-based PDF documents.
- Split content into coherent, searchable chunks with skill and section metadata.
- Generate embeddings and store them in pgvector.
- Retrieve relevant chunks for a skill gap and return source citations.
- Leave room for reviewed skill dependencies and structured learning modules as later work.

## 3. Non-goals for MVP

The MVP does not:

- Search the public web continuously or discover arbitrary sources at runtime.
- Crawl outside configured hosts or URL path boundaries, or ingest every page from a documentation site.
- Index discovered pages without review in the MVP.
- Treat co-occurring skills as prerequisites.
- Let an unreviewed LLM extraction determine a roadmap.
- Require a separate vector database.
- Implement automatic dependency or learning-module extraction as a runtime requirement.

## 4. Knowledge flow

Curated YAML source configurations (career tracks, skills, and seed URLs)
→ bounded crawl within configured host/path/depth/page limits
→ candidate-page manifest with titles, canonical URLs, headings, and crawl status
→ review and approve candidate pages
→ fetch or reuse approved page content
→ parse and clean
→ deduplicate exact copies
→ chunk by headings and coherent sections
→ attach metadata
→ generate embeddings
→ store source records and chunks
→ retrieve by skill and intent
→ return cited RAG context
→ combine with user, market, skill-gap, and constraint data
→ roadmap agent

Structured dependencies and learning modules are separate knowledge products. They can be added after the ingestion and retrieval path is useful.

## 5. Source collection

### MVP collection method

Source discovery uses curated YAML configuration and a bounded crawler. A person selects the initial seed URLs and the career tracks and canonical skills they are intended to support. The crawler follows links only within the configured host and path boundaries, subject to depth and page limits. It produces a candidate-page manifest; it does not add discovered pages to the searchable knowledge corpus until they are reviewed and approved.

Use one YAML source configuration for a single host and coherent path policy. A configuration may contain multiple seed URLs for the same source scope. Use separate configurations for different hosts or different crawl policies. The human-provided minimum is a stable config ID, career track(s), skill name(s), seed URLs, `max_depth`, and `max_pages`. Publisher may be recorded once per source config when known; page title and heading metadata are read from each page. If `allowed_hosts` or `allowed_path_prefixes` are omitted, derive hosts from the seeds and path prefixes from each seed's parent directory, then show those derived boundaries in the run summary for review. Optional controls include include/exclude path fragments, content types (default `text/html`), and `review_required` (default `true`).

A minimal shape is:

```yaml
schema_version: 1
sources:
  - id: airflow-official-tutorials
    publisher: Apache Software Foundation
    career_tracks: [Data Engineer]
    skills: [Apache Airflow]
    seed_urls:
      - https://airflow.apache.org/docs/apache-airflow/stable/tutorial/index.html
      - https://airflow.apache.org/docs/apache-airflow/stable/tutorial/fundamentals.html
    max_depth: 1
    max_pages: 12
```

The crawler must enforce the configured host/path boundaries, depth and page limits, avoid revisiting canonicalized URLs, respect robots rules, and use a configurable request rate. The first discovery implementation fetches ordinary `text/html` pages without login or browser-rendered JavaScript. Markdown, plain text, and text-based PDFs may enter through a separately approved input path; scanned PDFs that need OCR go to review rather than being silently indexed.

The initial Airflow pilot configuration is maintained in [`config/document_sources.yaml`](../../config/document_sources.yaml). `include_patterns` and `exclude_patterns` are case-insensitive fragments matched against the URL path, not regular expressions. If include patterns are set, a URL must match at least one; exclude patterns always take precedence.

The discovery pass should produce one JSONL manifest record per discovered page, including source-config ID, URL, canonical URL, page title, publisher and source type when known, career tracks, skills, detected headings, content type, crawl depth, HTTP status, and content hash when available. Keep `fetch_status` (`fetched`, `failed`, `blocked_by_robots`, or `unsupported_content_type`) separate from `review_status` (`pending`, `approved`, or `excluded`). Review candidate pages for relevance and access/copy-retention terms before indexing. Keep the YAML and run-specific manifest as versioned ingestion artifacts so a crawl can be reproduced and audited.

Prefer, in order:

1. Official documentation
2. Official learning paths
3. Official tutorials
4. Reputable university or industry learning material
5. Curated roadmaps as supporting sources

After approval, record the canonical page URL, publisher, title, source type, and collection time. Keep the original page or downloaded file in object storage when applicable and store its storage key in the source record. Use the manifest for source-level details not represented by the existing DBML, such as crawl depth, content hash, and review history.

A career track is a curation and reporting dimension; it is not a field in the current knowledge schema. Resolve configured skill names to canonical skills. Register a shared page once, then associate each reviewed chunk with every relevant canonical skill through `knowledge.knowledge_chunk_skills`. A chunk may map to multiple skills; if its skill cannot be identified reliably, leave it without a skill mapping rather than guessing.

## 6. PostgreSQL and schema baseline

Use the existing PostgreSQL database and the knowledge schema. Use pgvector as a PostgreSQL extension; do not provision a separate vector database for MVP.

The existing knowledge DBML is the source of truth for table names, relationships, and core columns:

- knowledge.knowledge_sources: source metadata and optional storage key
- knowledge.knowledge_chunks: source-linked text, topic, metadata, embedding model, and embedding
- knowledge.knowledge_chunk_skills: many-to-many mapping from chunks to canonical skills
- knowledge.skill_dependencies: evidence-backed relationships between canonical skills
- knowledge.learning_modules: structured topics and outcomes by skill and proficiency level

Use core.skills as the canonical skill catalog. Keep source_id and chunk-to-skill relationships consistent with the DBML.

Do not add columns just because a parser can produce them. For MVP, source-level details such as document format, source version, and source content hash belong in an ingestion manifest stored with the source file or source registry artifact. Per-chunk details such as language, heading path, page number, chunk hash, and parser details may use the existing knowledge_chunks.metadata JSONB field. Promote a value to a dedicated column only when a concrete query or integrity requirement needs it and the DBML and migration are updated together.

The migration set enables pgvector and creates the MVP source and chunk tables. The demo embedding configuration is Gemini Embedding 2 with 768 output dimensions; the database column is `vector(768)`. Keep the configured model and SQL dimension in sync. Before applying migrations:

- Confirm the PostgreSQL environment supports the vector extension.
- Make any SQL vector dimension and operator/index configuration agree with the configured model.
- Apply knowledge migrations through the repository migration runner.

## 7. Document parsing and provenance

For the MVP, crawl ordinary HTML pages and parse approved HTML, Markdown, plain text, and text-based PDF inputs. Prefer structured HTML or Markdown. Remove navigation, cookie banners, and other non-content elements while retaining useful heading hierarchy and source locations. Do not require a browser runtime for JavaScript-rendered pages in the MVP; route pages whose main content is unavailable to review.

Topic assignment should use the page's own structure first: breadcrumb, page title, and H1–H3 heading path. Split chunks at heading boundaries and store the most specific useful topic in `knowledge_chunks.topic`; retain the complete `heading_path`, page URL, and extraction details in `knowledge_chunks.metadata`. The skill comes from the reviewed YAML/source assignment and may be refined per chunk during review; do not infer a skill solely from a page title. If headings are missing or extraction produces a weak structure, mark the page or chunk for review instead of inventing a topic. LLM-based topic classification is not required for the MVP.

Each chunk must retain:

- source_id
- zero or more canonical skill IDs in `knowledge.knowledge_chunk_skills` when known
- chunk_index within its source
- section or heading path when available
- source URL and title through the related source record
- language or page location in metadata when available

Detect source updates through a source-level content hash or version in the ingestion manifest. Re-ingestion must not silently mix old and new content. For MVP, replace chunk rows for a source transactionally and update the source record; retain old source files under versioned storage keys when retention is required. Keep per-chunk hashes in chunk metadata when useful.

## 8. Chunking and deduplication

Use headings and subsection boundaries first. A chunk should contain one coherent concept or subsection and be understandable with its heading context.

When a section is too large, split it at paragraph or sentence boundaries and stay within the selected embedding model's input limit. A size around 300–500 words may be used as an initial fallback, not as a universal rule. Tune chunk size and overlap using retrieval examples.

Preserve code blocks, tables, lists, and warnings as intact as practical. Avoid both whole-document chunks and fragments that lose necessary context.

For MVP, normalize text and use a content hash in metadata to detect exact duplicates. Near-duplicate detection can be deferred. Do not merge distinct source records solely because their content is similar.

## 9. Metadata

Keep per-chunk operational and citation metadata in the existing knowledge_chunks.metadata JSONB field where it is not already a dedicated DB column. A chunk metadata object may include:

- language
- heading_path or section_title (used to derive the `topic` value)
- breadcrumb and page title when available
- page_number or page URL
- chunk content hash
- parser name and parser version
- document format
- extraction notes

Metadata must not replace the source foreign key or the canonical skill mappings in `knowledge.knowledge_chunk_skills`.

## 10. Embeddings and vector index

Generate an embedding for each cleaned chunk using the Gemini Embedding 2 document format `title: {title} | text: {content}` and store the model identifier with it. At query time, format the search text as `task: search result | query: {query}`. The chunk content is what the language model reads; the embedding is used for similarity search. The SQL column is `vector(768)`, so verify the returned vector length before writing it.

All vectors searched together must use a compatible model and dimension. If the model changes, re-embed the affected chunks before searching them together. Do not mix incompatible vector dimensions or silently reuse vectors produced by a different model.

An HNSW index with cosine distance may be added when corpus size and query performance justify it. It is an implementation optimization, not a prerequisite for a small demo. Ensure the query operator and index operator class use the same distance metric.

## 11. Retrieval

The requirements in this section describe the intended retrieval behavior. The current `scripts.documents.search_chunks` prototype embeds a natural-language query, optionally filters to one canonical skill or alias, ranks matching chunks by cosine similarity, and returns up to five excerpts by default (configurable from 1 to 50). It currently has no minimum-relevance threshold, reranking, context-window assembly, or LLM answer generation. Similarity is a ranking score, not a confidence probability. Treat off-topic top results as retrieval failures or corpus coverage gaps rather than as evidence.

Build retrieval queries from the skill gap and intent, such as:

- Find foundational topics for a missing skill.
- Find topics that help move from the user's current level to the target level.
- Find explicit prerequisite evidence for a skill.

When a target skill is known, filter chunks through `knowledge.knowledge_chunk_skills.skill_id` before semantic ranking. If a verified dependency identifies prerequisite skills and the request needs learning material for those skills, include those skill IDs in a separate retrieval step. Do not expect filtering only on the target skill to return full learning content for another skill.

Return the relevant chunk text with source ID, canonical URL, title, heading/page location, associated skill IDs, and retrieval score. Preserve citations when constructing RAG context. If no relevant result meets the configured relevance threshold, return an explicit no-evidence or coverage-gap result instead of fabricating an answer.

## 12. Skill dependencies

The skill_dependencies table remains part of the planned knowledge schema, but an exhaustive graph is not required for MVP. An absent relationship means unknown, not that no prerequisite exists.

Use the existing dependency types:

- prerequisite: required foundation, supported by explicit evidence
- recommended_before: useful preparation, but not a hard gate
- related: relevant relationship without an ordering claim

The current table has no career or proficiency scope for an edge. If evidence limits a relationship to a role or level, do not publish it as a universal dependency; keep it as cited retrieval evidence until a context-aware representation is designed.

Only create a dependency when a source explicitly supports the relationship. Keep evidence_text and source_id. Resolve both skill names to core.skills before persistence. Route ambiguous or unsupported skill names for review.

An extracted proposal must remain is_verified=false until reviewed. Runtime roadmap logic may use only verified relationships. Confidence can help prioritize review; it does not replace evidence or verification. Do not infer an edge from job co-occurrence or from the order of topics on a web page.

The current schema stores one source and one evidence text per edge. For MVP, keep one reviewed evidence source per relationship. A separate multi-evidence table can be considered if the product later needs multiple citations per edge.

## 13. Learning modules

Learning modules represent level-specific topics, outcomes, and sequence where a source explicitly provides a curriculum or where a human has curated one. They are not the same thing as retrieved chunks.

Automatic learning-module extraction and use in personalized roadmaps are outside the first retrieval MVP. The current DBML does not link a module to its supporting source, so do not claim full source provenance for stored modules until a provenance design is agreed. A later phase should decide how module evidence and review status are recorded before loading modules into the database.

Do not treat heading order alone as proof of a universal learning sequence. Mark inferred order as a suggested interpretation and retain its evidence.

## 14. RAG context contract

The retrieval layer returns supporting material, not a final roadmap. A RAG context item should include:

- skill ID and canonical skill name
- intent
- chunk ID and source ID
- content
- source title and URL
- section/page location when available
- retrieval score
- any coverage-gap or verification status relevant to the item

The context builder combines retrieved chunks with user profile, target career, market requirements, skill gap, verified dependencies when available, and user constraints. Keep the context within an agreed token budget and remove duplicate chunks before sending it to the roadmap agent.

The roadmap agent receives the assembled agent context. It does not parse documents or query pgvector directly.

## 15. Evaluation and acceptance criteria

Prepare a small set of representative queries covering missing skills, level gaps, and explicit prerequisite lookup. Review retrieval results manually before connecting them to roadmap generation. This evaluation has not yet been completed systematically for the current corpus.

The MVP is acceptable when:

1. Each chunk can be traced to its source and relevant section.
2. Skill filtering returns chunks for the requested canonical skill.
3. Test queries return useful evidence in the selected top results.
4. Returned citations open the source material and identify the relevant location where possible.
5. Unverified dependencies are not used as roadmap requirements.
6. Unsupported prerequisites and empty retrieval results are reported as coverage gaps.
7. The system does not treat market co-occurrence as learning evidence.
8. The agent context includes market, user, skill-gap, and retrieval data without requiring the agent to access the vector store.

## 16. Development phases

### Phase 1 — Bounded-crawl retrieval MVP

**Status: ingestion, persistence, embeddings, and a basic retrieval prototype are implemented for the current reviewed demo corpus.** Source configurations, bounded discovery, candidate review, approved HTML parsing, heading-aware chunking, database loading, embedding checks, and top-k vector search are available. Remaining Phase 1 work is to evaluate representative queries, improve retrieval/context selection based on evidence, define source refresh and deduplication behavior, and connect retrieved chunks to cited answer generation.

### Phase 2 — Reviewed dependencies

**Status: planned.** Extract dependency proposals only from explicit source evidence, resolve them against `core.skills`, review them, and publish only verified edges. The embedding model does not create dependency relationships by itself.

### Phase 3 — Learning modules

**Status: planned.** Agree on source provenance and review status for modules, then curate or extract level-specific learning outcomes and sequences.

### Phase 4 — Agent context integration

**Status: planned.** Assemble market, user, skill gap, verified structured knowledge, and RAG context into the agent context contract.

## 17. Responsibilities

Data / RAG owns source curation support, parsing, cleaning, chunking, embedding, retrieval, provenance, and reviewed knowledge persistence.

The backend owns API orchestration, user data, and roadmap persistence.

The AI/roadmap agent owns reasoning, prioritization based on supplied structured inputs, roadmap composition, and explanations. It must not invent market facts or treat unverified relationships as requirements.

## 18. Implementation boundary

This document separates implemented ingestion/retrieval foundations from the remaining RAG and roadmap work. The current implementation covers bounded HTML discovery, manual page review, approved HTML parsing, chunk generation, persistence in the knowledge schema, Gemini Embedding 2 vectors in pgvector, embedding checks, and a basic semantic-search command. It does not yet provide systematic retrieval evaluation, relevance-threshold or reranker behavior, LLM context assembly and cited answer generation, automated evidence-backed dependency extraction/review, learning-module extraction, or roadmap-agent integration.

Implementation should extend the existing documents scaffold and reuse the existing database model. Any schema change must be reflected in the knowledge DBML and migration together; do not create a parallel schema or redesign the tables without a demonstrated requirement. New documents should follow the existing review, parse, chunk, load, and embedding workflow. When model or vector dimensions change, preserve compatibility by re-embedding affected corpus vectors before searching them together.
