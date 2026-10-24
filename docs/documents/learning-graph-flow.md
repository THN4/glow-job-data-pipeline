# Learning Graph: Evidence-to-Skill Flow

## Purpose and scope

This document describes the downstream learning-graph workflow that can use evidence produced by document extraction. For the implemented document-ingestion commands and review stages, see the [document extraction flow](document-extraction-flow.md). It uses canonical names from `core.skills` to connect the domains. The market workflow answers *which skills the job market requests*; the learning graph answers *which skills should be learned first, and what sources support that order*. The fact that many jobs mention both Python and Apache Airflow does not prove that Python is a prerequisite for Airflow.

The current reviewed demo corpus has gone through bounded discovery, page review, approved-HTML parsing, chunking, loading into PostgreSQL/pgvector, and embedding. A command-line semantic-search prototype is available. Systematic retrieval evaluation, automated dependency proposals and review, learning-module curation, and roadmap-agent integration remain follow-up work. The relevant tables are described in the [knowledge domain DBML](../database/schemas/knowledge-schema.dbml) and the [consolidated Glow-Job DBML](../../../docs/schemas/glow-job.dbml).

```text
Market: JSearch → job skills → career skill demand
                          │
                          └── Select skills for learning content
                                      ↓
Knowledge: YAML seeds → bounded crawler → candidate pages → review
                                                     ↓
                                          parse / clean → reviewed topic chunks
                                                     ↓
                                  PostgreSQL + pgvector → semantic retrieval (prototype)
                                                     ↓
                         explicit dependency proposals → human review → verified graph (later)
```

## Downstream learning-graph workflow

### 1. Select skills and sources

Select canonical skills in `core.skills` that support the product goals. `market.career_skill_stats` may help prioritize which skills need learning content when enough market data is available. Source configuration and bounded HTML discovery are implemented; see the [document extraction flow](document-extraction-flow.md) for YAML fields, crawler boundaries, review manifests, and commands.

Each YAML configuration may contain multiple seed URLs for one coherent host/path policy, career tracks, canonical skill names, optional include/exclude patterns, `max_depth`, and `max_pages`. The crawler creates a candidate-page manifest with canonical URL, title, detected headings, crawl depth, content type, and status. Review candidate pages for relevance and access/copy-retention terms before indexing. A seed is depth 0; page limits apply across all seeds in its configuration. Keep different host or path policies in separate configurations.

After approval, the current loader stores source metadata such as page title and canonical URL in `knowledge.knowledge_sources`; the reviewed manifests retain crawl and review details. The parser refetches approved HTML and does not archive a full copy of each original page. If future retention or reproducibility requirements call for archived originals, add object storage and populate the existing optional `storage_key` deliberately.

### 2. Parse documents into traceable text and topics

For approved HTML pages, the parser removes common navigation, breadcrumb, and other non-content elements, then groups text by heading path. It retains the page title, canonical URL, skill/career labels, and content hash in a parsed JSONL review artifact and fails if page content changed after review. The heading-aware chunker splits long prose near a configurable word target at paragraph/sentence boundaries; fenced code stays intact where possible and may be flagged when oversized. Review the JSONL/Markdown artifacts, then the combined reviewed corpus can be loaded into `knowledge.knowledge_sources`, `knowledge.knowledge_chunks`, and `knowledge.knowledge_chunk_skills`. Nova Multimodal Embeddings are stored in pgvector alongside legacy Gemini vectors, and a CLI semantic-search prototype uses the Nova vectors. Markdown, PDF, and plain-text parsing remain future work. Split content at heading boundaries first, then at paragraph or sentence boundaries when a section is too large.

Derive `knowledge_chunks.topic` from the most specific useful heading. Store the full heading path and page URL in chunk metadata so a retrieved result can be cited precisely. Assign skills from the reviewed source configuration and refine them per chunk where a page covers multiple skills. A chunk may map to multiple canonical skills through `knowledge.knowledge_chunk_skills`. If the page has no reliable headings or skill mapping, send it for review rather than guessing. Associate each chunk with a `source_id` and `chunk_index`.

`knowledge.knowledge_chunks` stores searchable text and evidence. The current design and implementation status are described in [skill-knowledge-rag-spec.md](skill-knowledge-rag-spec.md). Dependency extraction remains a later, reviewed phase. If the embedding model or vector dimension changes, keep the database column, stored vectors, and query vectors compatible.

### 3. Propose skill relationships

Use document text as evidence for rules or an LLM to propose relationships such as `prerequisite`, `recommended_before`, or `related`. Each proposal should identify the source and target skills, relationship type, evidence text, and source.

Hypothetical example: a tutorial says, “Learners should know Python before writing Airflow DAGs.” The system could propose `Python → Apache Airflow` as a `prerequisite`, attaching that sentence and its `source_id`. If the document merely mentions Python and Airflow on the same page, that is **not enough** evidence to create a prerequisite edge.

Resolve skill names found in documents against `core.skills` and `core.skill_aliases` before creating relationships that reference `skill_id`. Send unmatched or ambiguous names for review; do not guess or create skills and relationships automatically.

### 4. Review and publish the graph

Verify that the evidence exists in the source, the `source_id` is valid, both skills exist, no edge points from a skill to itself, and the proposed relationship does not conflict with verified edges. For `prerequisite` relationships, check for cycles that would make the learning order unusable. An LLM confidence value may assist review but is not evidence by itself.

Store proposals with `evidence_text`, `source_id`, and `is_verified=false` in `knowledge.skill_dependencies` or a review area designed later. Only relationships reviewed and confirmed by a person should become `is_verified=true` and be used to generate learning sequences.

`knowledge.learning_modules` is intended to define topics and learning outcomes for each skill and level, grounded in sources and verified graph relationships. Do not generate a personalized roadmap directly from raw documents; personalization belongs to the application and requires user-specific information.

## Related tables

| Table in combined DBML | Purpose |
|---|---|
| `core.skills`, `core.skill_aliases` | Canonical skill names and verified alternative names used to connect market and knowledge data. |
| `knowledge.knowledge_sources` | Metadata and original-file location for source documents. |
| `knowledge.knowledge_chunks` | Searchable and citable text segments; embeddings are optional. |
| `knowledge.skill_dependencies` | Graph edges with relationship type, evidence, and verification status. |
| `knowledge.learning_modules` | Learning topics and outcomes by skill and level. |
| `market.career_skill_stats` | Market data for prioritizing which skills get content first; it does not prove prerequisites. |

## Recommended next steps

1. The curated ingestion, persistence, embedding, and basic retrieval prototype are in place for the reviewed demo corpus. Evaluate representative skill-specific, broad-goal, and prerequisite queries before connecting retrieval to answer generation.
2. Add skill dependency proposals only when source text gives explicit evidence. Keep proposals unverified until a person reviews them; only verified edges may affect learning order. Do not infer edges from vector similarity, page order, or market co-occurrence.
3. Add learning modules and broader ingestion after deciding how each module's source evidence and review status will be retained.

The schema now permits a source to be represented once while each chunk maps to one or more canonical skills through `knowledge.knowledge_chunk_skills`. Preserve the source URL and section/page location rather than duplicating the whole file.

The current DBML allows one source_id and one evidence_text per unique dependency row. Keep one reviewed evidence source per edge for the MVP. If multiple citations per edge become necessary, design a separate evidence table in a later schema change.

If market and knowledge data live in separate databases, do not assume their numeric skill_id values will match. Exchange a stable name or key, then resolve it to the destination database's skill_id.
